"""The orchestrator: a DAG of jobs, timeouts, cancellation and a guaranteed run.finished (C03)."""

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import Golden

from repro.bus import EventBus
from repro.orchestrator import (
    GitRef,
    Job,
    JobCancelled,
    JobContext,
    OnFailure,
    Orchestrator,
    PipelineError,
    RunResult,
    RunSpec,
    SubprocessTimeoutError,
    check_pipeline,
)
from repro.orchestrator import runner as runner_module
from repro.store import StoreReader, StoreWriter
from repro_events.log import LogLine, dumps_jsonl, normalise_log, validate_log
from repro_events.schemas import SchemaSet
from store_support import started_writer

SPEC = RunSpec(
    repo_name="fixture/honest-fix",
    base=GitRef("main", "fe755e41c8d49ca8e2f60e44cd6eeb6e3ab93acc"),
    head=GitRef("fix/parse-date-utc", "44c5e145df93b6051f6a2fb2e795ceef189e9c0d"),
    pr_title="Parse dates as UTC",
)
GRAPH = OnFailure("unsupported_project", "the import graph", resolution="a Python project")
TESTS = OnFailure(
    "environment_failed",
    "the tests on base and head",
    targets=({"file": "tests/test_dates.py"},),
)


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[StoreWriter]:
    with started_writer(tmp_path / "repro.db") as writer:
        yield writer


@pytest.fixture
def orchestrator(writer: StoreWriter) -> Orchestrator:
    return Orchestrator(EventBus(writer), concurrency=1)


def events_of(db: Path, run_id: str) -> list[dict[str, Any]]:
    with StoreReader(db) as reader:
        return [event.envelope() for event in reader.iter_events(run_id)]


def job(
    name: str,
    stage: str,
    run: Callable[[JobContext], None] | None = None,
    *,
    needs: tuple[str, ...] = (),
    timeout_s: float = 30,
    on_failure: OnFailure = GRAPH,
    after: tuple[str, ...] = (),
) -> Job:
    def say(ctx: JobContext) -> None:
        ctx.log(f"{name} done", status="ok")

    return Job(name, stage, run or say, on_failure, needs, timeout_s, after)  # type: ignore[arg-type]


def fail(ctx: JobContext) -> None:
    raise RuntimeError("grimp failed")


def hang(ctx: JobContext) -> None:
    """Ignores cancellation for a while, as a stuck job would."""
    time.sleep(1.5)
    ctx.log("too late")  # the job was abandoned: this must not reach the log


def stub_pipeline() -> list[Job]:
    return [
        job("claims", "read"),
        job("snapshot", "build", needs=("claims",)),
        job("graph", "build", fail, needs=("snapshot",)),
        job("tests", "run", hang, needs=("snapshot",), timeout_s=0.2, on_failure=TESTS),
        job("outcome", "diff", needs=("tests",), on_failure=TESTS),
        job("invariants", "check", needs=("snapshot",)),
    ]


def test_stub_pipeline_matches_its_golden_log(
    orchestrator: Orchestrator, tmp_path: Path, golden: Golden, schema_set: SchemaSet
) -> None:
    """Roadmap C03: a golden-log test of a stub pipeline (normalised, then schema-validated)."""
    result = orchestrator.run(SPEC, stub_pipeline())
    assert result.outcome == "failed"
    assert dict(result.jobs) == {
        "claims": "ok",
        "snapshot": "ok",
        "graph": "failed",
        "tests": "timeout",
        "outcome": "skipped",
        "invariants": "ok",
    }
    events = events_of(tmp_path / "repro.db", result.run_id)
    lines = [LogLine(i + 1, event) for i, event in enumerate(events)]
    assert validate_log(schema_set, lines) == []
    golden.check("stub-pipeline.jsonl", dumps_jsonl(normalise_log(lines)))
    time.sleep(1.6)  # the abandoned job wakes up and tries to log
    assert events_of(tmp_path / "repro.db", result.run_id) == events  # nothing after the end


def test_a_clean_run_completes(orchestrator: Orchestrator, tmp_path: Path) -> None:
    jobs = [job("claims", "read"), job("snapshot", "build", needs=("claims",))]
    result = orchestrator.run(SPEC, jobs)
    assert result.outcome == "completed"
    events = events_of(tmp_path / "repro.db", result.run_id)
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "run.started"
    assert kinds[-1] == "run.finished"
    finished = events[-1]["payload"]
    assert finished["outcome"] == "completed"
    assert finished["counts"] == {"events": len(events), "evidence": 0, "missing": 0}
    assert finished["card_status"] is None
    with StoreReader(tmp_path / "repro.db") as reader:
        run = reader.run(result.run_id)
    assert run is not None
    assert run.status == "completed"


