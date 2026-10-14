"""Outcome classification and the test-file diff (D06), on their own."""

import ast
from typing import Any

import pytest

from repro.analysis.changes import SymbolChange
from repro.ids import new_run_id
from repro.runner import outcomes, selection, testdiff
from repro_events import models

RUN = new_run_id()


def diff(**runs: Any) -> outcomes.OutcomeDiff:
    options = {"base": "passed", "base_again": "passed", "head": "passed", "modified": False}
    return outcomes.classify("t.py::t", **{**options, **runs})


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ({"base": None, "base_again": None}, "new"),
        ({"head": None}, "removed"),
        ({"base_again": "failed"}, "flaky"),  # A and A2 disagree
        ({"modified": True, "head": "failed"}, "modified"),
        ({}, "P2P"),
        ({"base": "xfailed", "base_again": "xfailed", "head": "xpassed"}, "P2P"),
        ({"base": "failed", "base_again": "error", "head": "error"}, "F2F"),
        ({"base": "skipped", "base_again": "skipped", "head": "skipped"}, "F2F"),
    ],
)
def test_classes_without_a_flip(runs: dict[str, Any], expected: str) -> None:
    assert diff(**runs).outcome_class == expected


def test_a_flip_needs_every_rerun_to_repeat_it() -> None:
    fixed = {"base": "failed", "base_again": "failed", "head": "passed"}
    assert outcomes.is_flip("failed", "failed", "passed", modified=False)
    assert diff(**fixed).outcome_class == "flaky"  # not yet run again
    confirmed = diff(**fixed, base_reruns=("failed",) * 3, head_reruns=("passed",) * 3)
    assert confirmed.outcome_class == "F2P"
    assert confirmed.stable
    wobbly = diff(**fixed, base_reruns=("failed",) * 3, head_reruns=("passed", "failed", "passed"))
    assert wobbly.outcome_class == "flaky"
    assert not wobbly.stable


def test_a_skip_on_head_does_not_pass() -> None:
    skipped = {"base": "passed", "base_again": "passed", "head": "skipped"}
    found = diff(**skipped, base_reruns=("passed",) * 3, head_reruns=("skipped",) * 3)
    assert found.outcome_class == "P2F"


def test_deflakers_mark_stays_on_the_evidence() -> None:
    found = diff(
        base="passed",
        head="failed",
        base_reruns=("passed",) * 3,
        head_reruns=("failed",) * 3,
        ran_changed_code=False,
    )
    assert (found.outcome_class, found.likely_flaky) == ("P2F", True)
    assert "ran none of the changed code" in found.summary()
    assert found.evidence(RUN)["data"]["likely_flaky"] is True


@pytest.mark.parametrize(
    ("kind", "origin"),
    [("P2P", "n/a"), ("F2F", "pre-existing"), ("new", "introduced"), ("flaky", "n/a")],
)
def test_evidence_and_payload_follow_the_schema(kind: str, origin: str) -> None:
    runs: dict[str, dict[str, Any]] = {
        "P2P": {},
        "F2F": {"base": "failed", "base_again": "failed", "head": "failed"},
        "new": {"base": None, "base_again": None},
        "flaky": {"base_again": "failed"},
    }
    found = diff(**runs[kind])
    record = found.evidence(RUN)
    assert (record["origin"], record["stability"]) == (
        origin,
        "unstable" if kind == "flaky" else "stable",
    )
    models.Evidence.model_validate({**record, "seq": 1})
    models.DiffOutcomePayload.model_validate(found.payload(record["id"]))
    if kind == "flaky":
        models.MissingRecordedPayload.model_validate(outcomes.unstable_observation(found))


def shape(source: str) -> Any:
    return testdiff.shape(ast.parse(source).body[0])


