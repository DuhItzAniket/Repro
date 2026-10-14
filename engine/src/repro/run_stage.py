"""The run and diff stages of a run's pipeline (D06): sandboxes, environments, two-sided
execution, and its evidence as events.

- ``sandbox-<side>`` (build): the side's sandbox, Docker (L3) when asked or available, else the
  process sandbox (L2); its environment (D03). ``sandbox.ready``, ``env.provisioned``. A project
  that cannot be provisioned is an ``environment_failed`` item with the reason, and the run goes
  on without running tests: the change is unverifiable, not the run broken.
- ``tests`` (run): ``repro.runner.twosided.reproduce``. ``test.selected`` per selected test,
  ``test.started`` / ``test.finished`` per test and attempt.
- ``outcomes`` (diff): ``evidence.created`` with ``diff.outcome`` per classified test and
  ``diff.tests`` per test change; what the sandbox detected; ``missing.recorded`` for each
  uncovered symbol, flaky test, unfinished run and collection error.
- ``perf`` (run, D07): the tests that pass on both sides, timed untraced in ABBA blocks;
  ``perf.sample`` per test and run. ``perf-diff`` (diff): ``perf_diff`` evidence with
  ``diff.perf`` per timed test, and a ``perf_not_assessable`` item for those too fast to time.

The jobs share a ``RunState``; ``RunState.close`` removes what they left (Docker volumes).
"""

import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from repro.analysis import StaticAnalysis
from repro.gitops import Git
from repro.orchestrator import Job, JobContext, OnFailure
from repro.provision import (
    DockerProvisioner,
    HostProvisioner,
    ProjectError,
    ProvisionError,
    environment_missing,
    inspect_project,
)
from repro.runner import selection
from repro.runner.outcomes import unstable_observation
from repro.runner.perf import Samples, TimingRun, assess, not_assessable, time_tests
from repro.runner.selection import MapCache, Selected, map_key, no_covering_test
from repro.runner.sides import Side
from repro.runner.twosided import RunRecord, TwoSided, reproduce
from repro.sandbox import DockerSandbox, Limits, ProcessSandbox, docker_available
from repro.sandbox.detect import Detection
from repro.sandbox.evidence import detection_evidence
from repro.sandbox.image import sandbox_image

Backend = Literal["auto", "docker", "process"]
#: Labels of runs that are not attempts of the selected tests themselves.
_NOT_ATTEMPTS: Final = frozenset({"head tests", "base tests on head"})
PROVISION_TIMEOUT_S: Final = 1800.0
TESTS_TIMEOUT_S: Final = 3600.0


@dataclass
class RunState:
    """What the run's jobs hand on to each other."""

    analysis: StaticAnalysis | None = None
    sides: dict[str, Side] = field(default_factory=dict)
    result: TwoSided | None = None
    platform: dict[str, str] = field(default_factory=dict)
    timings: list[Samples] | None = None
    timing_runs: list[TimingRun] = field(default_factory=list)
    #: Every container sandbox opened, provisioned or not: their volumes go with ``close``.
    containers: list[DockerSandbox] = field(default_factory=list)

    def close(self) -> None:
        while self.containers:
            self.containers.pop().close()
        self.sides.clear()


def use_docker(backend: Backend) -> bool:
    return backend == "docker" or (backend == "auto" and docker_available())


def _sandbox_job(
    git: Git, side: str, sha: str, work: Path, state: RunState, *, backend: Backend, cache: Path
) -> Job:
    def run(ctx: JobContext) -> None:
        try:
            provision(ctx)
        except (ProjectError, ProvisionError) as exc:
            ctx.log(f"{side}: no environment: {exc}", level="warning", status="warn")
            payload = environment_missing(side, str(exc))
            ctx.emit("missing.recorded", status="warn", payload=payload)

    def provision(ctx: JobContext) -> None:
        tree = work / "snapshots" / side
        project = inspect_project(tree)
        box_dir = work / "sandboxes" / side
        limits = Limits(timeout_s=900)
        provisioning = f"{side}: provisioning the environment ({project.kind})"
        if use_docker(backend):
            image = sandbox_image()
            ctx.check()
            container = DockerSandbox(box_dir, git, sha, image=image, limits=limits)
            state.containers.append(container)
            state.platform[side] = f"docker {image}"
            ctx.emit("sandbox.ready", status="ok", payload=container.ready_payload(side))
            ctx.log(provisioning)
            env = DockerProvisioner(image).provision(side, project, container)
            state.sides[side] = Side(side, container, env)
        else:
            box = ProcessSandbox(box_dir, limits)
            state.platform[side] = f"process {sys.platform}"
            ctx.emit("sandbox.ready", status="ok", payload=box.ready_payload(side))
            ctx.log(provisioning)
            env = HostProvisioner(cache / "envs").provision(side, project, box)
            state.sides[side] = Side(side, box, env)
        ctx.emit("env.provisioned", status="ok", payload=env.payload())

    return Job(
        f"sandbox-{side}",
        "build",
        run,
        OnFailure(
            reason="environment_failed",
            detail=f"the {side} environment could not be provisioned",
            resolution=(
                "Make the project installable from the package index, with wheels for its "
                "dependencies, and its own build working offline"
            ),
        ),
        needs=(f"snapshot-{side}",),
        timeout_s=PROVISION_TIMEOUT_S,
    )


