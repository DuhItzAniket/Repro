"""An agent call as events: ``agent.spawned``, ``agent.state`` and ``cost.estimate`` (G01).

The cockpit's dispatch and workspace panels are projections of these (ARCHITECTURE §5.2,
DESIGN.md, the agents panel). One agent's events, in order:

- ``agent.spawned`` (``start``) once it has a dispatch slot;
- ``agent.state`` ``waiting``, only if it must wait to start (the run's concurrency is taken);
- ``agent.state`` ``thinking`` as it starts, then ``thinking`` and ``tool_call`` as the model
  works, with what it does as ``detail``; ``progress`` is the share of its turn budget used;
- ``agent.state`` ``done`` (``ok``, progress 1) or ``failed`` (``fail``, saying why);
- ``cost.estimate`` (``ok``): the client-side estimate, one per model the call used whose
  price is known, with its ``source``: ``live``, or ``cassette`` when the call was replayed
  (what it cost when recorded).

With a ``RunLedger`` that has a limit, a call starts only if some of the run's agent budget is
left, with its dollar budget cut down to what is left (``repro.agents.cost``); one that finds
none ends ``failed`` with ``max_budget``, having called nothing.

Cancelling the job (the run is cancelled, or the job overran its time) cancels the call, which
ends its Claude Code process, and raises ``JobCancelled``; the job emits nothing more.
"""

import asyncio
from collections.abc import Awaitable
from dataclasses import replace
from typing import Final, Literal

from repro.agents.backend import AgentRequest, AgentResult, LLMBackend, Progress, Usage
from repro.agents.cost import RunLedger
from repro.agents.dispatch import POLL_S, Dispatch
from repro.orchestrator.jobs import JobContext

#: How long a cancelled call has to end before the job gives up on it.
CANCEL_WAIT_S: Final = 10.0
DETAIL_MAX: Final = 500

State = Literal["waiting", "thinking", "tool_call", "done", "failed"]


def _state(
    ctx: JobContext,
    agent: str,
    state: State,
    *,
    status: str = "progress",
    tool: str | None = None,
    detail: str | None = None,
    progress: float | None = None,
) -> None:
    payload = {
        "state": state,
        "tool": tool,
        "detail": detail[:DETAIL_MAX] if detail else None,
        "progress": progress,
    }
    ctx.emit("agent.state", status=status, payload=payload, agent=agent)


async def _until_cancelled(ctx: JobContext, call: Awaitable[AgentResult]) -> AgentResult:
    """Awaits the call, or cancels it as soon as the job is cancelled."""
    task = asyncio.ensure_future(call)
    while True:
        done, _ = await asyncio.wait({task}, timeout=POLL_S)
        if done:
            return task.result()
        if ctx.cancelled:
            task.cancel()
            await asyncio.wait({task}, timeout=CANCEL_WAIT_S)
            ctx.check()


async def _call(
    ctx: JobContext, backend: LLMBackend, request: AgentRequest, agent: str
) -> AgentResult:
    """The backend's call, its progress shown as ``agent.state`` events."""
    _state(ctx, agent, "thinking", progress=0.0)
    last: tuple[str, str | None, str | None] | None = None

    def on_progress(update: Progress) -> None:
        nonlocal last
        key = (update.state, update.tool, update.detail)
        if key == last:  # nothing new to show
            return
        last = key
        share = min(1.0, update.turn / request.budget.max_turns)
        _state(ctx, agent, update.state, tool=update.tool, detail=update.detail, progress=share)

    return await _until_cancelled(ctx, backend.run(request, on_progress))


def _costs(ctx: JobContext, request: AgentRequest, result: AgentResult, agent: str) -> None:
    """One ``cost.estimate`` per model the call used and whose price is known."""
    by_model = dict(result.by_model)
    if not by_model and result.usage != Usage():
        by_model = {request.model: result.usage}
    for model, usage in sorted(by_model.items()):
        if not usage.priced:
            continue
        cost = {
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "usd": usage.cost_usd,
            "estimate": True,
            "source": "cassette" if result.replayed else "live",
        }
        ctx.emit("cost.estimate", status="ok", payload=cost, agent=agent)


async def run_agent(
    ctx: JobContext,
    backend: LLMBackend,
    dispatch: Dispatch,
    request: AgentRequest,
    *,
    agent: str,
    ledger: RunLedger | None = None,
) -> AgentResult:
    """Runs one agent call in a dispatch slot, as events in the job's stage; within the run's
    agent budget when there is a ``ledger`` with a limit."""
    slot = await dispatch.seat(ctx.check)
    try:
        spawned = {
            "role": request.role,
            "model": request.model,
            "prompt_version": request.prompt_version,
            "slot": slot,
        }
        ctx.emit("agent.spawned", status="start", payload=spawned, agent=agent)
        if not dispatch.try_start():
            _state(ctx, agent, "waiting", progress=0.0)
            await dispatch.start(ctx.check)
        try:
            reservation = (ledger or RunLedger()).reserve(request.budget)
            if reservation is None:
                limit = ledger.limit_usd if ledger is not None else None
                spent = AgentResult(
                    "max_budget", detail=f"the run's agent budget of ${limit:g} is spent"
                )
                _state(ctx, agent, "failed", status="fail", detail=f"max_budget: {spent.detail}")
                return spent
            result: AgentResult | None = None
            try:
                bounded = replace(request, budget=reservation.budget)
                result = await _call(ctx, backend, bounded, agent)
            finally:
                if ledger is not None:
                    ledger.settle(reservation, result.usage if result is not None else Usage())
        finally:
            dispatch.stop()
    finally:
        dispatch.unseat(slot)
    if result.outcome == "ok":
        turns = f"{result.turns} turn{'s' if result.turns != 1 else ''}"
        _state(ctx, agent, "done", status="ok", detail=turns, progress=1.0)
    else:
        why = f"{result.outcome}: {result.detail}" if result.detail else result.outcome
        _state(ctx, agent, "failed", status="fail", detail=why)
    _costs(ctx, request, result, agent)
    return result