BASE_TEST = """
def test_it():
    assert f(1) == 2
    assert f(2) is None
    with pytest.raises(ValueError, match="bad"):
        f(-1)
"""


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (BASE_TEST.replace("def test_it", "@pytest.mark.skip\ndef test_it"), ["skip_added"]),
        (
            BASE_TEST.replace("def test_it", "@pytest.mark.skipif(True, reason='x')\ndef test_it"),
            ["skip_added"],
        ),
        (
            BASE_TEST.replace(
                "    assert f(1) == 2\n", "    pytest.skip('later')\n    assert f(1) == 2\n"
            ),
            ["skip_added"],
        ),
        (BASE_TEST.replace("def test_it", "@pytest.mark.xfail\ndef test_it"), ["xfail_added"]),
        (BASE_TEST.replace("    assert f(2) is None\n", ""), ["assertion_removed"]),
        (BASE_TEST.replace("assert f(1) == 2", "assert f(1)"), ["assertion_weakened"]),
        (BASE_TEST.replace("assert f(1) == 2", "assert f(1) > 0"), ["assertion_weakened"]),
        (BASE_TEST.replace("ValueError", "Exception"), ["raises_widened"]),
        (BASE_TEST.replace(', match="bad"', ""), ["raises_widened"]),
        (BASE_TEST.replace("f(-1)", "f(-2)"), []),  # changed, not weakened: test_modified
        (BASE_TEST.replace("assert f(1) == 2", "assert f(1) == 2\n    assert g() == 1"), []),
    ],
)
def test_weaker_tests_are_named(head: str, expected: list[str]) -> None:
    assert [kind for kind, _ in testdiff.compare(shape(BASE_TEST), shape(head))] == expected


def test_assertions_of_nested_functions_are_not_the_tests() -> None:
    nested = "def test_it():\n    def helper():\n        assert x == 1\n    helper()\n"
    assert shape(nested).assertions == ()
    unittest = (
        "def test_it(self):\n    self.assertEqual(a, 1)\n    self.assertTrue(b)\n"
        "    self.assertIn(c, d)\n"
    )
    assert shape(unittest).assertions == (2, 0, 1)


def test_the_test_file_diff_of_a_change() -> None:
    sources = {
        "tests/test_m.py": (
            b"import pytest\n\n\ndef test_a():\n    assert f() == 1\n    assert g() == 2\n\n\n"
            b"def test_b():\n    assert f() == 1\n"
        ),
    }
    head_sources = {
        "tests/test_m.py": (
            b"import pytest\n\n\ndef test_a():\n    assert f() == 1\n\n\n"
            b"@pytest.mark.skip\ndef test_b():\n    assert f() == 1\n"
        ),
    }

    def resolver(files: dict[str, bytes]) -> selection.Resolver:
        return selection.Resolver(
            {"tests/test_m.py": "test_m"},
            lambda paths: {p: files[p] for p in paths if p in files},
        )

    base_map = selection.TestMap(
        {
            "tests/test_m.py::test_a": "test_m:test_a#0",
            "tests/test_m.py::test_b": "test_m:test_b#0",
            "tests/test_m.py::test_gone": "test_m:test_gone#0",
        },
        {},
    )
    head_map = selection.TestMap(
        {
            "tests/test_m.py::test_a": "test_m:test_a#0",
            "tests/test_m.py::test_b": "test_m:test_b#0",
        },
        {},
    )
    changes = [
        SymbolChange("test_m:test_a#0", "modified", "function", "tests/test_m.py", None, None),
        SymbolChange("test_m:test_b#0", "modified", "function", "tests/test_m.py", None, None),
        SymbolChange("pkg.m:f#0", "modified", "function", "pkg/m.py", None, None),
    ]
    found = testdiff.test_changes(
        changes, base_map, head_map, (resolver(sources), resolver(head_sources))
    )
    assert [(c.change, c.test) for c in found] == [
        ("test_removed", "tests/test_m.py::test_gone"),
        ("assertion_removed", "tests/test_m.py::test_a"),
        ("skip_added", "tests/test_m.py::test_b"),
    ]
    for change in found:
        record = change.evidence(RUN)
        models.Evidence.model_validate({**record, "seq": 1})
        models.DiffTestsPayload.model_validate(change.payload(record["id"]))
