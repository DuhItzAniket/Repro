"""The tracer benchmark harness keeps working (E01). One quick round: ratios on a busy test
machine mean nothing, so only the harness's own behaviour is checked here."""

import json
from pathlib import Path

import pytest

from bench_tracer import LIMIT, main, targets


def test_the_targets_are_the_workloads() -> None:
    assert sorted(t[1] for t in targets()) == ["_small.<locals>.small", "fib", "normalise_record"]


def test_one_round(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "bench.jsonl"
    status = main(["--rounds", "1", "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [row["test"] for row in rows] == [
        "test_work.py::test_fib",
        "test_work.py::test_records",
        "test_work.py::test_small_functions",
    ]  # the warm-up test is not measured
    for row in rows:
        assert row["runs"] == 2
        assert row["plain_ms"] > 0
        assert row["traced_ms"] > 0
        assert row["budget"] == 200
        assert row["ci_low"] <= row["ratio"] <= row["ci_high"]
    assert status == (1 if any(row["ci_low"] > LIMIT for row in rows) else 0)
    assert capsys.readouterr().out.count("\n") == len(rows)
