"""Agent calls as events: agent.spawned, agent.state and cost.estimate (G01).

Each test runs agents from a job of a real run, through the bus and the store, with a scripted
backend, and checks the run's log against the event schemas.
"""

import asyncio
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_support import ScriptedBackend
from repro.agents import (
    SLOTS,
    AgentRequest,
    AgentResult,
    Budget,
    Dispatch,
    LLMBackend,
    Progress,
    RunLedger,
    Usage,
    run_agent,
)
from repro.bus import EventBus
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, Orchestrator, RunSpec
from repro.store import StoreReader, StoreWriter
from repro_events.log import LogLine, validate_log
from repro_events.schemas import SchemaSet
from store_support import started_writer

SPEC = RunSpec(
    repo_name="fixture/honest-fix",
    base=GitRef("main", "fe755e41c8d49ca8e2f60e44cd6eeb6e3ab93acc"),
    head=GitRef("fix/parse-date-utc", "44c5e145df93b6051f6a2fb2e795ceef189e9c0d"),
    pr_title="Parse dates as UTC",
)
REVIEW = OnFailure("agent_failed", "the claims' review")
REQUEST = AgentRequest(
    role="review",
    system_prompt="Judge the claim.",
    prompt="Is it supported?",
    model="claude-opus-5-5",
    prompt_version="r/1",
    budget=Budget(max_turns=4),
)
WORK = (
    Progress("thinking", 1),
    Progress("thinking", 1, detail="Reading the diff."),
    Progress("thinking", 1, detail="Reading the diff."),  # the same again: not re-emitted
    Progress("tool_call", 2, "mcp__repro__read_evidence", "read_evidence({'id': 'ev_1'})"),
)
USAGE = Usage(input_tokens=1200, output_tokens=300, cache_read_tokens=800, cost_usd=0.0123)


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


def run_job(
    writer: StoreWriter, work: Callable[[JobContext], None], *, timeout_s: float = 60
) -> tuple[str, str, list[dict[str, Any]]]:
    """Runs one review job; the run's outcome, the job's status and the run's events."""
    orchestrator = Orchestrator(EventBus(writer), concurrency=1)
    result = orchestrator.run(SPEC, [Job("review", "review", work, REVIEW, timeout_s=timeout_s)])
    with StoreReader(writer.path) as reader:
        events = [event.envelope() for event in reader.iter_events(result.run_id)]
    return result.outcome, dict(result.jobs)["review"], events


def agents(
    backend: LLMBackend,
    dispatch: Dispatch,
    count: int,
    results: list[AgentResult],
    ledger: RunLedger | None = None,
) -> Callable[[JobContext], None]:
    def work(ctx: JobContext) -> None:
        async def all_of_them() -> list[AgentResult]:
            calls = [
                run_agent(ctx, backend, dispatch, REQUEST, agent=dispatch.agent_id(), ledger=ledger)
                for _ in range(count)
            ]
            return await asyncio.gather(*calls)

        results.extend(asyncio.run(all_of_them()))

    return work


def of_agents(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["agent"] is not None]


def check_log(schema_set: SchemaSet, events: list[dict[str, Any]]) -> None:
    lines = [LogLine(i + 1, event) for i, event in enumerate(events)]
    assert validate_log(schema_set, lines) == []


def test_an_agent_call_is_reported_as_it_runs(writer: StoreWriter, schema_set: SchemaSet) -> None:
    backend = ScriptedBackend(AgentResult("ok", text="Supported.", turns=3, usage=USAGE), WORK)
    results: list[AgentResult] = []
    outcome, status, events = run_job(writer, agents(backend, Dispatch(2), 1, results))

    assert (outcome, status) == ("completed", "ok")
    assert results == [backend.result]
    check_log(schema_set, events)
    mine = of_agents(events)
    assert {(event["agent"], event["stage"]) for event in mine} == {("a01", "review")}
    assert [(e["kind"], e["status"]) for e in mine] == [
        ("agent.spawned", "start"),
        *[("agent.state", "progress")] * 4,
        ("agent.state", "ok"),
        ("cost.estimate", "ok"),
    ]
    assert mine[0]["payload"] == {
        "role": "review",
        "model": "claude-opus-5-5",
        "prompt_version": "r/1",
        "slot": 0,
    }
    assert [event["payload"] for event in mine[1:6]] == [
        {"state": "thinking", "tool": None, "detail": None, "progress": 0.0},  # starting
        {"state": "thinking", "tool": None, "detail": None, "progress": 0.25},
        {"state": "thinking", "tool": None, "detail": "Reading the diff.", "progress": 0.25},
        {
            "state": "tool_call",
            "tool": "mcp__repro__read_evidence",
            "detail": "read_evidence({'id': 'ev_1'})",
            "progress": 0.5,
        },
        {"state": "done", "tool": None, "detail": "3 turns", "progress": 1.0},
    ]
    assert mine[6]["payload"] == {
        "model": "claude-opus-5-5",
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_tokens": 800,
        "usd": 0.0123,
        "estimate": True,
        "source": "live",
    }


def test_a_call_that_ends_without_output_is_a_failed_agent(
    writer: StoreWriter, schema_set: SchemaSet
) -> None:
    result = AgentResult("max_turns", turns=4, detail="error_max_turns", usage=USAGE)
    _, status, events = run_job(writer, agents(ScriptedBackend(result), Dispatch(1), 1, []))

    assert status == "ok"  # the job decides what a failed agent means for the run
    check_log(schema_set, events)
    mine = of_agents(events)
    assert [e["kind"] for e in mine] == [
        "agent.spawned",
        "agent.state",
        "agent.state",
        "cost.estimate",
    ]
    assert mine[2]["status"] == "fail"
    assert mine[2]["payload"] == {
        "state": "failed",
        "tool": None,
        "detail": "max_turns: error_max_turns",
        "progress": None,
    }


