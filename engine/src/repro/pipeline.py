"""A run's pipeline: the jobs ``repro run`` hands the orchestrator (C08).

The build stage: both sides' snapshots (``snapshot.ready``), the static analysis of the
change (``graph.node``, ``graph.edge``, ``symbol.changed``, ``blast.computed``), and the policy
(``repro.yml`` from base; head's change to it as ``policy_change`` evidence, F01). Then, unless the
run only analyses, the run and diff stages (``repro.run_stage``, D06): each side's sandbox and
environment, the selected tests on both sides, and the evidence of what differs. A JavaScript or
TypeScript change (``Change.language``, K08) has its own analysis (``repro.analysis.javascript``)
and run and diff stages (``repro.js_stage``), with the same events. What could not
be read or run becomes a ``missing.recorded`` item, never a silent gap. With agents (G04), the
read stage first: the reader agent's claims; after every other job, the review stage: each
claim judged against the run's evidence (``repro.agents.stages``, G05). Last, the card stage
(``repro.card.job``, F05) assembles the card from the run's own log.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro import js_stage
from repro.agents.reader import PrText
from repro.agents.setup import AgentSetup
from repro.agents.stages import claims_job, gap_job, qa_job, review_job
from repro.analysis import StaticAnalysis, analyse, graph_payloads, javascript
from repro.card.job import CardStore, card_job
from repro.gitops import Git, Snapshot, snapshot
from repro.gitops.snapshot import remove_snapshot
from repro.js_stage import JsOptions, JsState
from repro.language import Language
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, RunSpec, SandboxBackend
from repro.policy import FILE as POLICY_FILE
from repro.policy.stage import read_policy
from repro.run_stage import Backend, RunState, run_jobs, use_docker
from repro.sandbox import Limits
from repro.sandbox.docker import GVISOR, KATA_NAMES
from repro.store import ArtifactStore

#: A run's log lists at most this many skipped entries or problems one by one.
LIST_AT_MOST: Final = 20


@dataclass(frozen=True, slots=True)
class Change:
    """What a run reproduces: two commits of one repository."""

    repo: Path
    base: GitRef
    head: GitRef
    pr_title: str | None = None
    #: No agent stage runs (G04): the status comes from the deterministic rules alone.
    deterministic_only: bool = True
    #: A pull request read from GitHub (I01): its repository, by name and page, and its own.
    repo_name: str | None = None
    repo_url: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    #: The sandbox the run's jobs use, as ``run.started`` names it (``run_backend``).
    sandbox_backend: SandboxBackend = "process"
    #: The target's language (K08): Python's pipeline, or JavaScript's (``repro.js_stage``).
    language: Language = "python"

    @classmethod
    def resolve(cls, git: Git, repo: Path, base: str, head: str) -> "Change":
        """Resolves both refs to commits (raises ``GitError`` if one does not exist)."""
        return cls(repo, GitRef(base, git.resolve(base)), GitRef(head, git.resolve(head)))

    def spec(self) -> RunSpec:
        return RunSpec(
            repo_name=self.repo_name or self.repo.resolve().name or "repository",
            base=self.base,
            head=self.head,
            repo_url=self.repo_url,
            pr_title=self.pr_title,
            pr_number=self.pr_number,
            pr_url=self.pr_url,
            deterministic_only=self.deterministic_only,
            sandbox_backend=self.sandbox_backend,
            language=self.language,
        )


def run_backend(backend: Backend, docker_runtime: str | None, *, runs_code: bool) -> SandboxBackend:
    """The sandbox a run uses, decided once for its jobs and ``run.started``: ``gvisor`` when its
    containers run under gVisor, ``kata`` under a runtime named as Kata's is (K10; the level the
    card states is probed, not named). ``auto`` asks Docker only if the run will run the
    target's code; a run that only analyses records it as ``process``. Python and JavaScript
    alike (K11: the JavaScript container has Node)."""
    if not (use_docker(backend) if runs_code else backend == "docker"):
        return "process"
    if docker_runtime == GVISOR:
        return "gvisor"
    return "kata" if docker_runtime and docker_runtime.startswith(KATA_NAMES) else "docker"


def _snapshot_job(git: Git, side: str, sha: str, work: Path) -> Job:
    def run(ctx: JobContext) -> None:
        ctx.log(f"snapshot {side} {sha[:7]} (from the tree object, no .git)")
        result: Snapshot = snapshot(git, sha, work / "snapshots" / side)
        ctx.emit(
            "snapshot.ready",
            status="ok",
            payload={
                "side": side,
                "sha": result.commit,
                "file_count": result.files,
                "tree_sha256": result.tree_sha256,
            },
        )
        if result.skipped:
            listed = "; ".join(f"{s.path}: {s.reason}" for s in result.skipped[:LIST_AT_MOST])
            more = len(result.skipped) - LIST_AT_MOST
            ctx.log(
                f"snapshot {side}: {len(result.skipped)} entries not written ({listed}"
                + (f"; and {more} more)" if more > 0 else ")"),
                level="warning",
                status="warn",
            )

    return Job(
        f"snapshot-{side}",
        "build",
        run,
        OnFailure(
            reason="environment_failed",
            detail=f"the {side} snapshot could not be written",
            resolution="check the repository and the disk, then run again",
        ),
    )


def _missing(reason: str, detail: str, file: str | None = None) -> dict[str, Any]:
    return {
        "missing": {
            "reason": reason,
            "targets": [{"file": file}] if file else [],
            "detail": detail[:1000],
            "resolution": None,
        }
    }


def emit_analysis(ctx: JobContext, analysis: StaticAnalysis) -> None:
    """The analysis as events: the graph (nodes, then edges), each changed symbol, the blast
    radius, then what could not be read."""
    for kind, payload in graph_payloads(analysis.base, analysis.head, analysis.changes.changes):
        ctx.emit(kind, status="ok", payload=payload)
    modules = len({**analysis.base.modules, **analysis.head.modules})
    imports = len(analysis.base.imports | analysis.head.imports)
    ctx.log(f"import graph: {modules} modules · {imports} imports")
    for change in analysis.changes.changes:
        ctx.emit(
            "symbol.changed",
            status="ok",
            payload=change.payload(),
            target={"file": change.file, "symbol": change.symbol_id},
        )
    blast = analysis.blast
    ctx.emit("blast.computed", status="ok", payload=blast.payload())
    ctx.log(
        f"blast radius: {len(blast.changed)} changed · {len(blast.affected)} affected · "
        f"{len(blast.module_level_changes)} module-level"
    )
    for item in analysis.changes.unanalysed:
        detail = f"symbols of {item.path} ({item.side}) not read: {item.reason}"
        ctx.emit(
            "missing.recorded",
            status="warn",
            payload=_missing("unsupported_project", detail, item.path),
        )
    for side, graph in (("base", analysis.base), ("head", analysis.head)):
        for problem in graph.problems:
            timed_out = "took longer than" in problem.reason
            file = problem.subject if problem.subject.endswith(".py") else None
            detail = f"import graph ({side}): {problem.subject}: {problem.reason}"
            reason = "timeout" if timed_out else "unsupported_project"
            ctx.emit("missing.recorded", status="warn", payload=_missing(reason, detail, file))


def _analysis_job(git: Git, change: Change, work: Path, state: RunState | None) -> Job:
    def run(ctx: JobContext) -> None:
        if change.language == "javascript":
            ctx.log("static analysis (JavaScript): modules, functions, imports")
            analysis, changes = javascript.analyse(git, change.base.sha, change.head.sha)
        else:
            ctx.log("static analysis: modules, symbols, imports")
            analysis = analyse(git, change.base.sha, change.head.sha, work / "analysis")
            changes = []
        ctx.check()
        emit_analysis(ctx, analysis)
        if state is not None:
            state.analysis = analysis
        if isinstance(state, JsState):
            state.changes = changes

    return Job(
        "static-analysis",
        "build",
        run,
        OnFailure(
            reason="unsupported_project",
            detail="the static analysis (symbols, import graph, blast radius) failed",
        ),
    )


def _policy_job(git: Git, change: Change, state: RunState | None) -> Job:
    def run(ctx: JobContext) -> None:
        read = read_policy(git, change.base.sha, change.head.sha)
        if state is not None:
            state.policy = read
        if read.policy is None:
            ctx.log(f"policy: {POLICY_FILE} on base is not valid", level="warning", status="warn")
        elif not read.found:
            ctx.log(f"policy: no {POLICY_FILE} on base: the defaults, no invariant enabled")
        else:
            names = ", ".join(i.name for i in read.policy.invariants) or "none"
            ctx.log(f"policy ({POLICY_FILE} on base): invariants {names}")
        status = "ok" if read.policy is not None else "warn"
        ctx.emit("evidence.created", status=status, payload={"evidence": read.evidence(ctx.run_id)})
        for item in read.missing():
            ctx.emit("missing.recorded", status="warn", payload=item)
        if read.change is not None:
            record = read.change.evidence(ctx.run_id)
            ctx.emit("evidence.created", status="warn", payload={"evidence": record})
            ctx.log(read.change.summary(), level="warning", status="warn")

    return Job(
        "policy",
        "build",
        run,
        OnFailure(reason="unsupported_project", detail=f"{POLICY_FILE} could not be read"),
    )


def build_jobs(
    git: Git, change: Change, work: Path, state: RunState | None = None
) -> Sequence[Job]:
    """The build stage: both snapshots, the static analysis and the policy, independent of each
    other."""
    return [
        _snapshot_job(git, "base", change.base.sha, work),
        _snapshot_job(git, "head", change.head.sha, work),
        _analysis_job(git, change, work, state),
        _policy_job(git, change, state),
    ]


def pipeline_jobs(
    git: Git,
    change: Change,
    work: Path,
    *,
    cache: Path,
    analyse_only: bool,
    artifacts: ArtifactStore | None = None,
    cards: CardStore | None = None,
    agents: AgentSetup | None = None,
    pr: PrText | None = None,
    limits: Limits | None = None,
    docker_runtime: str | None = None,
    env_image: str | None = None,
    js: JsOptions | None = None,
) -> tuple[Sequence[Job], RunState]:
    """Every job of a run, and the state they share (close it when the run is over). The
    sandboxes are ``change.sandbox_backend``'s (``run_backend``). With ``cards``, the card stage
    ends the run (F05); with ``agents``, the agent stages run (G04). A JavaScript change's run
    and diff stages are ``repro.js_stage``'s (K08), made as ``js`` says."""
    state = JsState() if change.language == "javascript" else RunState()
    backend: Backend = "process" if change.sandbox_backend == "process" else "docker"
    jobs: list[Job] = []
    if agents is not None:
        text = pr if pr is not None else PrText(())
        jobs.append(
            claims_job(
                git,
                base=change.base.sha,
                head=change.head.sha,
                pr=text,
                setup=agents,
                state=state.agents,
            )
        )
    jobs += build_jobs(git, change, work, state)
    if not analyse_only and isinstance(state, JsState):
        base, head = change.base.sha, change.head.sha
        jobs += js_stage.run_jobs(
            git,
            base,
            head,
            work,
            state,
            backend=backend,
            artifacts=artifacts,
            limits=limits,
            env_image=env_image,
            docker_runtime=docker_runtime,
            options=js or JsOptions(tools=cache / "tools"),
        )
    elif not analyse_only:
        base, head = change.base.sha, change.head.sha
        jobs += run_jobs(
            git,
            base,
            head,
            work,
            state,
            backend=backend,
            cache=cache,
            artifacts=artifacts,
            agents=agents,
            limits=limits,
            docker_runtime=docker_runtime,
            env_image=env_image,
        )
    if agents is not None and cards is not None:
        others = [job.name for job in jobs]
        jobs.append(
            review_job(
                cards.events,
                git,
                base=change.base.sha,
                head=change.head.sha,
                setup=agents,
                others=others,
            )
        )
        jobs.append(gap_job(cards.events, setup=agents, after=["review"]))
        jobs.append(qa_job(cards.events, setup=agents, after=["gap"]))
    if cards is not None:
        jobs.append(card_job(cards, [job.name for job in jobs]))
    return jobs, state


def remove_work(work: Path) -> None:
    """Deletes a run's scratch directory (its snapshots and the analysis tree)."""
    if work.exists():
        remove_snapshot(work)
