"""Behaviour differences (E04): classes, groups, reproducers and their evidence.

Roadmap E04: "the silent-change and false-claim fixtures produce the expected stable diffs
with working reproducers." The unit tests build observations by hand (``test_observations``'s
helpers); the two fixtures run for real in ``test_the_fixtures_give_stable_reproduced_diffs``,
and through ``repro run`` in ``test_run_stage.py``.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.analysis import analyse
from repro.gitops import Git, snapshot
from repro.provision import HostProvisioner, inspect_project
from repro.runner import behaviour as diffs
from repro.runner import observations, selection, twosided
from repro.runner.observations import Compared, compare
from repro.runner.sides import Side
from repro.runner.trace import plan
from repro.sandbox import Limits, ProcessSandbox
from repro_events import models
from test_observations import T1, T2, G, call, digest, observed

FIXTURES = Path(__file__).parent / "fixtures"
RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"


def compared(base: dict[str, Any], head: dict[str, Any], **shared: Any) -> Compared:
    """One call compared: A and A2 alike (``base``), H as ``head``."""
    a = observed("A", call(**shared, **base))
    a2 = observed("A2", call(**shared, **base))
    h = observed("H", call(**shared, **head))
    (item,) = compare(a, a2, h).compared
    return item


RAISED = {"outcome": "raise", "type": "builtins.ValueError"}


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        ({"result": 2}, {"result": 3}, ["result_changed"]),
        ({"result": 2}, {"result": 2, "type": "builtins.float"}, ["result_changed"]),
        ({"result": 2}, {"result": 4, **RAISED}, ["exception_added"]),
        ({"result": 4, **RAISED}, {"result": 2}, ["exception_removed"]),
        ({"result": 4, **RAISED}, {"result": 5, **RAISED}, ["exception_changed"]),
        (
            {"result": 2, "result_any_order": digest(20)},
            {"result": 3, "result_any_order": digest(20)},
            ["order_only"],
        ),
        ({"result": 2}, {"result": 2, "args_after": digest(9)}, ["input_mutated"]),
        (
            {"result": 2},
            {"result": 3, "args_after": digest(9)},
            ["result_changed", "input_mutated"],
        ),
        ({"result": 2}, {"result": 2}, []),
    ],
    ids=[
        "result",
        "type",
        "added",
        "removed",
        "changed",
        "order",
        "mutated",
        "both",
        "same",
    ],
)
def test_each_class(base: dict[str, Any], head: dict[str, Any], expected: list[str]) -> None:
    assert diffs.classes(compared(base, head)) == expected


def test_calls_on_one_side_are_calls_changed() -> None:
    a = observed("A", call(args=1), call(index=1, args=2))
    a2 = observed("A2", call(args=1), call(index=1, args=2))
    h = observed("H", call(args=1))
    found = diffs.differences(compare(a, a2, h))
    assert [(d.change, d.first.head) for d in found] == [("calls_changed", None)]


def test_differences_are_grouped_by_test_function_and_class() -> None:
    a = observed("A", call(args=1), call(index=1, args=2), call(test=T2), call(target=G))
    a2 = observed("A2", call(args=1), call(index=1, args=2), call(test=T2), call(target=G))
    h = observed(
        "H",
        call(args=1, result=7),
        call(index=1, args=2, result=7, args_after=digest(5)),
        call(test=T2, result=8),
        call(target=G),
    )
    found = diffs.differences(compare(a, a2, h), modified=frozenset({T2}))
    assert [(d.symbol, d.test, d.change, len(d.calls), d.test_modified) for d in found] == [
        ("pkg.m:f#0", T1, "result_changed", 2, False),
        ("pkg.m:f#0", T1, "input_mutated", 1, False),
        ("pkg.m:f#0", T2, "result_changed", 1, True),
    ]


def test_masked_noise_is_never_a_difference() -> None:
    a = observed("A", call(result=2))
    a2 = observed("A2", call(result=3))  # the result is noise
    h = observed("H", call(result=4))
    assert diffs.differences(compare(a, a2, h)) == []


def test_evidence_and_payload_match_the_schema() -> None:
    (difference,) = diffs.differences(
        compare(observed("A", call()), observed("A2", call()), observed("H", call(result=3)))
    )
    difference.reproduced = True
    key = difference.first.key
    again_base = observed("A", call(args_preview="f(x=1)", result_preview="2"))
    again_head = observed("H", call(result=3, args_preview="f(x=1)", result_preview="3"))
    difference.base_again, difference.head_again = again_base.calls[key], again_head.calls[key]
    ref = {
        "path": "obs/behaviour.cbor",
        "sha256": "0" * 64,
        "media_type": "application/cbor",
        "size_bytes": 10,
    }
    record = difference.evidence(RUN_ID, [ref])
    record["seq"] = 1
    models.Evidence.model_validate(record)
    payload = difference.payload(record["id"])
    models.DiffBehaviourPayload.model_validate(payload)
    assert (payload["change"], payload["stability"]) == ("result_changed", "stable")
    assert (payload["base_preview"], payload["head_preview"]) == ("2", "3")
    assert record["summary"] == f"f(x=1) gives another result: head 3, base 2 (in {T1})"
    assert record["data"]["reproducer"] == {
        "test": T1,
        "command": f"python -m pytest {T1}",
        "call": "f(x=1)",
        "base": "2",
        "head": "3",
        "reproduced": True,
    }
    assert record["origin"] == "introduced"


def test_a_difference_that_does_not_come_back_is_unstable() -> None:
    a, a2, h = observed("A", call()), observed("A2", call()), observed("H", call(result=3))
    (difference,) = diffs.differences(compare(a, a2, h))
    again_base, again_head = observed("A", call()), observed("H", call(result=4))
    diffs._check(difference, again_base, again_head)
    assert (difference.reproduced, difference.stability) == (False, "unstable")
    models.MissingRecordedPayload.model_validate(difference.missing())
    (other,) = diffs.differences(compare(a, a2, h))
    diffs._check(other, observed("A", call()), observed("H", call(result=3)))
    assert (other.reproduced, other.stability) == (True, "stable")
    (unseen,) = diffs.differences(compare(a, a2, h))
    diffs._check(unseen, observed("A", tests=(T2,)), observed("H", call(result=3)))
    assert (unseen.reproduced, unseen.stability) == (None, "stable")  # its test did not run


def test_a_summary_without_previews_still_names_the_call() -> None:
    (difference,) = diffs.differences(
        compare(observed("A", call()), observed("A2", call()), observed("H", call(result=3)))
    )
    assert difference.summary().startswith(f"f(… arguments {digest(1)[:12]}) gives another result")


# -- the fixtures, for real ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["silent-change", "false-claim"])
def test_the_fixtures_give_stable_reproduced_diffs(name: str, tmp_path: Path) -> None:
    expected = tomllib.loads((FIXTURES / f"{name}.toml").read_text(encoding="utf-8"))
    built = build_repo(ALL_SPECS[name], tmp_path / "repo")
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
    assert {d.outcome_class for d in result.outcomes} == {"P2P"}  # no test outcome changes
    behaviour = observations.behaviour_of(result)
    assert behaviour is not None
    assert behaviour.plan is not None
    found = diffs.differences(behaviour)
    diffs.reproduce(found, (sides[0], sides[1]), behaviour.plan)
    listed = [i for i in expected["expected"]["evidence"] if i.startswith("behaviour_diff:")]
    assert sorted(f"behaviour_diff:{d.change}:{d.test}" for d in found) == sorted(listed)
    shown = {f"{d.change}:{d.test}": list(d.previews()) for d in found}
    assert shown == expected["reproducers"]  # (base, head) as the reproducer run showed them
    for difference in found:
        assert (difference.stability, difference.reproduced) == ("stable", True)
        assert difference.call_text().startswith(difference.symbol.split(":")[1].split("#")[0])
