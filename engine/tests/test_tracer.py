"""Repro's tracer (E01), run for real in the process sandbox on Python 3.12 to 3.15.

The suite (``data/trace_suite``) calls one function per kind of call the tracer records:
returns, raises, generators run out and abandoned, recursion, threads, keyword and starred
arguments, methods, a fixture's setup, and a loop past the budget. Digests are checked against
the encoder itself (loaded from the hook directory, as the sandbox loads it), and must be the
same on every Python and under another hash seed.
"""

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from repro.analysis.symbols import build_table
from repro.provision import HostProvisioner, inspect_project
from repro.runner import run_tests
from repro.runner import trace as tracing
from repro.runner.pytest import PytestRun, TraceTarget
from repro.sandbox import Limits, ProcessSandbox
from repro.sandbox.detect import HOOK_DIR

SUITE = Path(__file__).parent / "data" / "trace_suite"
PYTHONS = ("3.12", "3.13", "3.14", "3.15")
TRACED = (
    "add",
    "fails",
    "gen",
    "recurse",
    "with_kw",
    "Box.size",
    "ordered",
    "extend",
    "label",
)


def hook_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HOOK_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENCODE = hook_module("repro_encode")


def digest(value: Any) -> str:
    found, complete = ENCODE.digest(value)
    assert complete
    return str(found)


def targets() -> list[TraceTarget]:
    table = build_table((SUITE / "calc.py").read_bytes(), "calc")
    return [("calc.py", s.qualname, s.start, s.end) for s in table.symbols if s.qualname in TRACED]


class Side:
    def __init__(self, provisioner: HostProvisioner, root: Path) -> None:
        self.snapshot = root / "snapshot"
        shutil.copytree(SUITE, self.snapshot, ignore=shutil.ignore_patterns("coverage_conftest.py"))
        self.box = ProcessSandbox(root / "work", Limits(timeout_s=300))
        self.env = provisioner.provision("base", inspect_project(self.snapshot), self.box)

    def trace(self, **options: Any) -> PytestRun:
        run = run_tests(self.box, self.env, trace=targets(), **options)
        assert run.results.complete, run.execution.stdout.decode(errors="replace")
        assert run.results.outcomes()
        assert set(run.results.outcomes().values()) == {"passed"}
        return run.results


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("envs")


@pytest.fixture(scope="module")
def side(cache: Path, tmp_path_factory: pytest.TempPathFactory) -> Side:
    return Side(HostProvisioner(cache), tmp_path_factory.mktemp("side"))


def calls(results: PytestRun, test: str, qualname: str) -> list[Any]:
    grouped = tracing.calls_by_target(results)
    found = [
        call for (where, target), listed in grouped.items() if where == f"test_calc.py::{test}"
        and target[1] == qualname for call in listed
    ]  # fmt: skip
    return sorted(found, key=lambda call: call.index)


def test_each_kind_of_call(side: Side) -> None:
    results = side.trace()
    (first, second) = calls(results, "test_add", "add")
    assert (first.outcome, first.args, first.result) == (
        "return",
        digest((1, 2)),  # the parameters' values, in their order
        digest(3),
    )
    assert (second.args, second.result, second.type) == (
        digest(("a", "b")),
        digest("ab"),
        "builtins.str",
    )
    (raised,) = calls(results, "test_raise", "fails")
    assert (raised.outcome, raised.type, raised.result) == (
        "raise",
        "builtins.ValueError",
        digest(ValueError("bad", 3)),  # its type, arguments and (empty) cause chain
    )
    (generated,) = calls(results, "test_generator", "gen")
    assert generated.outcome == "return"
    assert generated.yields == (digest(0), digest(2), digest(4))
    (abandoned,) = calls(results, "test_abandoned_generator", "gen")
    # Collected when its test returned: Python closes it with GeneratorExit.
    assert (abandoned.outcome, abandoned.yields) == ("suspended", (digest(0),))
    recursion = calls(results, "test_recursion", "recurse")
    assert [c.args for c in recursion] == [digest((n,)) for n in range(5, -1, -1)]
    assert [c.result for c in recursion] == [digest(n) for n in range(5, -1, -1)]
    assert len(calls(results, "test_threads", "add")) == 4
    (keywords,) = calls(results, "test_keywords", "with_kw")
    starred = (1, 4, (2, 3), {"c": {"x", "y", "z"}})  # a, b, *args, **kw
    assert keywords.args == digest(starred)
    (method,) = calls(results, "test_method", "Box.size")
    assert (method.outcome, method.result, method.args_complete) == ("return", digest(3), True)
    (keyed,) = calls(results, "test_dict_order", "ordered")
    returned = {"bb": 2, "a": 1}
    ordered, any_order, _ = ENCODE.digests(returned)
    assert (keyed.result, keyed.result_any_order) == (ordered, any_order)
    assert keyed.result_any_order != keyed.result
    (fixture,) = calls(results, "test_setup_phase", "add")
    assert fixture.phase == "setup"
    assert {c.phase for c in calls(results, "test_add", "add")} == {"call"}


