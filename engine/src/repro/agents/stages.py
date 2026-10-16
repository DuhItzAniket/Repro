"""The pipeline's agent jobs (G04 on): each runs its agents through ``run_agent`` and emits
what they found as events, and a call that ends without a usable answer fails the job, which
the card then lists as ``agent_failed`` (ground rule 3: never unverified silently).

- ``claims`` (stage ``read``, G04): the reader agent on the PR's text and the change's files,
  then one ``claim.extracted`` per claim. It needs nothing else from the run, so it runs while
  the build and run stages do.
- ``review`` (G05): after every other job, each claim's reviewer, its verdict checked.
- ``gap`` (G06): after the review, the differences no verdict accounts for mapped to the
  supported claims that explain them.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from repro.agents.backend import AgentResult, ReproTool
from repro.agents.events import run_agent
from repro.agents.evidence import EvidenceView
from repro.agents.gap import MAX_ITEMS as GAP_MAX_ITEMS
from repro.agents.gap import candidates, check_mapping, explainers, gap_request, verdicts
from repro.agents.prompts import Prompt, load_prompt
from repro.agents.reader import PrText, read_claims, reader_request
from repro.agents.reviewer import MAX_INLINE_ITEMS, relevant, reviewer_request
from repro.agents.setup import AgentSetup
from repro.agents.sources import RepoSources
from repro.agents.tools import EvidenceTools
from repro.agents.validate import Rejection, check
from repro.gitops import Git
from repro.gitops.changes import diff
from repro.orchestrator import Job, JobContext, OnFailure

READER_PROMPT: Final = "reader"


class AgentFailedError(RuntimeError):
    """An agent call ended without an answer the job can use."""


@dataclass(slots=True)
class AgentState:
    """What the agent jobs hand on to each other."""

    #: The claims read from the PR (``claim.extracted`` payloads' ``claim``); None until read.
    claims: list[dict[str, Any]] | None = None
    files: list[str] = field(default_factory=list)


def changed_files(git: Git, base: str, head: str) -> list[str]:
    """The paths the change touches, as git lists them (renames by their new path)."""
    return sorted({change.path for change in diff(git, base, head)})


def commit_messages(git: Git, base: str, head: str) -> list[str]:
    """The messages of the commits ``head`` has and ``base`` does not, oldest first."""
    raw = git.run("log", "--reverse", "--format=%B%x00", "--end-of-options", f"{base}..{head}")
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    return [message.strip() for message in text.split("\x00") if message.strip()]


def _call(ctx: JobContext, setup: AgentSetup, build: Callable[[], Any], agent: str) -> AgentResult:
    request = build()
    return asyncio.run(
        run_agent(ctx, setup.backend, setup.dispatch, request, agent=agent, ledger=setup.ledger)
    )


def claims_job(
    git: Git, *, base: str, head: str, pr: PrText, setup: AgentSetup, state: AgentState
) -> Job:
    def run(ctx: JobContext) -> None:
        files = changed_files(git, base, head)
        state.files = files
        if not pr.parts:
            ctx.log("the pull request has no text: no claims to read", level="warning")
            state.claims = []
            return
        prompt = load_prompt(READER_PROMPT)
        agent = setup.dispatch.agent_id()
        ctx.log(f"reading the pull request's claims ({setup.label}, {setup.model('read')})")
        result = _call(
            ctx,
            setup,
            lambda: reader_request(pr, files, prompt, setup.model("read")),
            agent,
        )
        if result.outcome != "ok":
            raise AgentFailedError(f"the reader ended {result.outcome}: {result.detail}"[:500])
        claims = read_claims(result.structured, files, [source for source, _ in pr.parts])
        for claim in claims:
            ctx.emit("claim.extracted", status="ok", payload={"claim": claim}, agent=agent)
        ctx.log(f"{len(claims)} claim{'s' if len(claims) != 1 else ''} read from the pull request")
        state.claims = claims

    return Job(
        "claims",
        "read",
        run,
        OnFailure(
            reason="agent_failed",
            detail="the pull request's claims could not be read",
            resolution="check the agent settings, the API or the cassettes, then run again",
        ),
    )


#: How long the review job waits for its first event to be stored (as the card job does).
COMMIT_WAIT_S: Final = 60.0
REVIEWER_PROMPT: Final = "reviewer"
#: Attempts per claim: the verdict, and one more after a rejection, told why.
ATTEMPTS: Final = 2
SHORT: Final = 1000
#: ``verdict.issued``'s status for each verdict (ADR-0015's sense).
VERDICT_STATUS: Final = {"supported": "ok", "contradicted": "fail", "unverifiable": "warn"}


def _missing(
    ctx: JobContext,
    reason: str,
    detail: str,
    claim: Mapping[str, Any],
    resolution: str,
) -> None:
    item = {
        "reason": reason,
        "targets": list(claim.get("targets") or []),
        "detail": detail[:SHORT],
        "resolution": resolution,
    }
    ctx.emit("missing.recorded", status="warn", payload={"missing": item})


async def review_claim(
    ctx: JobContext, setup: AgentSetup, context: "ReviewContext", claim: Mapping[str, Any]
) -> None:
    """One claim: a reviewer's verdict, checked; or why there is none."""
    items = relevant(context.view, claim)
    if not items:
        _missing(
            ctx,
            "claim_unverifiable",
            f"{claim['id']}: no evidence about it, so nothing could support it",
            claim,
            "a test that exercises what the claim is about",
        )
        return
    ids = [item.id for item in items]
    feedback, rejection, agent = "", None, ""
    for _ in range(ATTEMPTS):
        agent = setup.dispatch.agent_id()
        request = reviewer_request(
            claim,
            items,
            context.sources,
            tools=context.tools if len(items) > MAX_INLINE_ITEMS else (),
            prompt=context.prompt,
            model=setup.model("review"),
            claims=context.claims,
            feedback=feedback,
        )
        result = await run_agent(
            ctx, setup.backend, setup.dispatch, request, agent=agent, ledger=setup.ledger
        )
        if result.outcome == "invalid_output":
            rejection = Rejection("schema_error", result.detail or "no valid structured answer")
        elif result.outcome != "ok":
            _missing(
                ctx,
                "agent_failed",
                f"{claim['id']}: its reviewer ended {result.outcome}: {result.detail}",
                claim,
                "check the agent settings, the API or the cassettes, then run again",
            )
            return
        else:
            checked = check(
                result.structured, claim, context.view, ids, request.model, claims=context.claims
            )
            if not isinstance(checked, Rejection):
                status = VERDICT_STATUS[checked["verdict"]]
                ctx.emit("verdict.issued", status=status, payload={"verdict": checked}, agent=agent)
                return
            rejection = checked
        feedback = f"{rejection.reason}: {rejection.detail}"
    assert rejection is not None  # noqa: S101 - the loop ran
    detail = rejection.detail[:SHORT]
    rejected = {"claim_id": claim["id"], "reason": rejection.reason, "detail": detail}
    ctx.emit("verdict.rejected", status="warn", payload=rejected, agent=agent)
    _missing(
        ctx,
        "verdict_rejected",
        f"{claim['id']}: no verdict passed the checks ({rejection.reason}: {detail})",
        claim,
        "run the review again, or with another model",
    )


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """What every reviewer of a run reads."""

    view: EvidenceView
    sources: RepoSources
    tools: tuple[ReproTool, ...]
    prompt: Prompt
    #: The PR's claims, each reviewer seeing the others.
    claims: tuple[Mapping[str, Any], ...] = ()


