"""Deterministic input-replay probes (E06).

Roadmap E06: "finds the seeded divergence in a fixture whose existing tests don't exercise it",
with probes deterministic across the two base runs (A and A2, the docs' A-prime). The
``probe-only`` fixture runs for real here (``test_the_probe_only_fixture``) and through
``repro run`` in ``test_run_stage.py``.
"""

import ast
import tomllib
from pathlib import Path
from typing import Any

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.analysis import analyse
from repro.gitops import Git, snapshot
from repro.provision import HostProvisioner, inspect_project
from repro.runner import probes, selection
from repro.runner.probes import Candidate, ProbeRun
from repro.runner.sides import Side
from repro.sandbox import Limits, ProcessSandbox
from repro_events import models

FIXTURES = Path(__file__).parent / "fixtures"
RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"


def spec_of(annotation: str) -> Any:
    return probes._spec(ast.parse(annotation, mode="eval").body)


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("int", {"kind": "int"}),
        ("str | None", {"kind": "union", "of": [{"kind": "str"}, {"kind": "none"}]}),
        ("Optional[float]", {"kind": "union", "of": [{"kind": "float"}, {"kind": "none"}]}),
        ("list[bool]", {"kind": "list", "of": {"kind": "bool"}}),
        ("Dict[str, list[int]]", {"kind": "dict", "of": {"kind": "list", "of": {"kind": "int"}}}),
        ("Union[int, str]", {"kind": "union", "of": [{"kind": "int"}, {"kind": "str"}]}),
    ],
)
def test_json_types(annotation: str, expected: Any) -> None:
    assert spec_of(annotation) == expected


@pytest.mark.parametrize(
    "annotation",
    [
        "Path",
        "dict[int, str]",
        "tuple[int, int]",
        "set[int]",
        "Any",
        "list",
        "'int'",
        "Callable[[], int]",
    ],
)
def test_what_is_not_probed(annotation: str) -> None:
    assert spec_of(annotation) is None


def parameters(source: str) -> Any:
    (node,) = ast.parse(source).body
    assert isinstance(node, ast.FunctionDef)
    return probes._parameters(node)


def test_parameters() -> None:
    assert parameters("def f(a: int, /, b: str, *, c: bool = True): pass") == (
        ("a", "positional", {"kind": "int"}),
        ("b", "positional", {"kind": "str"}),
        ("c", "keyword", {"kind": "bool"}),
    )
    assert parameters("def f(a: int, b): pass") is None  # one not annotated
    assert parameters("def f(*a: int): pass") is None
    assert parameters("def f(**a: int): pass") is None
    assert parameters("def f(a: int):\n    yield a") is None  # a generator
    assert parameters("def f(): pass") is None  # nothing to generate


CANDIDATE = Candidate(
    symbol="pkg.m:f#0",
    module=("pkg.m", "pkg.m"),
    name="f",
    file="pkg/m.py",
    roots=(".", "."),
    parameters=(("a", "positional", {"kind": "int"}), ("b", "keyword", {"kind": "str"})),
)


def test_inputs_are_the_same_every_time_and_distinct() -> None:
    first = probes.inputs(CANDIDATE)
    assert first == probes.inputs(CANDIDATE)
    assert len(first) == probes.EXAMPLES
    assert len({repr(i) for i in first}) == len(first)
    assert all(set(i) == {"args", "kwargs"} and list(i["kwargs"]) == ["b"] for i in first)
    assert all(-(2**31) <= i["args"][0] < 2**31 for i in first)
    assert CANDIDATE.call({"args": [3], "kwargs": {"b": "x"}}) == "f(a=3, b='x')"


def result(outcome: str = "return", digest: str = "a", **extra: Any) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "result": digest,
        "complete": True,
        "type": "int",
        "preview": digest,
        **extra,
    }


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        (result(), result(), None),
        (result(), result(digest="b"), "result_changed"),
        (result(), result("raise", type="builtins.ValueError"), "exception_added"),
        (result("raise", type="E"), result(), "exception_removed"),
        (result("raise", type="E"), result("raise", digest="b", type="E"), "exception_changed"),
        (result(any_order="z"), result(digest="b", any_order="z"), "order_only"),
        (result(complete=False), result(digest="b", complete=False), None),  # unknowable
    ],
    ids=["same", "result", "added", "removed", "changed", "order", "incomplete"],
)
def test_change_of(base: dict[str, Any], head: dict[str, Any], expected: str | None) -> None:
    assert probes.change_of(base, head) == expected


