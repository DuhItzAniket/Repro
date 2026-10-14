"""A run's pipeline: the jobs ``repro run`` hands the orchestrator (C08).

The build stage: both sides' snapshots (``snapshot.ready``) and the static analysis of the
change (``graph.node``, ``graph.edge``, ``symbol.changed``, ``blast.computed``). Then, unless the
run only analyses, the run and diff stages (``repro.run_stage``, D06): each side's sandbox and
environment, the selected tests on both sides, and the evidence of what differs. What could not
be read or run becomes a ``missing.recorded`` item, never a silent gap.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.analysis import StaticAnalysis, analyse, graph_payloads
from repro.gitops import Git, Snapshot, snapshot
from repro.gitops.snapshot import remove_snapshot
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, RunSpec
from repro.run_stage import Backend, RunState, run_jobs

#: A run's log lists at most this many skipped entries or problems one by one.
LIST_AT_MOST: Final = 20


@dataclass(frozen=True, slots=True)
class Change:
    """What a run reproduces: two commits of one repository."""

    repo: Path
    base: GitRef
    head: GitRef

    @classmethod
    def resolve(cls, git: Git, repo: Path, base: str, head: str) -> "Change":
        """Resolves both refs to commits (raises ``GitError`` if one does not exist)."""
        return cls(repo, GitRef(base, git.resolve(base)), GitRef(head, git.resolve(head)))

    def spec(self) -> RunSpec:
        return RunSpec(
            repo_name=self.repo.resolve().name or "repository", base=self.base, head=self.head
        )


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
        ctx.log("static analysis: modules, symbols, imports")
        analysis = analyse(git, change.base.sha, change.head.sha, work / "analysis")
        ctx.check()
        emit_analysis(ctx, analysis)
        if state is not None:
            state.analysis = analysis

    return Job(
        "static-analysis",
        "build",
        run,
        OnFailure(
            reason="unsupported_project",
            detail="the static analysis (symbols, import graph, blast radius) failed",
        ),
    )


def build_jobs(
    git: Git, change: Change, work: Path, state: RunState | None = None
) -> Sequence[Job]:
    """The build stage: both snapshots and the static analysis, independent of each other."""
    return [
        _snapshot_job(git, "base", change.base.sha, work),
        _snapshot_job(git, "head", change.head.sha, work),
        _analysis_job(git, change, work, state),
    ]


def pipeline_jobs(
    git: Git, change: Change, work: Path, *, backend: Backend, cache: Path, analyse_only: bool
) -> tuple[Sequence[Job], RunState]:
    """Every job of a run, and the state they share (close it when the run is over)."""
    state = RunState()
    jobs = list(build_jobs(git, change, work, state))
    if not analyse_only:
        base, head = change.base.sha, change.head.sha
        jobs += run_jobs(git, base, head, work, state, backend=backend, cache=cache)
    return jobs, state


def remove_work(work: Path) -> None:
    """Deletes a run's scratch directory (its snapshots and the analysis tree)."""
    if work.exists():
        remove_snapshot(work)
