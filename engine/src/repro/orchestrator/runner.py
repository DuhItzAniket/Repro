"""Running a run: its jobs as a DAG, with timeouts, cancellation and a guaranteed end.

The orchestrator thread schedules: a job starts once every job it needs has succeeded and every
job it comes ``after`` has ended, while fewer than ``concurrency`` jobs run; a job whose
dependency (``needs``) did not succeed is skipped. Jobs run
on daemon threads (an abandoned one cannot block the process from exiting). A job still running
at its deadline is abandoned: its context is cancelled and closed, so it can emit nothing more.

What could not be done is recorded, never passed over (ARCHITECTURE §14): a failed or timed-out
job emits a ``log.line`` with status ``fail`` and a ``missing.recorded`` item; a skipped job
records its missing item. ``stage.started`` and ``stage.finished`` frame each stage's jobs.

``run.finished`` is emitted in a ``finally``: after a failure, a cancellation, or an error in
the orchestrator itself. The run registry is updated and the WAL checkpointed after it.
"""

import contextlib
import json
import queue
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from repro.bus import EventBus
from repro.clock import now_timestamp
from repro.ids import new_run_id
from repro.logs import get_logger
from repro.orchestrator.jobs import (
    STAGES,
    Job,
    JobCancelled,
    JobContext,
    JobStatus,
    Stage,
)
from repro.readable import reason
from repro.store import RunRecord, StoredEvent

log = get_logger("orchestrator")

RunOutcome = Literal["completed", "failed", "cancelled"]
#: The sandbox a run's target code runs in, as ``run.started`` names it.
SandboxBackend = Literal["process", "docker", "gvisor", "kata", "e2b"]
#: How long a cancelled run waits for its running jobs to notice before abandoning them.
CANCEL_GRACE_S: Final = 5.0
#: How long the end of a run waits for its events to be committed.
COMMIT_WAIT_S: Final = 60.0


class PipelineError(ValueError):
    """A DAG that cannot run: duplicate or unknown jobs, or a cycle."""


@dataclass(frozen=True, slots=True)
class GitRef:
    ref: str
    sha: str


@dataclass(frozen=True, slots=True)
class RunSpec:
    """What is reproduced: the ``run.started`` payload's content."""

    repo_name: str
    base: GitRef
    head: GitRef
    repo_url: str | None = None
    pr_title: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    deterministic_only: bool = False
    sandbox_backend: SandboxBackend = "process"
    #: The target's language (K08): which pipeline reproduces it.
    language: Literal["python", "javascript"] = "python"

    def payload(self) -> dict[str, Any]:
        return {
            "repo": {"name": self.repo_name, "url": self.repo_url},
            "base": {"ref": self.base.ref, "sha": self.base.sha},
            "head": {"ref": self.head.ref, "sha": self.head.sha},
            "pr": None
            if self.pr_title is None
            else {"title": self.pr_title, "number": self.pr_number, "url": self.pr_url},
            "mode": {
                "deterministic_only": self.deterministic_only,
                "sandbox_backend": self.sandbox_backend,
            },
            "language": self.language,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    outcome: RunOutcome
    jobs: Mapping[str, JobStatus]
    counts: Mapping[str, int]


def check_pipeline(jobs: Sequence[Job]) -> None:
    """Unique names, known dependencies, valid stages and no cycles."""
    names = [job.name for job in jobs]
    duplicates = sorted(name for name, n in Counter(names).items() if n > 1)
    if duplicates:
        raise PipelineError(f"duplicate jobs: {', '.join(duplicates)}")
    known = set(names)
    for job in jobs:
        if job.stage not in STAGES:
            raise PipelineError(f"{job.name}: unknown stage {job.stage!r}")
        unknown = sorted(set(job.needs) - known)
        if unknown:
            raise PipelineError(f"{job.name} needs unknown jobs: {', '.join(unknown)}")
        unknown = sorted(set(job.after) - known)
        if unknown:
            raise PipelineError(f"{job.name} waits for unknown jobs: {', '.join(unknown)}")
        if job.timeout_s <= 0:
            raise PipelineError(f"{job.name}: the timeout must be positive")
    remaining = {job.name: {*job.needs, *job.after} for job in jobs}
    while remaining:
        ready = [name for name, needs in remaining.items() if not needs]
        if not ready:
            raise PipelineError(f"the jobs form a cycle: {', '.join(sorted(remaining))}")
        for name in ready:
            del remaining[name]
        for needs in remaining.values():
            needs.difference_update(ready)


@dataclass(slots=True)
class _Running:
    context: JobContext
    started: float


@dataclass(slots=True)
class _Stage:
    jobs: set[str]
    started: float | None = None
    statuses: list[JobStatus] = field(default_factory=list)


class RunHandle:
    """A run in progress on its own thread: wait for it, or cancel it."""

    def __init__(self, execution: "_Execution") -> None:
        self.run_id = execution.run_id
        self._execution = execution
        self._result: RunResult | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._body, name=f"repro-run-{self.run_id[-8:]}", daemon=True
        )
        self._thread.start()

    def _body(self) -> None:
        try:
            self._result = self._execution.run()
        except BaseException as exc:  # noqa: BLE001 - re-raised by wait()
            self._error = exc

    def cancel(self) -> None:
        self._execution.cancel.set()

    def wait(self, timeout: float | None = None) -> RunResult:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise TimeoutError(f"{self.run_id} is still running")
        if self._error is not None:
            raise self._error
        assert self._result is not None  # noqa: S101 - set before the thread ends
        return self._result