def review_job(
    log: Callable[[str], list[dict[str, Any]]],
    git: Git,
    *,
    base: str,
    head: str,
    setup: AgentSetup,
    others: Sequence[str],
) -> Job:
    """The ``review`` job: after every other job, each claim judged against the run's evidence."""

    def run(ctx: JobContext) -> None:
        stored = ctx.emit(
            "log.line",
            status="progress",
            payload={"level": "info", "verb": "review", "message": "reviewing the claims"},
        )
        stored.result(COMMIT_WAIT_S)  # every event before it is stored too
        events = log(ctx.run_id)
        claims = [e["payload"]["claim"] for e in events if e["kind"] == "claim.extracted"]
        if not claims:
            ctx.log("no claims to review")
            return
        view = EvidenceView.from_events(events)
        sources = RepoSources(git, base, head)
        context = ReviewContext(
            view,
            sources,
            EvidenceTools(view, sources).tools(),
            load_prompt(REVIEWER_PROMPT),
            tuple(claims),
        )

        async def every_claim() -> None:
            await asyncio.gather(*(review_claim(ctx, setup, context, c) for c in claims))

        asyncio.run(every_claim())
        ctx.log(f"{len(claims)} claim{'s' if len(claims) != 1 else ''} reviewed ({setup.label})")

    return Job(
        "review",
        "review",
        run,
        OnFailure(
            reason="agent_failed",
            detail="the claims could not be reviewed",
            resolution="check the agent settings, the API or the cassettes, then run again",
        ),
        after=tuple(others),
    )


GAP_PROMPT: Final = "gap"


def gap_job(
    log: Callable[[str], list[dict[str, Any]]],
    *,
    setup: AgentSetup,
    after: Sequence[str],
) -> Job:
    """The ``gap`` job (G06): after the review, each difference no verdict accounts for mapped
    to the supported claims that explain it, or left unexplained."""

    def run(ctx: JobContext) -> None:
        stored = ctx.emit(
            "log.line",
            status="progress",
            payload={"level": "info", "verb": "review", "message": "explaining the gap"},
        )
        stored.result(COMMIT_WAIT_S)
        events = log(ctx.run_id)
        view = EvidenceView.from_events(events)
        items = candidates(events, view)
        claims = explainers(events)
        if not items:
            ctx.log("every difference is accounted for, or flags on its own")
            return
        if not claims:
            ctx.log(f"{len(items)} unexplained: no supported claim describes a change")
            return
        sent = items[:GAP_MAX_ITEMS]
        if len(items) > len(sent):
            beyond = len(items) - len(sent)
            ctx.log(f"{beyond} differences beyond the first {len(sent)} stay unexplained")
        prompt = load_prompt(GAP_PROMPT)
        request = gap_request(claims, sent, prompt, setup.model("gap"))
        agent = setup.dispatch.agent_id()
        result = asyncio.run(
            run_agent(ctx, setup.backend, setup.dispatch, request, agent=agent, ledger=setup.ledger)
        )
        if result.outcome != "ok":
            raise AgentFailedError(
                f"the gap reviewer ended {result.outcome}: {result.detail}"[:500]
            )
        explained = check_mapping(result.structured, claims, sent, view)
        for problem in explained.dropped:
            ctx.log(f"gap: dropped {problem}", level="warning")
        for verdict in verdicts(explained, request.model):
            ctx.emit("verdict.issued", status="ok", payload={"verdict": verdict}, agent=agent)
        count = sum(len(v) for v in explained.by_claim.values())
        ctx.log(f"gap: {count} of {len(sent)} differences explained by the claims")

    return Job(
        "gap",
        "review",
        run,
        OnFailure(
            reason="agent_failed",
            detail="the differences no verdict accounts for could not be mapped to the claims",
            resolution="check the agent settings, the API or the cassettes, then run again",
        ),
        after=tuple(after),
    )
