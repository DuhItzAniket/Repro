"""The pipeline's agent jobs (G04 on): each runs its agents through ``run_agent`` and emits
what they found as events, and a call that ends without a usable answer fails the job, which
the card then lists as ``agent_failed`` (ground rule 3: never unverified silently).

- ``claims`` (stage ``read``, G04): the reader agent on the PR's text and the change's files,
  then one ``claim.extracted`` per claim. It needs nothing else from the run, so it runs while
  the build and run stages do.
- ``review`` (G05): after every other job, each claim's reviewer, its verdict checked.
- ``gap`` (G06): after the review, the differences no verdict accounts for mapped to the
  supported claims that explain them.
- ``qa`` (G08): after the gap reviewer, the verdicts read together; a supported verdict that
  cannot hold with another is withheld.

The review applies G08's bias controls (``repro.agents.bias``): a contradicted verdict must
survive the evidence in the opposite order, a panel's verdict needs two of three, and the card
says when the reviewers share the model family the change names as its author.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from repro.agents.backend import AgentResult, ReproTool
from repro.agents.bias import (
    agreeing,
    author_families,
    degraded,
    described,
    judge_is_author,
    majority,
)
from repro.agents.events import run_agent
from repro.agents.evidence import EvidenceView, Item
from repro.agents.gap import MAX_ITEMS as GAP_MAX_ITEMS
from repro.agents.gap import candidates, check_mapping, explainers, gap_request, verdicts
from repro.agents.prompts import Prompt, load_prompt
from repro.agents.qa import check_answer, judged, qa_request, withheld, worth_checking
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


def _judge_policy(  # noqa: PLR0917 - what the check reads
    ctx: JobContext, setup: AgentSetup, texts: Sequence[str], git: Git, base: str, head: str
) -> None:
    """G08's judge ≠ author check: when the change names its author's model (a co-author
    trailer, a "generated with" line) and every reviewer is of that model's family, the card
    says so; LLM judges favour their own family's output (research/04 §2.3)."""
    authors = author_families([*texts, *commit_messages(git, base, head)])
    judges = list(setup.panel) or [m for m in [setup.models.get("review")] if m]
    shared = judge_is_author(judges, authors)
    if shared is None:
        return
    item = {
        "reason": "judge_is_author",
        "targets": [],
        "detail": (
            f"the change names a model by {shared} among its authors, and its reviewers "
            f"({', '.join(dict.fromkeys(judges))}) are models by {shared} too"
        ),
        "resolution": "review with a model of another family (agent_model or agent_panel)",
    }
    ctx.emit("missing.recorded", status="warn", payload={"missing": item})


def claims_job(
    git: Git, *, base: str, head: str, pr: PrText, setup: AgentSetup, state: AgentState
) -> Job:
    def run(ctx: JobContext) -> None:
        files = changed_files(git, base, head)
        state.files = files
        _judge_policy(ctx, setup, [text for _, text in pr.parts], git, base, head)
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


@dataclass(frozen=True, slots=True)
class Judgement:
    """One reviewer's outcome: a checked verdict, the last rejection, or no answer at all."""

    model: str
    agent: str
    verdict: dict[str, Any] | None = None
    rejection: Rejection | None = None
    #: How the call ended when it gave no answer (its ``agent_failed`` item is recorded).
    failed: str = ""

    @property
    def answer(self) -> str:
        """What it answered, in a few words."""
        if self.verdict is not None:
            return str(self.verdict["verdict"])
        if self.rejection is not None:
            return f"an answer refused by the checks ({self.rejection.reason})"
        return f"no answer ({self.failed})"


async def _judge(
    ctx: JobContext,
    setup: AgentSetup,
    context: "ReviewContext",
    claim: Mapping[str, Any],
    items: Sequence[Item],
    *,
    model: str,
    reverse: bool = False,
) -> Judgement:
    """One reviewer on the claim: its verdict, checked, after one more try on a rejection."""
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
            model=model,
            claims=context.claims,
            feedback=feedback,
            reverse=reverse,
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
            return Judgement(model, agent, failed=f"{result.outcome}: {result.detail}")
        else:
            checked = check(
                result.structured, claim, context.view, ids, request.model, claims=context.claims
            )
            if not isinstance(checked, Rejection):
                return Judgement(model, agent, verdict=checked)
            rejection = checked
        feedback = f"{rejection.reason}: {rejection.detail}"
    return Judgement(model, agent, rejection=rejection)


def _issue(ctx: JobContext, verdict: Mapping[str, Any], agent: str) -> None:
    status = VERDICT_STATUS[verdict["verdict"]]
    ctx.emit("verdict.issued", status=status, payload={"verdict": dict(verdict)}, agent=agent)


def _refused(ctx: JobContext, claim: Mapping[str, Any], judgement: Judgement) -> None:
    """No verdict for the claim passed the checks: why, and a missing item."""
    rejection = judgement.rejection
    assert rejection is not None  # noqa: S101 - only for a judgement that has one
    detail = rejection.detail[:SHORT]
    rejected = {"claim_id": claim["id"], "reason": rejection.reason, "detail": detail}
    ctx.emit("verdict.rejected", status="warn", payload=rejected, agent=judgement.agent)
    _missing(
        ctx,
        "verdict_rejected",
        f"{claim['id']}: no verdict passed the checks ({rejection.reason}: {detail})",
        claim,
        "run the review again, or with another model",
    )


