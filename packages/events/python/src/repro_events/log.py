"""Event logs (JSONL): reading, validation and normalisation.

A run's event log is one JSON object per line, ordered by ``seq``. Beyond per-event schema
validation, a log has invariants of its own:
- one run;
- ``seq`` starts at 1 and has no gaps;
- unique ids;
- ``parent`` points backwards;
- the run starts with ``run.started`` and ends with at most one ``run.finished``;
- **evidence is created before anything cites it**. This is the machine-checkable form of
  "a verdict with no evidence is rejected".

Normalisation makes logs comparable across runs, machines and operating systems, for golden
tests. Volatile values (ids, timestamps, durations, producer version) are replaced
deterministically, and the result is still schema-valid.
"""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from repro_events.schemas import SchemaSet

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID = "[0-9A-HJKMNP-TV-Z]{26}"
ID_PATTERN = re.compile(rf"\b(evt|run|ev)_({_ULID})\b")
DEFAULT_VOLATILE_KEYS = frozenset({"duration_ms"})
NORMALISED_PRODUCER = "repro/0.0.0"
_EPOCH_MS = 946_684_800_000  # 2000-01-01T00:00:00Z


@dataclass(frozen=True)
class LogLine:
    line: int  # 1-based line number in the file
    event: Any


@dataclass(frozen=True)
class LogIssue:
    line: int  # 0 = applies to the whole log
    message: str
    severity: Literal["error", "warning"] = "error"

    def __str__(self) -> str:
        where = f"line {self.line}" if self.line else "log"
        return f"{where}: {self.severity}: {self.message}"


def read_log(path: Path) -> tuple[list[LogLine], list[LogIssue]]:
    """Parse a JSONL log. Lines that are not JSON objects become issues, not exceptions."""
    lines: list[LogLine] = []
    issues: list[LogIssue] = []
    text = path.read_text(encoding="utf-8")
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()  # trailing newline
    for number, raw in enumerate(raw_lines, start=1):
        stripped = raw.removesuffix("\r")
        if not stripped.strip():
            issues.append(LogIssue(number, "blank line"))
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            issues.append(LogIssue(number, f"not valid JSON: {exc.msg}"))
            continue
        if not isinstance(value, dict):
            issues.append(LogIssue(number, "not a JSON object"))
            continue
        lines.append(LogLine(number, value))
    return lines, issues


def _cited_evidence(event: dict[str, Any]) -> Iterator[str]:
    kind = event.get("kind", "")
    payload = event.get("payload", {})
    if kind == "verdict.issued":
        verdict = payload.get("verdict", {})
        yield from verdict.get("cited_evidence", [])
        yield from (quote.get("evidence_id") for quote in verdict.get("quotes", []))
    elif kind == "invariant.result":
        yield from payload.get("evidence_ids", [])
    elif kind.startswith("diff.") and "evidence_id" in payload:
        yield payload["evidence_id"]


@dataclass
class _LogState:
    run_id: Any
    total: int
    seen_ids: set[str] = field(default_factory=set)
    created_evidence: set[str] = field(default_factory=set)
    previous_ts: str = ""


def _structure_issues(state: _LogState, index: int, item: LogLine) -> list[LogIssue]:
    event, n = item.event, item.line
    issues = []
    if event.get("run_id") != state.run_id:
        issues.append(LogIssue(n, f"run_id {event.get('run_id')!r} differs from {state.run_id!r}"))
    if event.get("seq") != index + 1:
        issues.append(LogIssue(n, f"seq {event.get('seq')!r}; expected {index + 1} (no gaps)"))
    event_id = event.get("id")
    if event_id in state.seen_ids:
        issues.append(LogIssue(n, f"duplicate event id {event_id}"))
    parent = event.get("parent")
    if parent is not None and parent not in state.seen_ids:
        issues.append(LogIssue(n, f"parent {parent} is not an earlier event"))
    if isinstance(event_id, str):
        state.seen_ids.add(event_id)
    kind = event.get("kind")
    if index == 0 and kind != "run.started":
        issues.append(LogIssue(n, f"first event must be run.started, not {kind}"))
    if kind == "run.finished" and index != state.total - 1:
        issues.append(LogIssue(n, "run.finished must be the last event"))
    return issues


