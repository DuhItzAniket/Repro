"""The agent evals' metrics, from event logs (G09).

The metrics are computed here on small hand-made logs; the gate that replays the reviewed
pull requests and holds them to ``bench/data/thresholds.toml`` is
``test_the_reviewers_meet_their_thresholds``.
"""

import csv
import io
import tomllib
from pathlib import Path
from typing import Any

import pytest

from repro_bench.claims import Item, Label
from repro_bench.claims import Report as ClaimReport
from repro_bench.claims import Scored as ClaimScored
from repro_bench.claims import rows as claim_rows
from repro_bench.flips import Flips
from repro_bench.results import FIELDS, ROOT, append_rows, read_rows
from repro_bench.runs import REVIEWED
from repro_bench.verdicts import Report, effective, measure, regressions, rows, score

THRESHOLDS = tomllib.loads((ROOT / "bench" / "data" / "thresholds.toml").read_text("utf-8"))


def label(text: str, pattern: str, verdict: str | None) -> Label:
    import re  # noqa: PLC0415 - only here

    return Label(text, "fix", (re.compile(pattern, re.IGNORECASE),), verdict)


ITEM = Item(
    "pr",
    "Fix f",
    "f returns 2. Nothing else changes. g is faster.",
    ("pkg/m.py",),
    (
        label("f returns 2", "returns 2", "supported"),
        label("nothing else changes", "nothing else", "contradicted"),
        label("g is faster", "faster", None),  # not labelled with a verdict
        label("h is gone", "h is gone", "supported"),  # no claim pairs with it
    ),
)


def event(kind: str, payload: dict[str, Any], agent: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "payload": payload, "agent": agent}


def verdict(claim_id: str, value: str) -> dict[str, Any]:
    return event("verdict.issued", {"verdict": {"claim_id": claim_id, "verdict": value}}, "a02")


def log() -> list[dict[str, Any]]:
    claims = [("C1", "f returns 2 now."), ("C2", "Nothing else changes."), ("C3", "g is faster.")]
    found = [event("claim.extracted", {"claim": {"id": i, "text": t}}, "a01") for i, t in claims]
    found += [
        event("agent.spawned", {"role": "read"}, "a01"),
        event("agent.spawned", {"role": "review"}, "a02"),
        event("agent.spawned", {"role": "review"}, "a03"),
        event("agent.spawned", {"role": "review"}, "a04"),
        event("agent.spawned", {"role": "qa"}, "a05"),
        event("agent.state", {"state": "done"}, "a01"),
        event("agent.state", {"state": "done"}, "a02"),
        event("agent.state", {"state": "failed", "detail": "invalid_output: no answer"}, "a03"),
        event("agent.state", {"state": "done"}, "a04"),
        event("agent.state", {"state": "failed", "detail": "timeout: took over 600 s"}, "a05"),
        event("verdict.rejected", {"claim_id": "C2", "reason": "uncited"}, "a03"),
        event("verdict.rejected", {"claim_id": "C2", "reason": "quote_mismatch"}, "a04"),
        event("verdict.rejected", {"claim_id": "C2", "reason": "order_swap_disagreement"}, "a04"),
        verdict("C1", "supported"),
        verdict("C1", "unverifiable"),  # withheld by QA: the claim is unverifiable
        verdict("C2", "supported"),  # wrong, and the unsafe way round
        verdict("C3", "contradicted"),
        event("cost.estimate", {"usd": 0.002, "input_tokens": 100, "output_tokens": 50}, "a02"),
        event("cost.estimate", {"usd": 0.001, "input_tokens": 40, "output_tokens": 10}, "a03"),
        event("card.published", {"card": {"status": "UNVERIFIABLE"}}),
    ]
    return found


def test_a_claim_s_verdict_is_what_the_status_rules_make_of_its_verdicts() -> None:
    assert effective(["supported", "contradicted", "unverifiable"]) == "contradicted"
    assert effective(["supported", "unverifiable"]) == "unverifiable"
    assert effective(["supported", "supported"]) == "supported"
    assert effective([]) is None