def _swapped(
    ctx: JobContext, claim: Mapping[str, Any], first: Judgement, second: Judgement
) -> dict[str, Any]:
    """The first verdict if the reversed order gives it too; otherwise ``unverifiable``."""
    assert first.verdict is not None  # noqa: S101 - only a verdict is judged again
    said = first.verdict["verdict"]
    if second.verdict is not None and second.verdict["verdict"] == said:
        return agreeing(first.verdict, 2, 2)
    detail = f"{said} with the evidence in one order, {second.answer} in the other"
    rejected = {"claim_id": claim["id"], "reason": "order_swap_disagreement", "detail": detail}
    ctx.emit("verdict.rejected", status="warn", payload=rejected, agent=second.agent)
    ctx.log(f"{claim['id']}: {detail}; it is unverifiable", level="warning")
    agree = int(said == "unverifiable") + int(second.answer == "unverifiable")
    why = f"with the evidence in the opposite order the reviewer answered {second.answer}"
    return degraded(first.verdict, why, 2, agree)


async def _panel(
    ctx: JobContext,
    setup: AgentSetup,
    context: "ReviewContext",
    claim: Mapping[str, Any],
    items: Sequence[Item],
) -> None:
    """Three reviewers, the second with the order reversed; two must give the verdict."""
    judgements = await asyncio.gather(
        *(
            _judge(ctx, setup, context, claim, items, model=model, reverse=number == 1)
            for number, model in enumerate(setup.panel)
        )
    )
    given = [(j, j.verdict) for j in judgements if j.verdict is not None]
    if not given:
        refused = [j for j in judgements if j.rejection is not None]
        if refused:
            _refused(ctx, claim, refused[0])
        return  # otherwise every call failed, each an agent_failed item
    verdicts = [verdict for _, verdict in given]
    found = majority(verdicts, len(judgements))
    if found is not None:
        agent = next(j.agent for j, v in given if v["verdict"] == found["verdict"])
        _issue(ctx, found, agent)
        return
    answers = described([(j.model, j.answer) for j in judgements])
    ctx.log(f"{claim['id']}: the panel did not agree ({answers}); unverifiable", level="warning")
    agree = sum(v["verdict"] == "unverifiable" for v in verdicts)
    why = f"the panel did not agree ({answers})"
    _issue(ctx, degraded(verdicts[0], why, len(judgements), agree), given[0][0].agent)


async def review_claim(
    ctx: JobContext, setup: AgentSetup, context: "ReviewContext", claim: Mapping[str, Any]
) -> None:
    """One claim: a reviewer's verdict, checked and, if it is to be, judged again in the
    opposite order (G08); a panel's verdict instead when there is one; or why there is none."""
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
    if setup.panel:
        await _panel(ctx, setup, context, claim, items)
        return
    model = setup.model("review")
    first = await _judge(ctx, setup, context, claim, items, model=model)
    if first.verdict is None:
        if first.rejection is not None:
            _refused(ctx, claim, first)
        return
    verdict = first.verdict
    said = verdict["verdict"]
    if setup.swap == "all" or (setup.swap == "contradicted" and said == "contradicted"):
        second = await _judge(ctx, setup, context, claim, items, model=model, reverse=True)
        verdict = _swapped(ctx, claim, first, second)
    _issue(ctx, verdict, first.agent)


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


QA_PROMPT: Final = "qa"


def qa_job(
    log: Callable[[str], list[dict[str, Any]]],
    *,
    setup: AgentSetup,
    after: Sequence[str],
) -> Job:
    """The ``qa`` job (G08): after the gap reviewer, the verdicts read together; a supported
    verdict that cannot hold with another is withheld (``unverifiable``)."""

    def run(ctx: JobContext) -> None:
        stored = ctx.emit(
            "log.line",
            status="progress",
            payload={"level": "info", "verb": "review", "message": "checking the verdicts"},
        )
        stored.result(COMMIT_WAIT_S)
        events = log(ctx.run_id)
        found = judged(events)
        if not worth_checking(found):
            ctx.log("QA: nothing to cross-check (fewer than two judged claims, or none supported)")
            return
        request = qa_request(
            found, EvidenceView.from_events(events), load_prompt(QA_PROMPT), setup.model("qa")
        )
        agent = setup.dispatch.agent_id()
        result = asyncio.run(
            run_agent(ctx, setup.backend, setup.dispatch, request, agent=agent, ledger=setup.ledger)
        )
        if result.outcome != "ok":
            raise AgentFailedError(f"the QA agent ended {result.outcome}: {result.detail}"[:500])
        checked = check_answer(result.structured, found)
        for problem in checked.dropped:
            ctx.log(f"QA: dropped {problem}", level="warning")
        for verdict in withheld(checked, found, request.model):
            ctx.emit("verdict.issued", status="warn", payload={"verdict": verdict}, agent=agent)
            ctx.log(f"QA: {verdict['claim_id']} withheld: {verdict['rationale']}"[:500])
        ctx.log(f"QA: {len(checked.kept)} inconsistencies among {len(found)} judged claims")

    return Job(
        "qa",
        "review",
        run,
        OnFailure(
            reason="agent_failed",
            detail="the verdicts could not be checked against each other",
            resolution="check the agent settings, the API or the cassettes, then run again",
        ),
        after=tuple(after),
    )