class _TestEvents:
    """``test.started`` / ``test.finished`` per selected test and attempt, as runs end."""

    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx
        self.attempts: dict[tuple[str, str], int] = defaultdict(int)

    def selected(self, chosen: tuple[Selected, ...]) -> None:
        self.ctx.log(f"selected {len(chosen)} tests")
        for item in chosen:
            self.ctx.emit(
                "test.selected", status="ok", payload=item.payload(), target={"test": item.test}
            )

    def observe(self, record: RunRecord) -> None:
        results = record.run.results
        listed = record.label == "head tests"  # collected only, not run
        count = len(results.collected) if listed else len(results.tests)
        self.ctx.log(
            f"{record.side} {record.label}: {count} tests {'collected' if listed else 'reported'}"
            + ("" if results.complete else " (the run did not finish)")
        )
        if record.label in _NOT_ATTEMPTS:
            return
        # The repeat base run (A2: the docs' A-prime) has a side of its own: the cockpit draws it
        # dimmer in the BASE lane, with its own counts.
        side = "base_repeat" if record.label == "A2" else record.side
        for test in record.tests:
            found = results.tests.get(test)
            if found is None:
                continue
            key = (side, test)
            self.attempts[key] += 1
            attempt = self.attempts[key]
            target = {"test": test}
            payload = {"side": side, "attempt": attempt}
            self.ctx.emit("test.started", status="progress", payload=payload, target=target)
            finished = {
                **payload,
                "outcome": found.outcome,
                "duration_ms": max(0, int(found.duration_s * 1000)),
            }
            status = "ok" if found.outcome in ("passed", "xfailed", "xpassed") else "warn"
            self.ctx.emit("test.finished", status=status, payload=finished, target=target)


def _tests_job(git: Git, base: str, head: str, state: RunState, *, cache: Path) -> Job:
    def run(ctx: JobContext) -> None:
        analysis = state.analysis
        if analysis is None:
            raise RuntimeError("the static analysis left nothing to select from")
        if "base" not in state.sides or "head" not in state.sides:
            ctx.log("tests not run: a side has no environment", level="warning", status="warn")
            return
        sides = state.sides["base"], state.sides["head"]
        key = map_key(
            base,
            sides[0].env.project.lock_sha256,
            sides[0].env.python_version,
            state.platform.get("base", "?"),
        )
        events = _TestEvents(ctx)
        state.result = reproduce(
            sides,
            analysis.changes.changes,
            (analysis.base, analysis.head),
            selection.side_resolvers(git, base, head),
            cache=MapCache(cache / "maps"),
            cache_key=key,
            observe=events.observe,
            on_selected=events.selected,
            stop=lambda: ctx.cancelled,
        )

    return Job(
        "tests",
        "run",
        run,
        OnFailure(
            reason="environment_failed",
            detail="the tests could not be run on both sides",
        ),
        needs=("sandbox-base", "sandbox-head", "static-analysis"),
        timeout_s=TESTS_TIMEOUT_S,
    )


def _detections(result: TwoSided, side: str) -> list[Detection]:
    return [d for r in result.runs if r.side == side for d in r.run.execution.detections.items]


