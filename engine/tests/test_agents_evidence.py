"""A run's evidence as agents see it: ordered, related to targets, rendered (G03)."""

import json
from pathlib import Path
from typing import Any

import pytest

from repro.agents.evidence import EvidenceView
from repro.ids import new_evidence_id


def evidence(kind: str, targets: list[dict[str, str]], summary: str, **data: Any) -> dict[str, Any]:
    record = {
        "id": new_evidence_id(),
        "type": kind,
        "targets": targets,
        "summary": summary,
        "data": data,
        "stability": "stable",
        "origin": "introduced",
    }
    return {"kind": "evidence.created", "payload": {"evidence": record}}


def changed(symbol: str, file: str) -> dict[str, Any]:
    return {"kind": "symbol.changed", "payload": {"symbol_id": symbol, "file": file}}


PARSE = "pkg.dates:parse_date#0"
TEST = "tests/test_dates.py::test_parse"


def run_events() -> list[dict[str, Any]]:
    return [
        changed(PARSE, "pkg/dates.py"),
        evidence(
            "behaviour_diff",
            [{"symbol": PARSE, "test": TEST}],
            "parse_date('x') gives another result",
            change="result_changed",
            calls=1,
            test_modified=False,
            first={"args": "8ed9e2b01f314ab36eea5315029b9dce"},  # a digest: not shown
            reproducer={"call": "parse_date('x')", "base": "1", "head": "2", "reproduced": True},
        ),
        evidence(
            "test_outcome",
            [{"test": TEST}],
            f"F2P: {TEST} (base failed, head passed)",
            **{"class": "F2P", "base_outcome": "failed", "head_outcome": "passed"},
            base_message="E   assert 1 == 2\n\ntests\\test_dates.py:13: AssertionError",
            base_reruns=["failed", "failed"],
        ),
        evidence("environment", [{"file": "."}], "python 3.13", hash_seed=1),
        evidence("policy", [{"file": "repro.yml"}], "no repro.yml", found=False),
        evidence(
            "perf_diff",
            [{"test": TEST}],
            "regression: 1.83x slower (95% CI 1.61-2.07)",
            verdict="regression",
            ratio=1.8347,
            ci_low=1.61,
            p_value=0.0001,
        ),
        evidence(
            "file_attempt",
            [{"test": TEST}],
            f"head: wrote outside its directories: {Path.home()}/notes.txt",
            side="head",
            event="open",
            detail=f"{Path.home()}/notes.txt",
            count=2,
            pids=[4242],
        ),
        evidence("api_diff", [{"file": "pkg/other.py", "symbol": "pkg.other:f#0"}], "f removed"),
    ]


def test_the_engines_bookkeeping_is_not_shown() -> None:
    view = EvidenceView.from_events(run_events())
    assert {item.type for item in view.items} == {
        "test_outcome",
        "behaviour_diff",
        "perf_diff",
        "file_attempt",
        "api_diff",
    }


def test_items_are_ordered_by_content_not_by_when_they_were_made() -> None:
    events = run_events()
    forward = EvidenceView.from_events(events)
    backward = EvidenceView.from_events(list(reversed(events)))
    assert [i.type for i in forward.items] == [i.type for i in backward.items]
    assert [i.type for i in forward.items] == [
        "test_outcome",
        "behaviour_diff",
        "api_diff",
        "perf_diff",
        "file_attempt",
    ]


def test_rendering_shows_the_finding_and_nothing_that_varies_by_run() -> None:
    view = EvidenceView.from_events(run_events())
    by_type = {item.type: item.render() for item in view.items}

    behaviour = by_type["behaviour_diff"]
    assert "reproducer.call: parse_date('x')" in behaviour
    assert "reproducer.head: 2" in behaviour
    assert "8ed9e2b01f314ab36eea5315029b9dce" not in behaviour

    outcome = by_type["test_outcome"]
    assert "tests/test_dates.py:13: AssertionError" in outcome  # pytest's location, portable
    assert "base_reruns" not in outcome

    perf = by_type["perf_diff"]
    assert "summary: regression: tests/test_dates.py::test_parse" in perf
    assert "ratio: 1.8" in perf
    assert "1.83" not in perf
    assert "p_value" not in perf

    attempt = by_type["file_attempt"]
    assert "~/notes.txt" in attempt
    assert str(Path.home()) not in attempt
    assert "4242" not in attempt  # process IDs


def test_the_engines_fields_are_outside_the_block_and_the_targets_inside() -> None:
    item = EvidenceView.from_events(run_events()).items[0]
    header, body = item.render().split("<untrusted_content", 1)
    assert header.splitlines() == [
        f"evidence {item.id}",
        "type: test_outcome",
        "stability: stable",
        "origin: introduced",
        f"targets: test {TEST}",
    ]
    assert body.startswith(f' kind="evidence" id="{item.id}">\nsummary: F2P:')
    assert body.endswith("</untrusted_content>")


@pytest.mark.parametrize(
    ("target", "types"),
    [
        ({"file": "pkg/dates.py"}, {"behaviour_diff"}),  # its symbol changed in that file
        ({"symbol": PARSE}, {"behaviour_diff"}),
        ({"test": TEST}, {"test_outcome", "behaviour_diff", "perf_diff", "file_attempt"}),
        (
            {"file": "tests/test_dates.py"},
            {"test_outcome", "behaviour_diff", "perf_diff", "file_attempt"},
        ),
        ({"file": "pkg/other.py"}, {"api_diff"}),
        ({"file": "nowhere.py"}, set()),
    ],
)
def test_evidence_is_related_to_its_files_symbols_and_tests(
    target: dict[str, str], types: set[str]
) -> None:
    view = EvidenceView.from_events(run_events())
    assert {item.type for item in view.relevant([target])} == types


def test_a_listing_line_is_short_and_one_line() -> None:
    long = "x" * 1000 + "\nsecond line"
    events = [evidence("test_change", [{"file": "t.py"}], long, change="removed", detail="d")]
    line = EvidenceView.from_events(events).items[0].line()
    assert "\n" not in line.replace("\\n", "")
    assert len(line) < 300
    assert json.dumps(line)  # a plain string


def test_a_test_is_evidence_about_the_code_it_was_selected_for() -> None:
    """A new test in tests/test_prices.py that exercises shop.prices.discount is evidence about
    shop/prices.py (G06), as test.selected records."""
    clamped = "tests/test_prices.py::test_discount_is_clamped"
    events = [
        changed("shop.prices:discount#0", "shop/prices.py"),
        {
            "kind": "test.selected",
            "target": {"test": clamped},
            "payload": {"reasons": ["new_test"], "symbols": ["shop.prices:discount#0"]},
        },
        evidence("test_outcome", [{"test": clamped}], f"new: {clamped} (base absent, head passed)"),
        evidence("test_outcome", [{"test": "tests/test_cart.py::test_total"}], "P2P: test_total"),
    ]
    view = EvidenceView.from_events(events)
    about = view.relevant([{"file": "shop/prices.py"}])
    assert [item.summary for item in about] == [f"new: {clamped} (base absent, head passed)"]