def _timestamp_issues(state: _LogState, item: LogLine) -> list[LogIssue]:
    # Timestamps are informational; seq is the order (ADR-0002). Going backwards only warns.
    ts = item.event.get("ts")
    if not isinstance(ts, str):
        return []
    issues = []
    if ts < state.previous_ts:
        message = f"timestamp goes backwards ({ts} < {state.previous_ts})"
        issues.append(LogIssue(item.line, message, "warning"))
    state.previous_ts = max(state.previous_ts, ts)
    return issues


def _evidence_issues(state: _LogState, item: LogLine) -> list[LogIssue]:
    event = item.event
    issues = [
        LogIssue(item.line, f"cites evidence {cited} not created earlier in the log")
        for cited in _cited_evidence(event)
        if cited not in state.created_evidence
    ]
    if event.get("kind") == "evidence.created":
        state.created_evidence.add(event.get("payload", {}).get("evidence", {}).get("id", ""))
    return issues


def validate_log(schemas: SchemaSet, lines: list[LogLine]) -> list[LogIssue]:
    """Schema errors for every event plus the log-level invariants."""
    if not lines:
        return [LogIssue(0, "log has no events")]
    state = _LogState(run_id=lines[0].event.get("run_id"), total=len(lines))
    issues: list[LogIssue] = []
    for index, item in enumerate(lines):
        issues += [LogIssue(item.line, message) for message in schemas.event_errors(item.event)]
        issues += _structure_issues(state, index, item)
        issues += _timestamp_issues(state, item)
        issues += _evidence_issues(state, item)
    return issues


def synthetic_ulid(n: int) -> str:
    """A deterministic, schema-valid ULID for normalised logs: base32 of ``n``, zero-padded."""
    digits = []
    for _ in range(26):
        digits.append(CROCKFORD[n & 31])
        n >>= 5
    return "".join(reversed(digits))


def _synthetic_ts(seq: int) -> str:
    ms = _EPOCH_MS + seq
    seconds, millis = divmod(ms, 1000)
    stamp = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{millis:03d}Z"


def normalise_log(
    lines: Iterable[LogLine], volatile_keys: frozenset[str] = DEFAULT_VOLATILE_KEYS
) -> list[dict[str, Any]]:
    """Replace volatile values deterministically; the result stays schema-valid.

    Event ids map to ``seq``. Evidence ids are numbered by first appearance. Run ids map to a
    single synthetic id. ``ts`` becomes 2000-01-01T00:00:00.000Z plus ``seq`` milliseconds.
    Keys in ``volatile_keys`` (anywhere in the payload) become 0, and ``producer`` is fixed.
    """
    events = [item.event for item in lines]
    mapping: dict[str, str] = {}
    for event in events:
        mapping[event["id"]] = f"evt_{synthetic_ulid(event['seq'])}"
    evidence_counter = 0

    def remap(match: re.Match[str]) -> str:
        nonlocal evidence_counter
        original = match.group(0)
        if original not in mapping:
            prefix = match.group(1)
            if prefix == "run":
                mapping[original] = f"run_{synthetic_ulid(1)}"
            elif prefix == "ev":
                evidence_counter += 1
                mapping[original] = f"ev_{synthetic_ulid(evidence_counter)}"
            else:  # an event id that is not in this log (e.g. a dangling parent)
                mapping[original] = f"evt_{synthetic_ulid(0)}"
        return mapping[original]

    def walk(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return ID_PATTERN.sub(remap, value)
        if key in volatile_keys and isinstance(value, int | float) and not isinstance(value, bool):
            return 0
        return value

    normalised = []
    for event in events:
        out = walk(event)
        out["ts"] = _synthetic_ts(event["seq"])
        out["producer"] = NORMALISED_PRODUCER
        normalised.append(out)
    return normalised


def dumps_jsonl(events: Iterable[dict[str, Any]]) -> str:
    """Canonical JSONL: sorted keys, compact separators, LF line endings, trailing newline."""
    return "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for event in events
    )
