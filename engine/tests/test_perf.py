"""The performance pass's statistics (D07), and an A/A run of real tests.

Reference values come from SciPy 1.18.1 (``mannwhitneyu(..., method="asymptotic")``) and
statsmodels (``multipletests(..., method="fdr_bh")``), computed once outside the project: they
are not dependencies. The BCa interval was compared with ``scipy.stats.bootstrap(...,
method="BCa")`` the same way and agrees within Monte Carlo error (phase record D07).
"""
# ruff: noqa: S311 - seeded generators for test data, not secrets

import random
import re
import shutil
from pathlib import Path

import pytest

from fixtures.repo_builder import build_repo
from fixtures.specs import PERF_REGRESS
from repro.gitops import Git, snapshot
from repro.ids import new_run_id
from repro.provision import HostProvisioner, inspect_project
from repro.runner import perf
from repro.runner.sides import Side
from repro.sandbox import Limits, ProcessSandbox
from repro_events import models


def test_runs_alternate_in_abba_blocks() -> None:
    assert perf.abba(2) == ["base", "head", "head", "base"] * 2


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        (list(range(1, 11)), list(range(11, 21)), 0.00018267179110955002),
        ([1, 2, 2, 3, 3, 3, 4, 5, 5, 6], [2, 2, 3, 3, 3, 4, 4, 5, 6, 7], 0.5627113600645403),
    ],
)
def test_mann_whitney_matches_scipy(base: list[float], head: list[float], expected: float) -> None:
    assert perf.mann_whitney_p(base, head) == pytest.approx(expected, rel=1e-12)


def test_benjamini_hochberg_matches_statsmodels() -> None:
    adjusted = perf.benjamini_hochberg([0.01, 0.04, 0.03, 0.2, 0.5])
    assert adjusted == pytest.approx([0.05, 0.2 / 3, 0.2 / 3, 0.25, 0.5])


def noisy(level: float, seed: int, n: int = 10) -> list[float]:
    gen = random.Random(seed)
    return [level * (1 + gen.gauss(0, 0.03)) for _ in range(n)]


def test_the_interval_brackets_the_ratio() -> None:
    same = perf.bca_ratio_interval(noisy(0.02, 1), noisy(0.02, 2), rng=random.Random(0))
    assert same[1] < 1 < same[2]
    slower = perf.bca_ratio_interval(noisy(0.02, 1), noisy(0.04, 2), rng=random.Random(0))
    assert 1.8 < slower[1] < slower[0] < slower[2] < 2.2


def samples(test: str, base: float, head: float, seed: int) -> perf.Samples:
    return perf.Samples(test, tuple(noisy(base, seed)), tuple(noisy(head, seed + 1)))


def test_verdicts() -> None:
    found, too_fast = perf.assess(
        [
            samples("t.py::slower", 0.02, 0.05, 1),
            samples("t.py::faster", 0.05, 0.02, 3),
            samples("t.py::same", 0.02, 0.02, 5),
            samples("t.py::slightly", 0.02, 0.0205, 7),  # 2.5 %: under the 10 % floor
            samples("t.py::tiny", 0.0001, 0.0002, 9),
        ],
        resamples=2000,
    )
    verdicts = {d.test: d.verdict for d in found}
    assert verdicts == {
        "t.py::slower": "regression",
        "t.py::faster": "improvement",
        "t.py::same": "no_change",
        "t.py::slightly": "no_change",
    }
    assert too_fast == ["t.py::tiny"]
    assert {d.noise_floor for d in found} == {perf.MIN_EFFECT}
    run_id = new_run_id()
    for diff in found:
        record = diff.evidence(run_id)
        models.Evidence.model_validate({**record, "seq": 1})
        models.DiffPerfPayload.model_validate(diff.payload(record["id"]))
    models.MissingRecordedPayload.model_validate(perf.not_assessable(too_fast))
    slower = next(d for d in found if d.test == "t.py::slower")
    pattern = (
        r"regression: t\.py::slower: head \d+% slower \(95% CI \+\d+% to \+\d+%\), noise floor 10%"
    )
    assert re.fullmatch(pattern, slower.summary()), slower.summary()


def test_the_aa_spread_raises_the_floor() -> None:
    wobbly = perf.Samples("t.py::w", (0.02, 0.03) * 5, (0.02,) * 10)  # first vs last: +50 %
    assert perf.aa_noise([wobbly]) == pytest.approx(0.5)
    found, _ = perf.assess([wobbly], resamples=500)
    assert found[0].noise_floor == pytest.approx(0.5)


def test_an_aa_run_of_real_tests_shows_no_change(tmp_path: Path) -> None:
    """Roadmap D07: "An A/A run on an unchanged repo produces no perf diff over 20 repetitions."
    Base against a second copy of base, interleaved, twenty runs a side."""
    built = build_repo(PERF_REGRESS, tmp_path / "repo")
    git = Git(built.path)
    provisioner = HostProvisioner(tmp_path / "envs")
    sides = []
    for name in ("base", "head"):  # both are base's commit
        tree = snapshot(git, built.base_sha, tmp_path / name / "snapshot")
        box = ProcessSandbox(tmp_path / name / "work", Limits(timeout_s=300))
        sides.append(Side(name, box, provisioner.provision(name, inspect_project(tree.root), box)))
    tests = ["tests/test_tags.py::test_unique_tags", "tests/test_tags.py::test_report_is_sorted"]
    timed, runs = perf.time_tests(sides[0], sides[1], tests, repetitions=20)
    assert len(runs) == 40
    assert all(len(s.base) == 20 and len(s.head) == 20 for s in timed)
    found, too_fast = perf.assess(timed)
    assert too_fast == []
    assert {d.test: d.verdict for d in found} == dict.fromkeys(tests, "no_change"), [
        d.summary() for d in found
    ]
    shutil.rmtree(tmp_path / "envs", ignore_errors=True)
