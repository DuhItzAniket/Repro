"""Event-log reading, validation, normalisation and the repro-events CLI."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from repro_events.cli import main as cli
from repro_events.log import (
    LogLine,
    dumps_jsonl,
    normalise_log,
    read_log,
    synthetic_ulid,
    validate_log,
)
from repro_events.schemas import SchemaSet, default_schema_root

SAMPLE = default_schema_root().parent / "examples" / "logs" / "sample-run.jsonl"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ANY_ID = re.compile(r"\b(?:evt|run|ev)_[0-9A-HJKMNP-TV-Z]{26}\b")
# Hypothesis tests cannot use function-scoped fixtures, so they share one schema set.
SCHEMAS = SchemaSet(default_schema_root())


def sample_lines() -> list[LogLine]:
    lines, issues = read_log(SAMPLE)
    assert issues == []
    return lines


def errors(schema_set: SchemaSet, lines: list[LogLine]) -> list[str]:
    return [i.message for i in validate_log(schema_set, lines) if i.severity == "error"]


def with_events(events: list[dict[str, Any]]) -> list[LogLine]:
    return [LogLine(n, e) for n, e in enumerate(events, start=1)]


# -- the committed sample ----------------------------------------------------------------------
def test_sample_log_is_valid(schema_set: SchemaSet) -> None:
    lines = sample_lines()
    assert len(lines) == 45
    assert validate_log(schema_set, lines) == []


def test_normalised_sample_matches_golden(golden: Any) -> None:
    golden.check("sample-run.normalised.jsonl", dumps_jsonl(normalise_log(sample_lines())))


def test_normalised_log_is_still_valid_and_normalisation_is_idempotent(
    schema_set: SchemaSet,
) -> None:
    once = normalise_log(sample_lines())
    assert errors(schema_set, with_events(once)) == []
    assert normalise_log(with_events(once)) == once


# -- normalisation is invariant to volatile values ----------------------------------------------
ulids = st.text(alphabet=CROCKFORD, min_size=25, max_size=25).map(lambda s: "0" + s)


@given(data=st.data())
def test_normalisation_ignores_ids_timestamps_durations_and_producer(data: st.DataObject) -> None:
    events = [copy.deepcopy(line.event) for line in sample_lines()]
    text = json.dumps(events)
    originals = sorted(set(ANY_ID.findall(text)))
    fresh = data.draw(
        st.lists(ulids, min_size=len(originals), max_size=len(originals), unique=True)
    )
    for old, new in zip(originals, fresh, strict=True):
        text = text.replace(old, old.split("_")[0] + "_" + new)
    shifted = json.loads(text)
    offset_ms = data.draw(st.integers(min_value=0, max_value=10**9))
    for event in shifted:
        event["producer"] = data.draw(st.sampled_from(["repro/9.9.9", "repro/0.1.0+deadbee"]))
        event["ts"] = f"2031-01-01T00:00:{(offset_ms % 50):02d}.{event['seq']:03d}Z"
        if "duration_ms" in event["payload"]:
            event["payload"]["duration_ms"] = data.draw(st.floats(min_value=0, max_value=1e6))
    assert normalise_log(with_events(shifted)) == normalise_log(sample_lines())


@given(st.integers(min_value=0, max_value=2**64))
def test_synthetic_ulids_are_schema_shaped(n: int) -> None:
    value = synthetic_ulid(n)
    assert len(value) == 26
    assert set(value) <= set(CROCKFORD)


# -- log-level invariants ------------------------------------------------------------------------
@given(st.integers(min_value=1, max_value=43))
def test_removing_any_middle_event_is_detected_as_a_seq_gap(index: int) -> None:
    events = [line.event for line in sample_lines()]
    del events[index]
    issues = validate_log(SCHEMAS, with_events(events))
    assert any("expected" in i.message and "no gaps" in i.message for i in issues)


def test_evidence_must_be_created_before_it_is_cited(schema_set: SchemaSet) -> None:
    events = [line.event for line in sample_lines()]
    created = next(i for i, e in enumerate(events) if e["kind"] == "evidence.created")
    citing = next(i for i, e in enumerate(events) if e["kind"] == "diff.outcome")
    events[created], events[citing] = events[citing], events[created]
    for seq, event in enumerate(events, start=1):
        event["seq"] = seq
    assert any("not created earlier" in m for m in errors(schema_set, with_events(events)))


def test_structural_rules(schema_set: SchemaSet) -> None:
    events = [line.event for line in sample_lines()]
    first_not_run_started = events[1:]
    for seq, event in enumerate(first_not_run_started, start=1):
        event["seq"] = seq
    assert any(
        "first event must be run.started" in m
        for m in errors(schema_set, with_events(first_not_run_started))
    )

    events = [line.event for line in sample_lines()]
    events[3] = events[3] | {"id": events[2]["id"]}
    assert any("duplicate event id" in m for m in errors(schema_set, with_events(events)))

    events = [line.event for line in sample_lines()]
    events[5] = events[5] | {"parent": events[9]["id"]}
    assert any("is not an earlier event" in m for m in errors(schema_set, with_events(events)))

    events = [line.event for line in sample_lines()]
    events[7] = events[7] | {"run_id": "run_" + synthetic_ulid(99)}
    assert any("differs from" in m for m in errors(schema_set, with_events(events)))


def test_backwards_timestamp_is_only_a_warning(schema_set: SchemaSet) -> None:
    events = [line.event for line in sample_lines()]
    events[10] = events[10] | {"ts": "2026-10-13T00:00:00.000Z"}
    issues = validate_log(schema_set, with_events(events))
    assert [i.severity for i in issues] == ["warning"]


# -- reading -------------------------------------------------------------------------------------
def test_read_log_reports_bad_lines_and_accepts_crlf(tmp_path: Path) -> None:
    good = SAMPLE.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "log.jsonl"
    path.write_bytes(f"{good}\r\n\r\nnot json\r\n[1]\r\n".encode())
    lines, issues = read_log(path)
    assert len(lines) == 1
    assert [(i.line, i.message.split(":")[0]) for i in issues] == [
        (2, "blank line"),
        (3, "not valid JSON"),
        (4, "not a JSON object"),
    ]


# -- CLI -----------------------------------------------------------------------------------------
def test_cli_validate_and_normalise(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["validate", str(SAMPLE)]) == 0
    assert "ok (45 events, 0 errors)" in capsys.readouterr().out

    broken = tmp_path / "broken.jsonl"
    lines = SAMPLE.read_text(encoding="utf-8").splitlines(keepends=True)
    broken.write_text("".join(lines[:5] + lines[6:]), encoding="utf-8")
    assert cli(["validate", str(broken)]) == 1

    out = tmp_path / "normalised.jsonl"
    assert cli(["normalise", str(SAMPLE), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == dumps_jsonl(normalise_log(sample_lines()))