def test_inputs_that_differ_between_a_and_a2_are_left_out() -> None:
    given = [[{"args": [n], "kwargs": {"b": ""}} for n in range(4)]]
    runs = {
        "A": ProbeRun("base", "A", {(0, i): result(digest=str(i)) for i in range(4)}),
        "A2": ProbeRun("base", "A2", {(0, 0): result(digest="0"), (0, 1): result(digest="x"),
                                      (0, 2): result(digest="2"), (0, 3): result(digest="3")}),
        "H": ProbeRun("head", "H", {(0, 0): result(digest="0"), (0, 1): result(digest="y"),
                                     (0, 2): result(digest="q"), (0, 3): result(digest="r")}),
    }  # fmt: skip
    found = probes.compare([CANDIDATE], given, runs)
    assert found.unstable == {"pkg.m:f#0": 1}  # input 1: A and A2 disagree
    (difference,) = found.differences
    assert (difference.change, difference.inputs, difference.tried) == ("result_changed", [2, 3], 4)
    assert difference.probe_id == "probe_f_2"
    record = difference.evidence(RUN_ID, [])
    record["seq"] = 1
    models.Evidence.model_validate(record)
    assert record["data"]["provenance"] == "generated"
    models.DiffProbePayload.model_validate(difference.payload(record["id"]))
    for item in found.missing():
        models.MissingRecordedPayload.model_validate(item)
    assert [m["missing"]["reason"] for m in found.missing()] == ["unstable_observation"]


def test_a_run_cut_short_or_an_import_that_fails_is_said_so() -> None:
    runs = {
        "A": ProbeRun("base", "A", {}, {0: "ModuleNotFoundError: pkg"}),
        "A2": ProbeRun("base", "A2", {}),
        "H": ProbeRun("head", "H", {}, complete=False),
    }
    found = probes.compare([CANDIDATE], [[]], runs)
    assert [m["missing"]["reason"] for m in found.missing()] == ["environment_failed", "timeout"]


def test_the_probe_only_fixture(tmp_path: Path) -> None:
    expected = tomllib.loads((FIXTURES / "probe-only.toml").read_text(encoding="utf-8"))
    built = build_repo(ALL_SPECS["probe-only"], tmp_path / "repo")
    git = Git(built.path)
    base, head = built.base_sha, built.head_shas[expected["fixture"]["head"]]
    changes = analyse(git, base, head, tmp_path / "analysis").changes.changes
    found = probes.candidates(changes, selection.side_resolvers(git, base, head))
    assert [c.symbol for c in found] == ["stats.ratio:percent#0"]
    provisioner = HostProvisioner(tmp_path / "envs")
    sides = []
    for side, sha in (("base", base), ("head", head)):
        tree = snapshot(git, sha, tmp_path / side / "snapshot")
        box = ProcessSandbox(tmp_path / side / "work", Limits(timeout_s=300))
        sides.append(Side(side, box, provisioner.provision(side, inspect_project(tree.root), box)))
    probing = probes.probe((sides[0], sides[1]), found, timeout_s=120)
    assert all(run.complete and not run.errors for run in probing.runs.values())
    assert probing.unstable == {}  # deterministic across A and A2
    (difference,) = probing.differences
    assert (
        f"probe_diff:{difference.change}:{difference.candidate.symbol}"
        in expected["expected"]["evidence"]
    )
    call, base_shown, head_shown = expected["expected"]["probe"]
    assert difference.candidate.call(difference.first_input) == call
    assert difference.previews() == (base_shown, head_shown)
    assert difference.found_by == ["hypothesis"]


# -- proposed inputs (G07) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "fitting", "not_fitting"),
    [
        ("int", [0, -(2**31), 2**31 - 1], [True, 2**31, 1.0, "1", None]),
        ("float", [0, 1.5, -2], [True, float("nan"), float("inf"), "1.5"]),
        ("str", ["", "x" * probes.MAX_PROPOSED], ["x" * (probes.MAX_PROPOSED + 1), 1, None]),
        ("bool", [True, False], [0, 1, "true"]),
        ("None", [None], [0, "", False]),
        ("list[int]", [[], [1, 2]], [[1, "2"], (1,), {"a": 1}, [True]]),
        ("dict[str, float]", [{}, {"a": 1.5}], [{"a": "x"}, [1.5]]),
        ("int | None", [3, None], ["3", 1.5]),
        ("Optional[list[str]]", [None, ["a"]], [[None], "a"]),
    ],
)
def test_fits(annotation: str, fitting: list[Any], not_fitting: list[Any]) -> None:
    spec = spec_of(annotation)
    assert [probes.fits(spec, value) for value in fitting] == [True] * len(fitting)
    assert [probes.fits(spec, value) for value in not_fitting] == [False] * len(not_fitting)