def test_a_run_is_scored_against_its_labels() -> None:
    scored = score(ITEM, log(), "FLAGGED")
    assert scored.judged == [
        ("f returns 2", "supported", "unverifiable"),
        ("nothing else changes", "contradicted", "supported"),
        ("h is gone", "supported", None),
    ]
    assert scored.answers == 3  # two done, one with no valid answer; the reader and QA aside
    assert dict(scored.refused) == {"uncited": 1, "quote_mismatch": 1}
    assert (round(scored.usd, 4), scored.tokens) == (0.003, 200)
    report = Report([scored], Flips(judged=4, flipped=1))
    rates = report.rates()
    assert rates["verdict_accuracy"] == (0.0, 0, 3)
    assert rates["unsafe_verdicts"] == (1.0, 1, 3)
    assert rates["status_accuracy"] == (0.0, 0, 1)
    assert rates["citation_validity"] == (2 / 3, 2, 3)
    assert rates["rejection_rate"] == (2 / 3, 2, 3)
    assert rates["flip_rate"] == (0.25, 1, 4)
    assert rates["usd_per_pr"][0] == pytest.approx(0.003)
    assert rates["tokens_per_pr"] == (200.0, 200, 1)


def test_results_are_one_row_per_metric(tmp_path: Path) -> None:
    report = Report([score(ITEM, log(), "UNVERIFIABLE")], Flips(judged=4, flipped=1))
    found = rows(report, model="m", source="cassettes", date="2026-10-16")
    assert [r["metric"] for r in found] == [
        "verdict_accuracy",
        "unsafe_verdicts",
        "status_accuracy",
        "citation_validity",
        "rejection_rate",
        "flip_rate",
        "usd_per_pr",
        "tokens_per_pr",
    ]
    assert found[2] | {} == {
        "date": "2026-10-16",
        "eval": "verdicts",
        "metric": "status_accuracy",
        "value": "1.000",
        "count": "1",
        "total": "1",
        "model": "m",
        "prompts": "reader/1;reviewer/1;gap/1;probe/1;qa/1",
        "repro_version": found[2]["repro_version"],
        "source": "cassettes",
    }
    claims = claim_rows(
        ClaimReport((ClaimScored("pr", ("a", "b"), 1, 2),)), model="m", source="live", date="d"
    )
    assert [(r["metric"], r["value"], r["count"], r["total"]) for r in claims] == [
        ("precision", "0.500", "1", "2"),
        ("recall", "0.500", "1", "2"),
        ("failed", "0.000", "0", "1"),
    ]
    path = tmp_path / "evals.csv"
    append_rows(found, path)
    append_rows(claims, path)
    assert len(read_rows(path)) == len(found) + len(claims)
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(FIELDS)


def test_the_results_file_is_well_formed() -> None:
    text = (ROOT / "bench" / "results" / "agent-evals.csv").read_text(encoding="utf-8")
    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == list(FIELDS)
    assert all(len(line) == len(FIELDS) for line in lines)


@pytest.mark.agent_eval
def test_the_reviewers_meet_their_thresholds(tmp_path: Path) -> None:
    """G09's gate: the reviewed pull requests replayed from their cassettes, each twice (as
    configured, and with every verdict judged in both orders), held to the thresholds."""
    from repro_bench.claims import load  # noqa: PLC0415

    items = [item for item in load() if item.name in REVIEWED]
    report, problems = measure(items, tmp_path)
    assert problems == []
    assert regressions(report, THRESHOLDS["verdicts"]) == [], report.scored


def test_a_regression_beyond_tolerance_is_caught() -> None:
    """The gate's checks on a report worse than the thresholds allow, one metric at a time."""
    wanted = THRESHOLDS["verdicts"]
    good = score(ITEM, log(), "UNVERIFIABLE")
    good.judged = [("a", "supported", "supported")] * 9 + [("b", "supported", None)]
    good.refused.clear()
    clean = Report([good], Flips(judged=10, flipped=0))
    assert regressions(clean, wanted) == []
    worse = Report([good], Flips(judged=10, flipped=2))
    assert regressions(worse, wanted) == [f"flip_rate 0.200 is above {wanted['max_flip_rate']}"]
    unsafe = score(ITEM, log(), "UNVERIFIABLE")
    unsafe.judged = [("a", "contradicted", "supported"), *good.judged]
    unsafe.refused.clear()
    found = regressions(Report([unsafe], Flips()), wanted)
    assert found == [f"1 unsafe verdicts, more than {wanted['max_unsafe']}"]
    wrong_card = score(ITEM, log(), "VERIFIED")
    wrong_card.judged, wrong_card.refused = good.judged, good.refused
    assert regressions(Report([wrong_card], Flips()), wanted) == [
        f"status_accuracy 0.000 is below {wanted['status_accuracy']}"
    ]
    miscited = score(ITEM, log(), "UNVERIFIABLE")
    miscited.judged = good.judged
    assert regressions(Report([miscited], Flips()), wanted) == [
        f"citation_validity 0.667 is below {wanted['citation_validity']}"
    ]
