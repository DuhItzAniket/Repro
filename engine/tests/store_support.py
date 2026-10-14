"""Helpers for store tests: valid event envelopes (without seq) and evidence records."""

from pathlib import Path
from typing import Any

from repro.clock import now_timestamp
from repro.ids import new_event_id, new_evidence_id, new_run_id
from repro.store import RunRecord, StoreWriter

PRODUCER = "repro/0.0.0"


def run_record(run_id: str | None = None) -> RunRecord:
    return RunRecord(
        id=run_id or new_run_id(),
        repo="fixture/honest-fix",
        base="main",
        head="fix/parse-date-utc",
        producer=PRODUCER,
        created_at=now_timestamp(),
    )


def log_line(run_id: str, message: str = "reading the diff", **extra: Any) -> dict[str, Any]:
    """A ``log.line`` envelope without ``seq``."""
    return {
        "id": new_event_id(),
        "run_id": run_id,
        "ts": now_timestamp(),
        "stage": "read",
        "agent": None,
        "kind": "log.line",
        "target": None,
        "status": "progress",
        "payload": {"level": "info", "verb": "read", "message": message, **extra},
        "v": 1,
        "pv": 1,
        "producer": PRODUCER,
    }


def evidence_record(
    run_id: str, *, artifacts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """An evidence record without ``seq`` (the writer sets it)."""
    return {
        "id": new_evidence_id(),
        "run_id": run_id,
        "type": "test_outcome",
        "targets": [{"test": "tests/test_dates.py::test_tz"}],
        "summary": "tests/test_dates.py::test_tz: base fail, head pass",
        "data": {},
        "artifacts": artifacts or [],
        "stability": "stable",
        "origin": "introduced",
        "produced_by": {"component": "diff.outcome", "version": "0.0.0"},
    }


def evidence_created(run_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": new_event_id(),
        "run_id": run_id,
        "ts": now_timestamp(),
        "stage": "diff",
        "agent": None,
        "kind": "evidence.created",
        "target": {"test": "tests/test_dates.py::test_tz"},
        "status": "ok",
        "payload": {"evidence": evidence or evidence_record(run_id)},
        "v": 1,
        "pv": 1,
        "producer": PRODUCER,
    }


def started_writer(path: Path, **options: Any) -> StoreWriter:
    return StoreWriter(path, **options).start()