def test_input_mutation_and_previews(side: Side) -> None:
    """E04: arguments changed in place are encoded again when the call ends; the calls the
    engine names get previews (its reproducer), and no other call does."""
    (extend,) = [t for t in targets() if t[1] == "extend"]
    first = side.trace()
    (mutating,) = calls(first, "test_mutation", "extend")
    assert mutating.args == digest(([1], [2, 3]))
    assert mutating.args_after == digest(([1, 2, 3], [2, 3]))
    assert mutating.args_preview is None
    added = calls(first, "test_add", "add")
    assert {c.args_after for c in added} == {None}  # numbers and strings: not looked at again
    (method,) = calls(first, "test_method", "Box.size")
    assert method.args_after is None  # an object, encoded again, unchanged
    wanted = [("test_calc.py::test_mutation", extend, mutating.args)]
    again = side.trace(previews=wanted)
    (shown,) = calls(again, "test_mutation", "extend")
    assert shown.args_preview == "extend(items=[1], extra=[2, 3])"
    assert shown.result_preview == "3"
    assert shown.args_after_preview == "items=[1, 2, 3], extra=[2, 3]"
    assert {c.args_preview for c in again.calls if c.target != extend} == {None}


def test_a_call_whose_arguments_cannot_be_encoded_is_previewed_by_position(side: Side) -> None:
    """E03/E04: a call with arguments too deep or cyclic to encode is asked for as ``#n``, the
    n-th such call in its test's phase, and only that call is previewed."""
    (target,) = [t for t in targets() if t[1] == "label"]
    first = side.trace()
    cyclic = calls(first, "test_cycle", "label")
    assert [c.args_complete for c in cyclic] == [False, False]
    again = side.trace(previews=[("test_calc.py::test_cycle", target, "#1")])
    shown = calls(again, "test_cycle", "label")
    assert [c.result_preview for c in shown] == [None, "'node b'"]


def test_samples_preview_each_tests_first_calls(side: Side) -> None:
    """E07: with ``samples``, each (test, target)'s first calls carry previews."""
    results = side.trace(samples=1)
    first, second = calls(results, "test_add", "add")
    assert first.args_preview == "add(a=1, b=2)"
    assert first.result_preview == "3"
    assert second.args_preview is None
    budget = calls(results, "test_budget", "add")
    assert [c.args_preview is not None for c in budget[:3]] == [True, False, False]


def test_the_budget(side: Side) -> None:
    results = side.trace()
    budget = calls(results, "test_budget", "add")
    assert [c.index for c in budget] == list(range(200))
    assert [(test, target[1]) for test, target in results.truncated] == [
        ("test_calc.py::test_budget", "add")
    ]
    (item,) = tracing.trace_missing(results, "head")
    assert item["missing"]["reason"] == "trace_truncated"
    assert "add" in item["missing"]["detail"]


def comparable(results: PytestRun) -> set[tuple[Any, ...]]:
    return {
        (c.test, c.phase, c.target[1], c.index, c.args, c.outcome, c.result, c.type, c.yields)
        for c in results.calls
        if c.test != "test_calc.py::test_threads"  # four threads: their order is the OS's
    }


def test_the_same_digests_under_another_hash_seed(side: Side) -> None:
    """A and A2 (another PYTHONHASHSEED): string sets iterate in another order, digests do not."""
    assert comparable(side.trace(hash_seed=1)) == comparable(side.trace())


@pytest.mark.parametrize("python", ["3.12", "3.14", "3.15"])
def test_the_same_digests_on_every_python(
    side: Side, cache: Path, tmp_path: Path, python: str
) -> None:
    other = Side(HostProvisioner(cache, python=python), tmp_path)
    assert other.env.python_version.startswith(f"{python}.")
    assert comparable(other.trace()) == comparable(side.trace())


def test_beside_coverage(side: Side, tmp_path: Path) -> None:
    """coverage.py's sys.monitoring core holds its own tool ID (1): both measure."""
    snapshot = side.snapshot
    shutil.copyfile(SUITE / "coverage_conftest.py", snapshot / "conftest.py")
    try:
        results = side.trace()
    finally:
        (snapshot / "conftest.py").unlink()
    assert len(calls(results, "test_add", "add")) == 2
    assert results.map_unavailable is None
    (found,) = side.box.work.glob("pytest-*/coverage.json")
    report = json.loads(found.read_text(encoding="utf-8"))
    # coverage.py held its own ID (1, COVERAGE_ID) and Repro the first of its order (4).
    assert report["tools"]["1"] == "coverage.py"
    assert report["tools"]["4"] == "repro"
    assert "calc.py" in report["measured"]
    del tmp_path


def test_no_free_tool_id_is_a_missing_item(side: Side) -> None:
    busy = Path(__file__).parent / "fixtures" / "busy_conftest.py"
    shutil.copyfile(busy, side.snapshot / "conftest.py")
    try:
        results = side.trace()
    finally:
        (side.snapshot / "conftest.py").unlink()
    assert results.calls == ()
    (item,) = tracing.trace_missing(results, "base")
    assert item["missing"]["reason"] == "trace_unavailable"


def test_targets_come_from_symbols(tmp_path: Path) -> None:
    from repro.runner.selection import Resolver  # noqa: PLC0415

    source = (SUITE / "calc.py").read_bytes()
    resolver = Resolver({"calc.py": "calc"}, lambda paths: dict.fromkeys(paths, source))
    found = tracing.targets_for(
        ["calc:add#0", "calc:Box.size#0", "calc:<module>#0", "x:y#0"], resolver
    )
    assert [(t[0], t[1]) for t in found] == [("calc.py", "Box.size"), ("calc.py", "add")]
    del tmp_path