def test_a_call_with_no_usage_reports_no_cost(writer: StoreWriter) -> None:
    result = AgentResult("timeout", detail="took over 600 s")
    _, _, events = run_job(writer, agents(ScriptedBackend(result), Dispatch(1), 1, []))
    assert [e["kind"] for e in of_agents(events)][-1] == "agent.state"


def test_agents_wait_for_a_place_and_a_slot(writer: StoreWriter, schema_set: SchemaSet) -> None:
    """Fourteen agents, two at a time: never more than two run, never more than twelve hold a
    slot, the queued ones show ``waiting``, and every one finishes."""
    backend = ScriptedBackend(AgentResult("ok", turns=1, usage=USAGE), WORK[:1])
    results: list[AgentResult] = []
    _, status, events = run_job(writer, agents(backend, Dispatch(2), 14, results))

    assert status == "ok"
    assert len(results) == 14
    assert backend.peak == 2
    check_log(schema_set, events)
    mine = of_agents(events)
    seated: dict[str, int] = {}
    most = 0
    for event in mine:
        payload = event["payload"]
        if event["kind"] == "agent.spawned":
            assert payload["slot"] not in seated.values()  # a slot holds one agent at a time
            seated[event["agent"]] = payload["slot"]
            most = max(most, len(seated))
        elif event["kind"] == "agent.state" and payload["state"] in ("done", "failed"):
            del seated[event["agent"]]
    assert most == SLOTS
    assert seated == {}
    spawned = [e["agent"] for e in mine if e["kind"] == "agent.spawned"]
    assert sorted(spawned) == [f"a{n:02d}" for n in range(1, 15)]
    waited = {e["agent"] for e in mine if e["payload"].get("state") == "waiting"}
    assert len(waited) >= SLOTS - 2  # the ten seated behind the first two at least
    done = [e for e in mine if e["payload"].get("state") == "done"]
    assert len(done) == 14


def test_cancelling_the_run_cancels_the_call(writer: StoreWriter) -> None:
    hold = threading.Event()
    backend = ScriptedBackend(AgentResult("ok"), hold=hold)
    dispatch = Dispatch(1)
    started = threading.Event()

    def work(ctx: JobContext) -> None:
        async def one() -> AgentResult:
            started.set()
            return await run_agent(ctx, backend, dispatch, REQUEST, agent="a01")

        asyncio.run(one())

    orchestrator = Orchestrator(EventBus(writer), concurrency=1)
    handle = orchestrator.start(SPEC, [Job("review", "review", work, REVIEW, timeout_s=60)])
    assert started.wait(10)
    while backend.running == 0:
        threading.Event().wait(0.01)
    handle.cancel()
    result = handle.wait(30)

    assert result.outcome == "cancelled"
    assert backend.cancelled == 1
    assert dispatch.try_seat() == 0  # its slot and place were given back
    assert dispatch.try_start()
    hold.set()


def test_a_call_that_overruns_its_job_is_cancelled(writer: StoreWriter) -> None:
    hold = threading.Event()
    backend = ScriptedBackend(AgentResult("ok"), hold=hold)
    _, status, events = run_job(writer, agents(backend, Dispatch(1), 1, []), timeout_s=0.5)

    assert status == "timeout"
    deadline = threading.Event()
    for _ in range(200):  # the abandoned job notices within a poll
        if backend.cancelled:
            break
        deadline.wait(0.05)
    assert backend.cancelled == 1
    hold.set()
    assert "done" not in {e["payload"].get("state") for e in of_agents(events)}


def test_a_replayed_call_reports_each_models_recorded_cost(
    writer: StoreWriter, schema_set: SchemaSet
) -> None:
    small = Usage(input_tokens=90, output_tokens=10, cache_read_tokens=0, cost_usd=0.0004)
    by_model = {"claude-opus-5-5": USAGE, "claude-haiku-5-5": small}
    result = AgentResult("ok", turns=1, usage=USAGE, by_model=by_model, replayed=True)
    _, _, events = run_job(writer, agents(ScriptedBackend(result), Dispatch(1), 1, []))

    check_log(schema_set, events)
    costs = [e["payload"] for e in of_agents(events) if e["kind"] == "cost.estimate"]
    assert [(c["model"], c["usd"], c["source"]) for c in costs] == [
        ("claude-haiku-5-5", 0.0004, "cassette"),
        ("claude-opus-5-5", 0.0123, "cassette"),
    ]


def test_a_run_whose_agent_budget_is_spent_starts_no_more_calls(
    writer: StoreWriter, schema_set: SchemaSet
) -> None:
    """A $0.02 run budget, calls estimated at $0.0123: the first may spend $0.02, the second
    what is left, and the third finds nothing left and is never made."""
    backend = ScriptedBackend(AgentResult("ok", turns=1, usage=USAGE))
    ledger = RunLedger(limit_usd=0.02)
    results: list[AgentResult] = []
    _, status, events = run_job(writer, agents(backend, Dispatch(1), 3, results, ledger))

    assert status == "ok"
    check_log(schema_set, events)
    budgets = [request.budget.max_budget_usd for request in backend.requests]
    assert budgets == [0.02, pytest.approx(0.02 - 0.0123)]
    assert sorted(r.outcome for r in results) == ["max_budget", "ok", "ok"]
    assert ledger.spent_usd == pytest.approx(0.0246)
    failed = [e for e in of_agents(events) if e["payload"].get("state") == "failed"]
    assert [e["payload"]["detail"] for e in failed] == [
        "max_budget: the run's agent budget of $0.02 is spent"
    ]
    assert len([e for e in of_agents(events) if e["kind"] == "cost.estimate"]) == 2
