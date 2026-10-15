"""Two-sided execution on the fixture repositories (D06), through ``reproduce``.

Roadmap D06: "the honest-fix, flaky, untested and new test-tamper fixtures produce exactly the
expected evidence." Each fixture's expectation file lists its evidence as
``<type>:<detail>:<target>`` and its missing items as ``<reason>:<target>``; the run must give
exactly those, with the expected selection. The pipeline's own events are checked end to end in
``test_run_stage.py``.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.analysis import analyse
from repro.gitops import Git, snapshot
from repro.ids import new_run_id
from repro.provision import HostProvisioner, inspect_project
from repro.runner import selection, twosided
from repro.runner.outcomes import unstable_observation
from repro.runner.sides import Side
from repro.sandbox import Limits, ProcessSandbox
from repro_events import models

FIXTURES = Path(__file__).parent / "fixtures"
RUN_ID = new_run_id()
FIXTURE_NAMES = [
    "honest-fix", "selection", "untested", "flaky", "test-tamper", "breaks-one", "noisy",
    "silent-change", "false-claim", "api-break", "new-dep", "probe-only",
]  # fmt: skip


@pytest.fixture(scope="module")
def provisioner(tmp_path_factory: pytest.TempPathFactory) -> HostProvisioner:
    return HostProvisioner(tmp_path_factory.mktemp("envs"))


def expectation(name: str) -> dict[str, Any]:
    return tomllib.loads((FIXTURES / f"{name}.toml").read_text(encoding="utf-8"))


def reproduce_fixture(
    name: str, root: Path, provisioner: HostProvisioner, **options: Any
) -> twosided.TwoSided:
    built = build_repo(ALL_SPECS[name], root / "repo")
    git = Git(built.path)
    base_sha = built.base_sha
    head_sha = built.head_shas[expectation(name)["fixture"]["head"]]
    analysis = analyse(git, base_sha, head_sha, root / "analysis")
    sides = []
    for side, sha in (("base", base_sha), ("head", head_sha)):
        tree = snapshot(git, sha, root / side / "snapshot")
        box = ProcessSandbox(root / side / "work", Limits(timeout_s=300))
        sides.append(Side(side, box, provisioner.provision(side, inspect_project(tree.root), box)))
    return twosided.reproduce(
        (sides[0], sides[1]),
        analysis.changes.changes,
        (analysis.base, analysis.head),
        selection.side_resolvers(git, base_sha, head_sha),
        **options,
    )


def evidence_of(result: twosided.TwoSided) -> list[str]:
    found = [f"test_outcome:{d.outcome_class}:{d.test}" for d in result.outcomes]
    found += [f"test_change:{c.change}:{c.test or c.file}" for c in result.test_changes]
    return sorted(found)


def missing_of(result: twosided.TwoSided) -> list[str]:
    items = [selection.no_covering_test(gap) for gap in result.gaps]
    items += [unstable_observation(d) for d in result.outcomes if not d.stable]
    items += result.problems()
    found = []
    for item in items:
        models.MissingRecordedPayload.model_validate(item)
        missing = item["missing"]
        for target in missing["targets"] or [{}]:
            name = target.get("symbol") or target.get("test") or ""
            found.append(f"{missing['reason']}:{name}")
    return sorted(found)


def without_timing(items: list[str]) -> list[str]:
    """An expectation without what the performance and behaviour passes add (``reproduce``
    neither times nor compares behaviour)."""
    later = (
        "perf_diff:", "perf_not_assessable:", "behaviour_diff:", "api_diff:", "dep_diff:",
        "probe_diff:",
    )  # fmt: skip
    return sorted(i for i in items if not i.startswith(later))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_each_fixture_gives_exactly_its_evidence(
    name: str, tmp_path: Path, provisioner: HostProvisioner
) -> None:
    expected = expectation(name)
    result = reproduce_fixture(name, tmp_path, provisioner)
    runs = "\n".join(
        f"{r.side} {r.label}: {r.run.results.outcomes()} {r.run.results.notes}" for r in result.runs
    )
    assert {s.test: list(s.reasons) for s in result.selected} == expected["selection"].get(
        "selected", {}
    ), runs
    assert evidence_of(result) == without_timing(expected["expected"]["evidence"]), runs
    assert missing_of(result) == without_timing(expected["expected"]["missing"]), runs
    for diff in result.outcomes:
        record = diff.evidence(RUN_ID)
        record["seq"] = 1
        models.Evidence.model_validate(record)
        models.DiffOutcomePayload.model_validate(diff.payload(record["id"]))
    for change in result.test_changes:
        record = change.evidence(RUN_ID)
        record["seq"] = 1
        models.Evidence.model_validate(record)
        models.DiffTestsPayload.model_validate(change.payload(record["id"]))


def test_a_flip_is_run_again_on_both_sides(tmp_path: Path, provisioner: HostProvisioner) -> None:
    result = reproduce_fixture("honest-fix", tmp_path, provisioner)
    labels = [(r.side, r.label) for r in result.runs]
    assert labels == [
        ("base", "A"),
        ("head", "head tests"),
        ("base", "A2"),
        ("head", "H"),
        ("base", "rerun 1"),
        ("head", "rerun 1"),
        ("base", "rerun 2"),
        ("head", "rerun 2"),
        ("base", "rerun 3"),
        ("head", "rerun 3"),
    ]
    for diff in result.outcomes:
        assert diff.base_reruns == ("failed",) * 3
        assert diff.head_reruns == ("passed",) * 3
        assert not diff.likely_flaky  # both tests ran the fixed function


def test_the_reverse_order_and_another_hash_seed(
    tmp_path: Path, provisioner: HostProvisioner
) -> None:
    result = reproduce_fixture("flaky", tmp_path, provisioner)
    a2 = next(r for r in result.runs if r.label == "A2")
    assert a2.tests == (
        "tests/test_counter.py::test_record_second",
        "tests/test_counter.py::test_record_first",
    )
    assert list(a2.run.results.tests) == list(a2.tests)  # run in the order asked for
    (flaky,) = [d for d in result.outcomes if d.outcome_class == "flaky"]
    assert (flaky.base, flaky.base_again, flaky.head) == ("passed", "failed", "passed")
    assert not flaky.base_reruns  # A and A2 disagreeing is enough: no reruns spent


def test_a_cached_base_map_runs_only_the_selected_tests(
    tmp_path: Path, provisioner: HostProvisioner
) -> None:
    cache = selection.MapCache(tmp_path / "maps")
    first = reproduce_fixture(
        "selection", tmp_path / "first", provisioner, cache=cache, cache_key="k"
    )
    second = reproduce_fixture(
        "selection", tmp_path / "second", provisioner, cache=cache, cache_key="k"
    )
    assert (first.map_cached, second.map_cached) == (False, True)
    a = next(r for r in second.runs if r.label == "A")
    assert set(a.tests) == {s.test for s in second.selected if s.test in second.base_map.tests}
    assert evidence_of(second) == evidence_of(first)