def _outcomes_job(state: RunState) -> Job:
    def run(ctx: JobContext) -> None:
        result = state.result
        if result is None:
            ctx.log("no outcomes: the tests did not run", level="warning", status="warn")
            return
        for diff in result.outcomes:
            record = diff.evidence(ctx.run_id)
            ctx.emit("evidence.created", status="ok", payload={"evidence": record})
            ctx.emit(
                "diff.outcome",
                status=diff.status,  # ADR-0015 §2
                payload=diff.payload(record["id"]),
                target={"test": diff.test},
            )
        for change in result.test_changes:
            record = change.evidence(ctx.run_id)
            ctx.emit("evidence.created", status="ok", payload={"evidence": record})
            target = {"file": change.file, **({"test": change.test} if change.test else {})}
            payload = change.payload(record["id"])
            ctx.emit("diff.tests", status=change.status, payload=payload, target=target)
        for side in ("base", "head"):
            fallback = {"file": "."}
            for record in detection_evidence(
                _detections(result, side), run_id=ctx.run_id, side=side, fallback_target=fallback
            ):
                ctx.emit("evidence.created", status="warn", payload={"evidence": record})
        missing = [no_covering_test(gap) for gap in result.gaps]
        missing += [unstable_observation(diff) for diff in result.outcomes if not diff.stable]
        missing += result.problems()
        for item in missing:
            ctx.emit("missing.recorded", status="warn", payload=item)
        counts: dict[str, int] = defaultdict(int)
        for diff in result.outcomes:
            counts[diff.outcome_class] += 1
        summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items())) or "no outcomes"
        ctx.log(f"outcomes: {summary}; {len(result.test_changes)} test changes")

    return Job(
        "outcomes",
        "diff",
        run,
        OnFailure(reason="environment_failed", detail="the outcomes could not be compared"),
        needs=("tests",),
    )


def _perf_job(state: RunState) -> Job:
    def run(ctx: JobContext) -> None:
        result = state.result
        if result is None or "base" not in state.sides or "head" not in state.sides:
            ctx.log("no timing: the tests did not run", level="warning", status="warn")
            return
        stable = [d.test for d in result.outcomes if d.outcome_class == "P2P"]
        if not stable:
            ctx.log("no timing: no selected test passes on both sides")
            state.timings = []
            return
        ctx.log(f"timing {len(stable)} tests, untraced, base and head interleaved (ABBA)")

        def observe(timing: TimingRun) -> None:
            for test in stable:
                found = timing.record.results.tests.get(test)
                if found is None or found.call_s is None:
                    continue
                payload = {
                    "side": timing.side,
                    "repetition": timing.repetition,
                    "duration_ms": found.call_s * 1000,
                }
                ctx.emit("perf.sample", status="progress", payload=payload, target={"test": test})

        state.timings, state.timing_runs = time_tests(
            state.sides["base"],
            state.sides["head"],
            stable,
            observe=observe,
            stop=lambda: ctx.cancelled,
        )

    return Job(
        "perf",
        "run",
        run,
        OnFailure(reason="perf_not_assessable", detail="the timing runs did not complete"),
        needs=("tests",),
        timeout_s=TESTS_TIMEOUT_S,
    )


def _perf_diff_job(state: RunState) -> Job:
    def run(ctx: JobContext) -> None:
        if state.timings is None:
            ctx.log("no performance comparison: nothing was timed")
            return
        for timing in state.timing_runs:
            if not timing.record.results.complete:
                detail = (
                    f"{timing.side}: timing run {timing.repetition} did not finish; "
                    "its samples are missing"
                )
                payload: dict[str, Any] = {
                    "missing": {
                        "reason": "perf_not_assessable",
                        "targets": [],
                        "detail": detail,
                        "resolution": None,
                    }
                }
                ctx.emit("missing.recorded", status="warn", payload=payload)
        compared, too_fast = assess(state.timings)
        for diff in compared:
            record = diff.evidence(ctx.run_id)
            ctx.emit("evidence.created", status="ok", payload={"evidence": record})
            status = "warn" if diff.verdict == "regression" else "ok"
            ctx.emit(
                "diff.perf",
                status=status,
                payload=diff.payload(record["id"]),
                target={"test": diff.test},
            )
        if too_fast:
            ctx.emit("missing.recorded", status="warn", payload=not_assessable(too_fast))
        verdicts = ", ".join(f"{d.test}: {d.verdict}" for d in compared[:10]) or "none timed"
        ctx.log(f"performance: {verdicts}; {len(too_fast)} too fast to time")

    return Job(
        "perf-diff",
        "diff",
        run,
        OnFailure(reason="perf_not_assessable", detail="the timings could not be compared"),
        needs=("perf",),
    )


def run_jobs(
    git: Git,
    base: str,
    head: str,
    work: Path,
    state: RunState,
    *,
    backend: Backend,
    cache: Path,
) -> Sequence[Job]:
    """The run and diff stages, after the build stage's snapshots and analysis."""
    return [
        _sandbox_job(git, "base", base, work, state, backend=backend, cache=cache),
        _sandbox_job(git, "head", head, work, state, backend=backend, cache=cache),
        _tests_job(git, base, head, state, cache=cache),
        _outcomes_job(state),
        _perf_job(state),
        _perf_diff_job(state),
    ]