def test_a_proposal_names_exactly_the_parameters() -> None:
    assert probes.arranged(CANDIDATE, {"a": 1, "b": "x"}) == {"args": [1], "kwargs": {"b": "x"}}
    assert probes.arranged(CANDIDATE, {"b": "x", "a": 1}) == {"args": [1], "kwargs": {"b": "x"}}
    assert probes.arranged(CANDIDATE, {"a": 1}) is None  # one missing
    assert probes.arranged(CANDIDATE, {"a": 1, "b": "x", "c": 2}) is None  # one it has not
    assert probes.arranged(CANDIDATE, {"a": "1", "b": "x"}) is None  # not of its type
    assert probes.arranged(CANDIDATE, [1, "x"]) is None  # not by name
    assert probes.arranged(CANDIDATE, None) is None


def test_differences_say_which_inputs_found_them() -> None:
    # Two generated inputs, then two proposed: one the base runs disagree on, one that differs.
    given = [[{"args": [n], "kwargs": {"b": ""}} for n in range(4)]]
    runs = {
        "A": ProbeRun("base", "A", {(0, i): result(digest=str(i)) for i in range(4)}),
        "A2": ProbeRun("base", "A2", {(0, 0): result(digest="0"), (0, 1): result(digest="1"),
                                      (0, 2): result(digest="x"), (0, 3): result(digest="3")}),
        "H": ProbeRun("head", "H", {(0, 0): result(digest="0"), (0, 1): result(digest="y"),
                                     (0, 2): result(digest="2"), (0, 3): result(digest="z")}),
    }  # fmt: skip
    found = probes.compare([CANDIDATE], given, runs, [2])
    assert found.generated == [2]
    assert found.proposed == {"ran": 2, "unstable": 1, "differing": 1}
    (difference,) = found.differences
    assert (difference.inputs, difference.found_by) == ([1, 3], ["agent", "hypothesis"])
    record = difference.evidence(RUN_ID, [])
    assert (record["data"]["inputs_proposed"], record["data"]["found_by"]) == (
        2,
        ["agent", "hypothesis"],
    )
    # Without proposals, every input is Hypothesis's.
    assert probes.compare([CANDIDATE], given, runs).proposed == {
        "ran": 0,
        "unstable": 0,
        "differing": 0,
    }


def test_the_probe_semantic_fixture_needs_a_realistic_input(tmp_path: Path) -> None:
    """G07's acceptance: the tests pass on a wrong change, Hypothesis's inputs find nothing, and
    a realistic proposed input exposes the divergence; a repeat of a generated input is not run
    twice."""
    built = build_repo(ALL_SPECS["probe-semantic"], tmp_path / "repo")
    git = Git(built.path)
    base, head = built.base_sha, built.head_shas["refactor/to-utc"]
    changes = analyse(git, base, head, tmp_path / "analysis").changes.changes
    found = probes.candidates(changes, selection.side_resolvers(git, base, head))
    assert [c.symbol for c in found] == ["stamps.utc:to_utc#0"]
    provisioner = HostProvisioner(tmp_path / "envs")
    sides = []
    for side, sha in (("base", base), ("head", head)):
        tree = snapshot(git, sha, tmp_path / side / "snapshot")
        box = ProcessSandbox(tmp_path / side / "work", Limits(timeout_s=300))
        sides.append(Side(side, box, provisioner.provision(side, inspect_project(tree.root), box)))
    alone = probes.probe((sides[0], sides[1]), found, timeout_s=120)
    assert alone.differences == []
    repeat = alone.inputs[0][0]
    half_hour = {"args": ["2026-03-01T09:00:00+05:30"], "kwargs": {}}
    whole_hour = {"args": ["2026-03-01T09:00:00-05:00"], "kwargs": {}}
    probing = probes.probe(
        (sides[0], sides[1]), found, proposed=[[repeat, half_hour, whole_hour]], timeout_s=120
    )
    assert probing.inputs[0][-2:] == [half_hour, whole_hour]
    assert len(probing.inputs[0]) == len(alone.inputs[0]) + 2
    assert probing.proposed == {"ran": 2, "unstable": 0, "differing": 1}
    (difference,) = probing.differences
    assert (difference.change, difference.found_by) == ("result_changed", ["agent"])
    assert difference.candidate.call(difference.first_input) == (
        "to_utc(text='2026-03-01T09:00:00+05:30')"
    )
    assert difference.previews() == ("'2026-03-01T03:30:00+00:00'", "'2026-03-01T04:00:00+00:00'")