class Orchestrator:
    """Runs pipelines through a bus; one orchestrator can run several runs."""

    def __init__(self, bus: EventBus, *, concurrency: int = 4) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.bus = bus
        self.concurrency = concurrency

    def start(self, spec: RunSpec, jobs: Sequence[Job], *, run_id: str | None = None) -> RunHandle:
        """Registers the run and starts it in the background."""
        check_pipeline(jobs)
        run_id = run_id or new_run_id()
        self.bus.writer.create_run(
            RunRecord(
                id=run_id,
                repo=spec.repo_name,
                base=spec.base.ref,
                head=spec.head.ref,
                producer=self.bus.producer,
                created_at=now_timestamp(),
            )
        ).result(COMMIT_WAIT_S)
        execution = _Execution(
            self.bus,
            run_id=run_id,
            spec=spec,
            jobs=list(jobs),
            concurrency=self.concurrency,
            cancel=threading.Event(),
        )
        return RunHandle(execution)

    def run(self, spec: RunSpec, jobs: Sequence[Job], *, run_id: str | None = None) -> RunResult:
        return self.start(spec, jobs, run_id=run_id).wait()


class _Execution:
    """One run, from ``run.started`` to ``run.finished``."""

    def __init__(
        self,
        bus: EventBus,
        *,
        run_id: str,
        spec: RunSpec,
        jobs: list[Job],
        concurrency: int,
        cancel: threading.Event,
    ) -> None:
        self.bus = bus
        self.run_id = run_id
        self.spec = spec
        self.jobs = {job.name: job for job in jobs}
        self.order = [job.name for job in jobs]
        self.concurrency = concurrency
        self.cancel = cancel
        self.status: dict[str, JobStatus] = {}
        self.running: dict[str, _Running] = {}
        self.done: queue.SimpleQueue[tuple[str, BaseException | None]] = queue.SimpleQueue()
        self.stages: dict[Stage, _Stage] = {}
        for job in jobs:
            self.stages.setdefault(job.stage, _Stage(set())).jobs.add(job.name)
        self.futures: list[Future[list[StoredEvent]]] = []
        self.futures_lock = threading.Lock()

    # -- events ------------------------------------------------------------------------------

    def emit(self, run_id: str, kind: str, **fields: Any) -> "Future[list[StoredEvent]]":
        future = self.bus.emit(run_id, kind, **fields)
        with self.futures_lock:
            self.futures.append(future)
        return future

    def _log(self, stage: Stage, message: str, *, status: str, level: str) -> None:
        payload = {"level": level, "verb": stage, "message": message[:2000]}
        self.emit(self.run_id, "log.line", stage=stage, status=status, payload=payload)

    def _missing(self, job: Job, reason: str, detail: str) -> None:
        missing = {
            "reason": reason,
            "targets": [dict(target) for target in job.on_failure.targets],
            "detail": detail[:1000],
            "resolution": job.on_failure.resolution,
        }
        self.emit(
            self.run_id, "missing.recorded", stage=job.stage, status="warn",
            payload={"missing": missing},
        )  # fmt: skip

    # -- the run -----------------------------------------------------------------------------

    def run(self) -> RunResult:
        started = time.monotonic()
        outcome: RunOutcome = "failed"
        try:
            self.emit(self.run_id, "run.started", stage="read", status="start",
                      payload=self.spec.payload())  # fmt: skip
            self._schedule()
            if self.cancel.is_set():
                outcome = "cancelled"
            elif all(status == "ok" for status in self.status.values()):
                outcome = "completed"
        except BaseException as exc:
            log.exception("orchestrator error", extra={"fields": {"run": self.run_id}})
            try:
                self._log("read", f"internal error: {type(exc).__name__}: {exc}", status="fail",
                          level="error")  # fmt: skip
            except Exception:
                log.exception("could not record the internal error")
        finally:
            counts = self._finish(outcome, started)
        return RunResult(self.run_id, outcome, dict(self.status), counts)

    def _finish(self, outcome: RunOutcome, started: float) -> dict[str, int]:
        """Emits run.finished after every earlier event is committed, then closes the run."""
        committed = self._settle()
        counts = {
            "events": len(committed) + 1,
            "evidence": sum(event.kind == "evidence.created" for event in committed),
            "missing": sum(event.kind == "missing.recorded" for event in committed),
        }
        cards = [json.loads(event.body) for event in committed if event.kind == "card.published"]
        payload = {
            "outcome": outcome,
            "card_status": cards[-1]["payload"]["status"] if cards else None,  # F05
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "counts": counts,
        }
        status = {"completed": "ok", "failed": "fail", "cancelled": "warn"}[outcome]
        self.bus.emit(self.run_id, "run.finished", stage="card", status=status,
                      payload=payload).result(COMMIT_WAIT_S)  # fmt: skip
        writer = self.bus.writer
        writer.finish_run(self.run_id, outcome, now_timestamp()).result(COMMIT_WAIT_S)
        writer.checkpoint().result(COMMIT_WAIT_S)
        return counts

    def _settle(self) -> list[StoredEvent]:
        """Waits for every event emitted so far; the ones the store refused are logged."""
        with self.futures_lock:
            futures = list(self.futures)
        committed: list[StoredEvent] = []
        for future in futures:
            try:
                committed.extend(future.result(COMMIT_WAIT_S))
            except Exception:
                log.exception("an event was not stored", extra={"fields": {"run": self.run_id}})
        return committed

    def _schedule(self) -> None:
        pending = list(self.order)
        while pending or self.running:
            if self.cancel.is_set():
                self._cancel_all(pending)
                return
            for name in list(pending):
                job = self.jobs[name]
                if any(other not in self.status for other in (*job.needs, *job.after)):
                    continue
                failed = [need for need in job.needs if self.status[need] != "ok"]
                if failed:
                    pending.remove(name)
                    self._skip(job, failed[0])
                elif len(self.running) < self.concurrency:
                    pending.remove(name)
                    self._start(job)
            self._collect()

    def _collect(self) -> None:
        """Waits for a job to end or the nearest deadline, and settles what happened."""
        if not self.running:
            return
        now = time.monotonic()
        nearest = min(running.context.deadline for running in self.running.values())
        name: str | None = None
        error: BaseException | None = None
        with contextlib.suppress(queue.Empty):
            name, error = self.done.get(timeout=max(0.0, min(nearest - now, 0.1)))
        if name is not None and name in self.running:
            self._ended(name, error)
        now = time.monotonic()
        for late in [n for n, r in self.running.items() if r.context.deadline <= now]:
            self._timed_out(late)

    def _stage_begins(self, stage: Stage) -> None:
        state = self.stages[stage]
        if state.started is None:
            state.started = time.monotonic()
            self.emit(self.run_id, "stage.started", stage=stage, status="start",
                      payload={"index": STAGES.index(stage)})  # fmt: skip

    def _settled(self, job: Job, status: JobStatus) -> None:
        self.status[job.name] = status
        state = self.stages[job.stage]
        state.statuses.append(status)
        if len(state.statuses) == len(state.jobs) and state.started is not None:
            worst = (
                "fail"
                if any(s in ("failed", "timeout") for s in state.statuses)
                else "warn"
                if any(s != "ok" for s in state.statuses)
                else "ok"
            )
            duration = max(0, round((time.monotonic() - state.started) * 1000))
            self.emit(self.run_id, "stage.finished", stage=job.stage, status=worst,
                      payload={"duration_ms": duration})  # fmt: skip

    def _start(self, job: Job) -> None:
        self._stage_begins(job.stage)
        context = JobContext(self.run_id, job, self.emit, time.monotonic() + job.timeout_s)
        self.running[job.name] = _Running(context, time.monotonic())

        def body() -> None:
            error: BaseException | None = None
            try:
                job.run(context)
            except BaseException as exc:  # noqa: BLE001 - settled by the orchestrator
                error = exc
            finally:
                context.close()
                self.done.put((job.name, error))

        threading.Thread(target=body, name=f"repro-job-{job.name}", daemon=True).start()

    def _ended(self, name: str, error: BaseException | None) -> None:
        running = self.running.pop(name)
        job = running.context.job
        if error is None:
            self._settled(job, "ok")
        elif isinstance(error, JobCancelled) and self.cancel.is_set():
            self._settled(job, "cancelled")
        else:
            what = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
            self._log(job.stage, f"{job.name} failed: {what}", status="fail", level="error")
            # The card says what failed in a line (H01): the type and its message's first line,
            # free of the machine; the whole message stays in the log.
            detail = f"{job.on_failure.detail}: {job.name} failed ({reason(error)})"
            self._missing(job, job.on_failure.reason, detail)
            self._settled(job, "failed")

    def _timed_out(self, name: str) -> None:
        running = self.running.pop(name)
        running.context.close()  # it may still be running; it can emit nothing more
        job = running.context.job
        self._log(job.stage, f"{job.name} timed out after {job.timeout_s:g} s", status="fail",
                  level="error")  # fmt: skip
        limit = f"{job.timeout_s:g} s"
        self._missing(job, "timeout", f"{job.on_failure.detail}: {job.name} took over {limit}")
        self._settled(job, "timeout")

    def _skip(self, job: Job, because: str) -> None:
        self._stage_begins(job.stage)
        detail = f"{job.on_failure.detail}: not attempted because {because} did not succeed"
        self._missing(job, job.on_failure.reason, detail)
        self._settled(job, "skipped")

    def _cancel_all(self, pending: list[str]) -> None:
        """Stops the run: running jobs are told to stop, then abandoned; the rest never start."""
        self._log("read", "cancelled", status="warn", level="warning")
        for running in self.running.values():
            running.context.cancel()
        deadline = time.monotonic() + CANCEL_GRACE_S
        while self.running and time.monotonic() < deadline:
            try:
                name, error = self.done.get(timeout=0.05)
            except queue.Empty:
                continue
            if name in self.running:
                self._ended(name, error)
        for name in list(self.running):
            running = self.running.pop(name)
            running.context.close()
            self._settled(running.context.job, "cancelled")
        # Pending jobs never start; a stage already under way still gets its stage.finished.
        for name in pending:
            self._settled(self.jobs[name], "cancelled")
        pending.clear()
