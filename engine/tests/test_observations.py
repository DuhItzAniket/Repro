"""Behaviour observations (E03): keys, A vs A2 stability, masking, artifacts.

Roadmap E03: "on fixtures with time, random and set-order noise, all noise is classified
`unstable` and none of it becomes a diff." The unit tests build traced runs by hand; the
``noisy`` fixture runs for real (``test_noise_is_unstable_and_never_a_difference``), and
``test_run_stage.py`` runs it through ``repro run`` with the stored artifacts.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.analysis import analyse
from repro.analysis.changes import SymbolChange
from repro.gitops import Git, snapshot
from repro.provision import HostProvisioner, inspect_project
from repro.runner import observations, selection, twosided
from repro.runner.observations import Behaviour, RunObservations, compare, observe
from repro.runner.pytest import PytestRun, TraceCall, read_results
from repro.runner.pytest import TestResult as Reported
from repro.runner.sides import Side
from repro.runner.trace import TracePlan, plan
from repro.sandbox import Limits, ProcessSandbox
from repro.store import cbor
from repro_events import models

FIXTURES = Path(__file__).parent / "fixtures"
F = ("pkg/m.py", "f", 1, 3)
G = ("pkg/m.py", "g", 5, 9)
NAMES = {F: "pkg.m:f#0", G: "pkg.m:g#0"}
T1, T2 = "tests/test_m.py::test_one", "tests/test_m.py::test_two"


def digest(n: int) -> str:
    return f"{n:032x}"


def call(
    test: str = T1,
    target: tuple[str, str, int, int] = F,
    index: int = 0,
    args: int = 1,
    result: int | str = 2,
    **changes: Any,
) -> TraceCall:
    fields: dict[str, Any] = {
        "test": test,
        "phase": "call",
        "target": target,
        "index": index,
        "args": digest(args),
        "args_complete": True,
        "outcome": "return",
        "result": digest(result) if isinstance(result, int) else result,
        "result_complete": True,
        "type": "builtins.int",
        "yields": (),
        "yields_complete": True,
        "result_any_order": None,
    }
    fields.update(changes)
    return TraceCall(**fields)


def run(*calls: TraceCall, tests: tuple[str, ...] = (T1, T2), **extra: Any) -> PytestRun:
    reported = {t: Reported(t, "passed", 0.01, None, None) for t in tests}
    return PytestRun(reported, (), {"exitstatus": 0}, calls=calls, **extra)


def observed(label: str, *calls: TraceCall, **options: Any) -> RunObservations:
    side = "head" if label == "H" else "base"
    return observe(label, side, run(*calls, **options), NAMES)


def compared(a: RunObservations, a2: RunObservations, h: RunObservations) -> dict[Any, Any]:
    behaviour = compare(a, a2, h)
    return {(c.key[0], c.key[3], c.key[4]): c for c in behaviour.compared}


# -- keys ----------------------------------------------------------------------------------------


def test_calls_are_keyed_by_their_arguments_and_occurrence() -> None:
    seen = observed(
        "A",
        call(index=0, args=1),
        call(index=1, args=7),
        call(index=2, args=1, result=3),  # the same arguments again: occurrence 1
        call(index=3, args=9, args_complete=False),  # no key
        call(target=("other.py", "h", 1, 2)),  # not a target of this plan
    )
    assert sorted(seen.calls) == [
        (T1, "call", "pkg.m:f#0", digest(1), 0),
        (T1, "call", "pkg.m:f#0", digest(1), 1),
        (T1, "call", "pkg.m:f#0", digest(7), 0),
    ]
    assert seen.calls[(T1, "call", "pkg.m:f#0", digest(1), 1)].result == digest(3)
    assert seen.unkeyed == {(T1, "call", "pkg.m:f#0"): 1}


def test_a_call_in_another_order_is_the_same_key() -> None:
    first = observed("A", call(index=0, args=1), call(target=G, index=0, args=5))
    later = observed("H", call(target=G, index=0, args=5), call(index=0, args=1))
    assert first.calls.keys() == later.calls.keys()


# -- stability and masking -----------------------------------------------------------------------


def test_what_differs_between_a_and_a2_is_masked() -> None:
    a = observed("A", call(result=2), call(test=T2, result=4))
    a2 = observed("A2", call(result=3), call(test=T2, result=4))
    h = observed("H", call(result=5), call(test=T2, result=6))
    found = compared(a, a2, h)
    noisy, steady = found[(T1, digest(1), 0)], found[(T2, digest(1), 0)]
    assert (noisy.stability, noisy.unstable, noisy.differs) == ("unstable", ("value", "order"), ())
    assert (steady.stability, steady.unstable, steady.differs) == ("stable", (), ("value", "order"))


def test_inputs_that_differ_between_a_and_a2_mask_the_call_set() -> None:
    a = observed("A", call(args=1, result=2))  # e.g. the time as an argument
    a2 = observed("A2", call(args=2, result=2))
    h = observed("H", call(args=3, result=2))
    behaviour = compare(a, a2, h)
    assert behaviour.stability.groups == frozenset({(T1, "call", "pkg.m:f#0")})
    assert [(c.unstable, c.differs) for c in behaviour.compared] == [(("call",), ())] * 2
    assert behaviour.differences() == []


def test_a_call_a2_did_not_make_is_masked_in_a_noisy_call_set() -> None:
    """A and H drew the same random argument (both run with seed 0), A2 another: the call
    is joined across A and H, but nothing shows its result is stable."""
    a = observed("A", call(args=1, result=2))
    a2 = observed("A2", call(args=9, result=2))
    h = observed("H", call(args=1, result=3))
    (joined,) = [c for c in compare(a, a2, h).compared if c.base and c.head]
    assert (joined.stability, joined.unstable, joined.differs) == (
        "unstable",
        ("value", "order"),
        (),
    )


def test_a_change_with_stable_noise_elsewhere_is_still_found() -> None:
    a = observed("A", call(result=2), call(target=G, result=8))
    a2 = observed("A2", call(result=2), call(target=G, result=9))  # g is noisy, f is not
    h = observed("H", call(result=3), call(target=G, result=10))
    (difference,) = compare(a, a2, h).differences()
    assert difference.key[2] == "pkg.m:f#0"
    assert difference.differs == ("value", "order")


def test_a_test_a2_did_not_report_has_no_stability() -> None:
    a = observed("A", call(result=2))
    a2 = observed("A2", tests=(T2,))
    h = observed("H", call(result=3))
    (item,) = compare(a, a2, h).compared
    assert (item.stability, item.differs) == ("n/a", ("value", "order"))


def test_order_alone() -> None:
    a = observed("A", call(result=2, result_any_order=digest(20)))
    a2 = observed("A2", call(result=2, result_any_order=digest(20)))
    h = observed("H", call(result=3, result_any_order=digest(20)))  # same entries, new order
    (item,) = compare(a, a2, h).compared
    assert item.differs == ("order",)


def test_calls_on_one_side_only() -> None:
    a = observed("A", call(args=1), call(index=1, args=2))
    a2 = observed("A2", call(args=1), call(index=1, args=2))
    h = observed("H", call(args=1), call(index=1, args=3))
    found = compared(a, a2, h)
    assert found[(T1, digest(2), 0)].differs == ("call",)
    assert found[(T1, digest(2), 0)].head is None
    assert found[(T1, digest(3), 0)].differs == ("call",)
    assert found[(T1, digest(3), 0)].base is None
    assert found[(T1, digest(1), 0)].differs == ()


def test_what_cannot_be_compared_is_never_a_difference() -> None:
    a = observed("A", call(result=2, result_complete=False), call(test=T2, result=2))
    a2 = observed("A2", call(result=2, result_complete=False), call(test=T2, result=2))
    h = observed("H", call(result=3, result_complete=False), call(test=T2, outcome="unfinished"))
    found = compared(a, a2, h)
    assert found[(T1, digest(1), 0)].unknown == ("value", "order")
    assert found[(T1, digest(1), 0)].differs == ()
    assert found[(T2, digest(1), 0)].unknown == ("outcome", "type", "value", "order", "yields")
    assert found[(T2, digest(1), 0)].differs == ()


def test_a_spent_budget_hides_calls_rather_than_inventing_them() -> None:
    a = observed("A", call(args=1), call(index=1, args=2), truncated=((T1, F),))
    a2 = observed("A2", call(args=1), call(index=1, args=2), truncated=((T1, F),))
    h = observed("H", call(args=1), truncated=((T1, F),))
    found = compared(a, a2, h)
    assert found[(T1, digest(2), 0)].unknown == ("call",)
    assert found[(T1, digest(2), 0)].differs == ()


def test_a_suspended_generator_is_compared_by_what_it_yielded() -> None:
    def generator(yields: tuple[int, ...]) -> TraceCall:
        values = tuple(digest(y) for y in yields)
        return call(outcome="suspended", result="", result_complete=False, yields=values, type="")

    a = observed("A", generator((1, 2)))
    a2 = observed("A2", generator((1, 2)))
    h = observed("H", generator((1, 3)))
    (item,) = compare(a, a2, h).compared
    assert (item.differs, item.unknown) == (("yields",), ())


# -- missing items -------------------------------------------------------------------------------


def test_missing_items_name_the_function_and_its_tests() -> None:
    a = observed("A", call(result=2), call(target=G, args=4, args_complete=False))
    a2 = observed("A2", call(result=3), call(target=G, args=4, args_complete=False))
    h = observed("H", call(result=3), call(target=G, args=4, args_complete=False))
    h.truncated = frozenset({(T2, "pkg.m:g#0")})
    behaviour = compare(a, a2, h)
    behaviour.left_out = ("pkg.n:z#0",)
    items = observations.missing(behaviour)
    for item in items:
        models.MissingRecordedPayload.model_validate(item)
    found = [
        (
            m["missing"]["reason"],
            [t.get("symbol") or t.get("test") for t in m["missing"]["targets"]],
        )
        for m in items
    ]
    assert found == [
        ("unstable_observation", ["pkg.m:f#0", T1]),
        ("encoding_failed", ["pkg.m:g#0", T1]),
        ("trace_truncated", ["pkg.m:g#0", T2]),
        ("trace_unavailable", ["pkg.n:z#0"]),
    ]
    assert "differ between two runs of base (order, value)" in items[0]["missing"]["detail"]


# -- artifacts -----------------------------------------------------------------------------------


def test_observations_round_trip_as_deterministic_cbor() -> None:
    seen = observed(
        "A",
        call(index=1, args=2, result_any_order=digest(30)),
        call(index=0, args=1, outcome="suspended", result="", yields=(digest(4),)),
        call(index=2, args=3, args_complete=False),
        truncated=((T1, F),),
    )
    data = observations.dump_observations(seen)
    assert observations.dump_observations(observations.load_observations(data)) == data
    back = observations.load_observations(data)
    assert (back.calls, back.tests, back.unkeyed, back.truncated) == (
        seen.calls,
        seen.tests,
        seen.unkeyed,
        seen.truncated,
    )
    reordered = observed(
        "A",
        call(index=2, args=3, args_complete=False),
        call(index=0, args=1, outcome="suspended", result="", yields=(digest(4),)),
        call(index=1, args=2, result_any_order=digest(30)),
        truncated=((T1, F),),
    )
    assert observations.dump_observations(reordered) == data  # the same bytes


def test_load_refuses_another_document() -> None:
    with pytest.raises(cbor.CBORError):
        observations.load_observations(cbor.encode({"format": "something else"}))
    with pytest.raises(cbor.CBORError):
        observations.load_observations(b"\xa0")


def test_the_comparison_document_cites_the_observations() -> None:
    a, a2, h = observed("A", call()), observed("A2", call()), observed("H", call(result=9))
    behaviour = compare(a, a2, h)
    refs = {label: {"path": f"obs/{label}.cbor", "sha256": "0" * 64} for label in ("A", "A2", "H")}
    document = cbor.decode(observations.dump_behaviour(behaviour, refs))
    assert document["observations"]["H"]["path"] == "obs/H.cbor"
    assert document["counts"] == behaviour.counts()
    (row,) = document["compared"]
    assert row[document["fields"].index("differs")] == ["value", "order"]


# -- the trace file ------------------------------------------------------------------------------


def test_a_cut_trace_is_said_so() -> None:
    session = b'{"kind": "session", "exitstatus": 0, "collected": 0}\n'
    cut = b'{"kind": "trace_cut", "bytes": 67108800, "limit": 67108864}\n'
    assert read_results(cut + session).trace_cut == "the trace reached its limit of 64 MiB"
    longer = read_results(session, b"", calls_cut=True)
    assert longer.trace_cut is not None
    assert "longer than" in longer.trace_cut
    assert read_results(session).trace_cut is None


def test_calls_come_from_their_own_file() -> None:
    session = b'{"kind": "session", "exitstatus": 0, "collected": 0}\n'
    record = (
        b'{"kind": "call", "nodeid": "t.py::a", "phase": "call", "target": ["m.py", "f", 1, 2],'
        b' "index": 0, "args": "' + digest(1).encode() + b'", "args_complete": true,'
        b' "outcome": "return", "result": "' + digest(2).encode() + b'", "result_complete": true,'
        b' "type": "builtins.int", "yields": [], "yields_complete": true}\n'
    )
    assert len(read_results(session, record).calls) == 1
    assert read_results(session + record).calls == ()  # not a results record: malformed
    assert read_results(session + record).malformed == 1


# -- the plan ------------------------------------------------------------------------------------


def test_the_plan_leaves_out_test_code() -> None:
    traced = TracePlan(
        {F: "pkg.m:f#0", ("tests/conftest.py", "fx", 1, 2): "conftest:fx#0", G: "tests.t:g#0"},
        {F: "pkg.m:f#0", ("tests/conftest.py", "fx", 1, 2): "conftest:fx#0"},
    )
    kept = traced.without_test_code({"tests.t"})
    assert (dict(kept.base), dict(kept.head)) == ({F: "pkg.m:f#0"}, {F: "pkg.m:f#0"})


def test_the_plan_traces_functions_on_both_sides(tmp_path: Path) -> None:
    built = build_repo(ALL_SPECS["noisy"], tmp_path / "repo")
    git = Git(built.path)
    head = built.head_shas["change/tidy"]
    changes = analyse(git, built.base_sha, head, tmp_path / "analysis").changes.changes
    resolvers = selection.side_resolvers(git, built.base_sha, head)
    traced = plan(changes, resolvers)
    names = ["fruit", "roll", "since", "stamp", "total"]
    assert sorted(t[1] for t in traced.base) == names
    assert sorted(t[1] for t in traced.head) == names
    assert sorted(traced.base.values()) == sorted(traced.head.values())
    added = SymbolChange("pkg.m:new#0", "added", "function", "pkg/m.py", None, (1, 2))
    assert not plan([added], resolvers)  # nothing on base to compare it with


# -- the noisy fixture, for real -----------------------------------------------------------------


def test_noise_is_unstable_and_never_a_difference(tmp_path: Path) -> None:
    expected = tomllib.loads((FIXTURES / "noisy.toml").read_text(encoding="utf-8"))
    built = build_repo(ALL_SPECS["noisy"], tmp_path / "repo")
    git = Git(built.path)
    base, head = built.base_sha, built.head_shas[expected["fixture"]["head"]]
    analysis = analyse(git, base, head, tmp_path / "analysis")
    provisioner = HostProvisioner(tmp_path / "envs")
    sides = []
    for side, sha in (("base", base), ("head", head)):
        tree = snapshot(git, sha, tmp_path / side / "snapshot")
        box = ProcessSandbox(tmp_path / side / "work", Limits(timeout_s=300))
        sides.append(Side(side, box, provisioner.provision(side, inspect_project(tree.root), box)))
    resolvers = selection.side_resolvers(git, base, head)
    result = twosided.reproduce(
        (sides[0], sides[1]),
        analysis.changes.changes,
        (analysis.base, analysis.head),
        resolvers,
        trace=plan(analysis.changes.changes, resolvers),
    )
    traced = result.traced()
    assert traced["A2"].run.results.session is not None
    assert traced["A2"].run.results.session["seed"] == twosided.OTHER_SEED
    behaviour = observations.behaviour_of(result)
    assert isinstance(behaviour, Behaviour)
    assert behaviour.differences() == []
    assert len(behaviour.differences()) == expected["expected"]["differences"]
    stability = {c.key[2].split(":")[1]: c.stability for c in behaviour.compared}
    assert stability == {
        "fruit#0": "unstable",  # a set's order: another hash seed
        "roll#0": "unstable",  # a random draw: another seed
        "since#0": "unstable",  # called with the time
        "stamp#0": "unstable",  # returns the time
        "total#0": "stable",
    }
    (steady,) = [c for c in behaviour.compared if c.stability == "stable"]
    assert steady.base is not None
    assert steady.head is not None
    assert (steady.differs, steady.unstable, steady.unknown) == ((), (), ())
    found = [
        f"{item['missing']['reason']}:{target.get('symbol') or target['test']}"
        for item in observations.missing(behaviour)
        for target in item["missing"]["targets"]
    ]
    assert sorted(found) == sorted(expected["expected"]["behaviour"])