def test_stages_frame_their_jobs(orchestrator: Orchestrator, tmp_path: Path) -> None:
    jobs = [job("a", "read"), job("b", "read", needs=("a",)), job("c", "build", needs=("b",))]
    result = orchestrator.run(SPEC, jobs)
    events = events_of(tmp_path / "repro.db", result.run_id)
    trail = [
        (event["kind"], event["stage"], event["payload"].get("index"))
        for event in events
        if event["kind"].startswith("stage.")
    ]
    assert trail == [
        ("stage.started", "read", 0),
        ("stage.finished", "read", None),
        ("stage.started", "build", 1),
        ("stage.finished", "build", None),
    ]


def test_a_failure_is_recorded_and_its_dependants_are_skipped(
    orchestrator: Orchestrator, tmp_path: Path
) -> None:
    jobs = [job("graph", "build", fail), job("blast", "build", needs=("graph",))]
    result = orchestrator.run(SPEC, jobs)
    assert dict(result.jobs) == {"graph": "failed", "blast": "skipped"}
    events = events_of(tmp_path / "repro.db", result.run_id)
    failures = [e for e in events if e["kind"] == "log.line" and e["status"] == "fail"]
    assert failures[0]["payload"]["message"] == "graph failed: RuntimeError: grimp failed"
    missing = [e["payload"]["missing"] for e in events if e["kind"] == "missing.recorded"]
    assert [m["detail"] for m in missing] == [
        "the import graph: graph failed (RuntimeError: grimp failed)",
        "the import graph: not attempted because graph did not succeed",
    ]
    assert all(m["reason"] == "unsupported_project" for m in missing)
    stage_end = next(e for e in events if e["kind"] == "stage.finished")
    assert stage_end["status"] == "fail"
    assert events[-1]["payload"]["counts"]["missing"] == 2


def test_a_job_after_others_runs_once_they_end_however_they_end(
    orchestrator: Orchestrator, tmp_path: Path
) -> None:
    """F02: the invariants say themselves what they could not evaluate, so a failed or skipped
    job before them does not skip them."""
    seen: list[str] = []

    def report(ctx: JobContext) -> None:
        seen.append("report")

    jobs = [
        job("graph", "build", fail),
        job("blast", "build", needs=("graph",)),
        job("api", "diff"),
        job("report", "check", report, needs=("api",), after=("graph", "blast")),
    ]
    result = orchestrator.run(SPEC, jobs)
    assert dict(result.jobs) == {
        "graph": "failed",
        "blast": "skipped",
        "api": "ok",
        "report": "ok",
    }
    assert seen == ["report"]
    events = events_of(tmp_path / "repro.db", result.run_id)
    missing = [e["payload"]["missing"]["detail"] for e in events if e["kind"] == "missing.recorded"]
    assert len(missing) == 2  # graph's and blast's, none for report


def test_a_job_that_overruns_is_abandoned_and_recorded_as_a_timeout(
    orchestrator: Orchestrator, tmp_path: Path
) -> None:
    start = time.monotonic()
    result = orchestrator.run(SPEC, [job("tests", "run", hang, timeout_s=0.2, on_failure=TESTS)])
    assert time.monotonic() - start < 1.2  # it did not wait for the stuck job
    assert result.jobs["tests"] == "timeout"
    events = events_of(tmp_path / "repro.db", result.run_id)
    (missing,) = [e["payload"]["missing"] for e in events if e["kind"] == "missing.recorded"]
    assert missing["reason"] == "timeout"
    assert missing["targets"] == [{"file": "tests/test_dates.py"}]
    time.sleep(1.6)
    assert events_of(tmp_path / "repro.db", result.run_id) == events


def test_a_cancelled_run_ends_cleanly_with_a_final_event(
    orchestrator: Orchestrator, tmp_path: Path
) -> None:
    """Roadmap C03: cancel while a job runs; the pending job never starts."""
    started = threading.Event()
    ran: list[str] = []

    def wait_for_cancel(ctx: JobContext) -> None:
        started.set()
        ctx.wait(30)

    def never(ctx: JobContext) -> None:
        ran.append("never")

    handle = orchestrator.start(
        SPEC, [job("long", "run", wait_for_cancel), job("next", "diff", never, needs=("long",))]
    )
    assert started.wait(10)
    began = time.monotonic()
    handle.cancel()
    result = handle.wait(30)
    assert time.monotonic() - began < 5
    assert result.outcome == "cancelled"
    assert dict(result.jobs) == {"long": "cancelled", "next": "cancelled"}
    assert ran == []
    events = events_of(tmp_path / "repro.db", result.run_id)
    assert events[-1]["kind"] == "run.finished"
    assert events[-1]["payload"]["outcome"] == "cancelled"
    assert events[-1]["status"] == "warn"
    assert not [
        e for e in events if e["kind"] == "missing.recorded"
    ]  # a cancelled run is not a gap
    with StoreReader(tmp_path / "repro.db") as reader:
        run = reader.run(result.run_id)
    assert run is not None
    assert run.status == "cancelled"


def test_an_error_in_the_orchestrator_still_ends_the_run(
    orchestrator: Orchestrator, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object) -> None:
        raise RuntimeError("scheduler bug")

    monkeypatch.setattr(runner_module._Execution, "_schedule", broken)
    result = orchestrator.run(SPEC, [job("claims", "read")])
    assert result.outcome == "failed"
    events = events_of(tmp_path / "repro.db", result.run_id)
    assert events[-1]["kind"] == "run.finished"
    messages = [e["payload"]["message"] for e in events if e["kind"] == "log.line"]
    assert messages == ["internal error: RuntimeError: scheduler bug"]


def test_jobs_run_concurrently_up_to_the_limit_and_after_their_needs(
    writer: StoreWriter,
) -> None:
    lock = threading.Lock()
    active = [0]
    peak = [0]
    finished: list[str] = []

    def work(name: str) -> Callable[[JobContext], None]:
        def run(ctx: JobContext) -> None:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
                finished.append(name)

        return run

    jobs = [job(n, "run", work(n)) for n in ("a", "b", "c", "d")]
    jobs.append(job("after", "diff", work("after"), needs=("a", "b", "c", "d")))
    result = Orchestrator(EventBus(writer), concurrency=2).run(SPEC, jobs)
    assert result.outcome == "completed"
    assert peak[0] == 2
    assert finished[-1] == "after"


@pytest.mark.parametrize(
    ("jobs", "message"),
    [
        ([job("a", "read"), job("a", "build")], "duplicate jobs: a"),
        ([job("a", "read", needs=("z",))], "unknown jobs: z"),
        ([job("a", "read", needs=("b",)), job("b", "read", needs=("a",))], "cycle"),
        ([job("a", "read", after=("z",))], "waits for unknown jobs: z"),
        ([job("a", "read", after=("b",)), job("b", "read", needs=("a",))], "cycle"),
        ([job("a", "lunch")], "unknown stage"),
        ([job("a", "read", timeout_s=0)], "timeout must be positive"),
    ],
)
def test_pipelines_are_checked_before_they_run(jobs: list[Job], message: str) -> None:
    with pytest.raises(PipelineError, match=message):
        check_pipeline(jobs)


def test_a_closed_job_cannot_emit(orchestrator: Orchestrator) -> None:
    contexts: list[JobContext] = []
    orchestrator.run(SPEC, [job("a", "read", contexts.append)])
    with pytest.raises(JobCancelled):
        contexts[0].log("after the end")


def run_in_job(
    orchestrator: Orchestrator, body: Callable[[JobContext], Any]
) -> tuple[Any, RunResult]:
    box: dict[str, Any] = {}

    def run(ctx: JobContext) -> None:
        try:
            box["value"] = body(ctx)
        except Exception as exc:
            box["error"] = exc
            raise

    result = orchestrator.run(SPEC, [job("tool", "build", run, timeout_s=20)])
    return box.get("value", box.get("error")), result


def test_a_tool_runs_and_its_output_is_captured(orchestrator: Orchestrator) -> None:
    done, result = run_in_job(
        orchestrator, lambda ctx: ctx.run([sys.executable, "-c", "print('hello')"])
    )
    assert result.outcome == "completed"
    assert (done.returncode, done.stdout.strip()) == (0, "hello")


CHILD_SPAWNS_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "time.sleep(60)\n"
)


def test_a_tool_that_overruns_is_killed_with_its_children(orchestrator: Orchestrator) -> None:
    start = time.monotonic()
    error, result = run_in_job(
        orchestrator,
        lambda ctx: ctx.run([sys.executable, "-c", CHILD_SPAWNS_GRANDCHILD], timeout_s=1),
    )
    # A surviving grandchild would hold the output pipes open and keep run() waiting.
    assert time.monotonic() - start < 15
    assert isinstance(error, SubprocessTimeoutError)
    assert result.jobs["tool"] == "failed"


def test_cancelling_a_run_kills_its_tools(orchestrator: Orchestrator) -> None:
    started = threading.Event()

    def run(ctx: JobContext) -> None:
        started.set()
        ctx.run([sys.executable, "-c", CHILD_SPAWNS_GRANDCHILD])

    handle = orchestrator.start(SPEC, [job("tool", "build", run)])
    assert started.wait(10)
    time.sleep(0.3)
    began = time.monotonic()
    handle.cancel()
    result = handle.wait(30)
    assert time.monotonic() - began < 15
    assert result.outcome == "cancelled"


def test_run_started_carries_the_spec(orchestrator: Orchestrator, tmp_path: Path) -> None:
    result = orchestrator.run(SPEC, [job("claims", "read")])
    started = events_of(tmp_path / "repro.db", result.run_id)[0]
    assert started["payload"] == json.loads(json.dumps(SPEC.payload()))
    assert started["payload"]["pr"] == {"title": "Parse dates as UTC", "number": None, "url": None}
