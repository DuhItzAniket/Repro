"""Ground truth's automatic tiers (J02): SWE-bench's grading, and the tiers' decisions.

The containers are faked here: ``run`` is replaced by a function that returns the statuses a
scenario needs. The real runs (SWE-rebench ``pypa__twine-1309`` in its image) are in the phase
record.
"""

import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from gitrepo import Repo
from repro.agents.backend import AgentResult
from repro_bench import annotate, groundtruth, truth
from repro_bench.swe import Prediction
from repro_bench.truth import ERROR, FAILED, PASSED, SKIPPED, XFAIL, ContainerRun, Oracle

LOG = """\
============================= test session starts ==============================
collected 6 items

tests/test_a.py ....F.                                                    [100%]

=========================== short test summary info ============================
PASSED tests/test_a.py::test_one
PASSED tests/test_a.py::test_param[599-Unknown Status]
XFAIL tests/test_a.py::test_known - not yet
SKIPPED [1] tests/test_a.py:20: needs a network
SKIPPED tests/test_a.py::test_skipped
FAILED tests/test_a.py::test_two - AssertionError: assert 1 == 2
ERROR tests/test_a.py::test_three
========================= 1 failed, 4 passed in 0.52s ==========================
"""


def record(**changes: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "instance_id": "o__r-1",
        "docker_image": "swerebench/sweb.eval.x86_64.o_1776_r-1:latest",
        "base_commit": "a" * 40,
        "patch": "diff --git a/src/m.py b/src/m.py\n",
        "test_patch": "diff --git a/tests/test_a.py b/tests/test_a.py\n",
        "FAIL_TO_PASS": '["tests/test_a.py::test_param[599-Unknown"]',
        "PASS_TO_PASS": ["tests/test_a.py::test_one"],
        "install_config": {
            "test_cmd": "pytest --no-header -rA -p no:cacheprovider tests/test_a.py",
            "log_parser": "parse_log_pytest",
        },
    }
    return found | changes


def test_pytest_statuses_are_read_as_swe_bench_reads_them() -> None:
    assert truth.parse_pytest(LOG) == {
        "tests/test_a.py::test_one": PASSED,
        "tests/test_a.py::test_param[599-Unknown": PASSED,  # cut at the space, as SWE-bench does
        "tests/test_a.py::test_known": XFAIL,
        "tests/test_a.py::test_skipped": SKIPPED,  # "SKIPPED [1] ..." is a count, not a test
        "tests/test_a.py::test_two": FAILED,
        "tests/test_a.py::test_three": ERROR,
    }


@pytest.mark.parametrize(
    ("f2p", "p2p", "resolved"),
    [
        (["tests/test_a.py::test_param[599-Unknown"], ["tests/test_a.py::test_one"], "FULL"),
        (["tests/test_a.py::test_known"], ["tests/test_a.py::test_skipped"], "FULL"),  # XFAIL; skip
        (["tests/test_a.py::test_skipped"], [], "NO"),  # a skipped FAIL_TO_PASS does not resolve
        (["tests/test_a.py::test_one", "tests/test_a.py::test_two"], [], "PARTIAL"),
        (["tests/test_a.py::test_one"], ["tests/test_a.py::test_three"], "NO"),
        (["tests/test_a.py::test_missing"], [], "NO"),  # missing from the log: failed
    ],
)
def test_resolution_follows_swe_bench(f2p: list[str], p2p: list[str], resolved: str) -> None:
    assert truth.grade(truth.parse_pytest(LOG), f2p, p2p).resolved == resolved


def test_an_id_cut_inside_its_brackets_matches_when_the_candidates_agree() -> None:
    statuses = {"t.py::f[a b]": PASSED, "t.py::f[a c]": PASSED, "t.py::g[x y]": PASSED}
    statuses |= {"t.py::g[x z]": FAILED}
    assert truth.passed("t.py::f[a", statuses)
    assert not truth.passed("t.py::g[x", statuses)  # they disagree: no match, so failed
    assert not truth.passed("t.py::f", statuses)  # brackets balanced: exact IDs only


def test_the_task_reads_its_test_command_and_full_suite() -> None:
    oracle = Oracle.from_record(record())
    assert oracle.test_files == ("tests/test_a.py",)
    assert oracle.fail_to_pass == ("tests/test_a.py::test_param[599-Unknown",)
    assert oracle.full_suite_cmd() == "pytest --no-header -rA -p no:cacheprovider"
    pinned = "swerebench/x@sha256:" + "0" * 64
    assert Oracle.from_record(record(), image=pinned).image == pinned


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"install_config": None}, "no install_config.test_cmd"),
        ({"install_config": '{"test_cmd": "./runtests.py", "log_parser": "parse_log_django"}'},
         "not pytest's"),
        ({"docker_image": None}, "no environment image"),
        ({"FAIL_TO_PASS": "[1, 2]"}, "not a list of test IDs"),
    ],
)  # fmt: skip
def test_a_task_the_tiers_cannot_judge_is_named(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(truth.OracleError, match=message):
        Oracle.from_record(record(**changes))


def test_the_container_script_carries_the_patches_and_mounts_nothing() -> None:
    oracle = Oracle.from_record(record())
    text = truth.script(oracle, ["diff one\n", "diff two\n"], "pytest -rA", repeat=3)
    assert "base64 -d > /tmp/repro-truth/0.diff" in text
    assert "base64 -d > /tmp/repro-truth/1.diff" in text
    assert "diff one" not in text  # encoded: no patch text is ever shell syntax
    assert f"git checkout -q {'a' * 40} -- tests/test_a.py" in text
    assert "seq 1 3" in text


def test_a_run_is_read_back_per_repetition(monkeypatch: pytest.MonkeyPatch) -> None:
    oracle = Oracle.from_record(record())
    output = "".join(
        f">>>>> Run {n}\n{truth.START}\n{LOG}>>>>> Exit 1\n{truth.END}\n" for n in (1, 2)
    )
    seen: list[list[str]] = []

    def fake(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv)
        assert b"base64 -d" in kwargs["input"]
        return subprocess.CompletedProcess(argv, 0, output.encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake)
    done = truth.run_tests(oracle, ["p\n"], "pytest -rA", repeat=2)
    assert done.valid
    assert [code for _, code in done.runs] == [1, 1]
    assert done.statuses["tests/test_a.py::test_two"] == FAILED
    (argv,) = seen
    assert argv[argv.index("--network") + 1] == "none"
    assert "-v" not in argv  # nothing from the host
    assert "--mount" not in argv


@pytest.mark.parametrize(
    ("log", "problem"),
    [
        ("collected 0 items\n", "no test result"),
        ("PASSED t.py::a\n============ 1 passed in 0.1s ============\n", "exit status 2"),
    ],
)
def test_an_invalid_result_is_not_a_pass(
    monkeypatch: pytest.MonkeyPatch, log: str, problem: str
) -> None:
    output = f">>>>> Run 1\n{truth.START}\n{log}>>>>> Exit 2\n{truth.END}\n"
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 0, output.encode())
    )
    done = truth.run_tests(Oracle.from_record(record()), [], "pytest")
    assert not done.valid
    assert problem in done.problem


def test_a_patch_that_does_not_apply_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    output = ">>>>> Patch 0 failed\nerror: corrupt patch\n"
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **_: subprocess.CompletedProcess(argv, 3, output.encode())
    )
    done = truth.run_tests(Oracle.from_record(record()), ["x"], "pytest")
    assert (done.applied, done.problem) == (False, "patch 0 does not apply")


class Scenario:
    """A fake container: statuses by which patch is first and whether the command is the hidden
    tests' (the task's own command) or the full suite's."""

    def __init__(
        self,
        hidden: Mapping[str, str],
        gold_full: Mapping[str, str],
        full: Mapping[str, str],
        confirm: Mapping[str, str] | None = None,
    ) -> None:
        self.hidden, self.gold_full, self.full = hidden, gold_full, full
        self.confirm = confirm
        self.calls: list[tuple[str, str, int]] = []

    def __call__(
        self, oracle: Oracle, patches: Sequence[str], command: str, repeat: int = 1
    ) -> ContainerRun:
        gold = patches[0] == oracle.gold_patch
        self.calls.append(("gold" if gold else "candidate", command, repeat))
        if command == oracle.test_cmd:
            statuses = self.hidden
        elif repeat > 1:  # the reruns that confirm a regression
            statuses = self.gold_full if gold else (self.confirm or self.full)
        else:
            statuses = self.gold_full if gold else self.full
        return ContainerRun(True, tuple((statuses, 0) for _ in range(repeat)), 0.1)


RESOLVED = {"tests/test_a.py::test_param[599-Unknown Status]": PASSED,
            "tests/test_a.py::test_one": PASSED}  # fmt: skip


def test_tier_a_flags_a_patch_that_does_not_resolve_the_task() -> None:
    oracle = Oracle.from_record(record())
    hidden = {"tests/test_a.py::test_one": PASSED}  # the FAIL_TO_PASS test is missing
    verdict, _ = truth.tier_a(oracle, "candidate", run=Scenario(hidden, {}, {}))
    assert verdict.tier == "INCORRECT_auto"
    assert verdict.evidence["fail_to_pass_failed"] == ["tests/test_a.py::test_param[599-Unknown"]


def test_tier_a_flags_a_regression_the_reruns_confirm() -> None:
    oracle = Oracle.from_record(record())
    full = {"tests/test_b.py::test_kept": PASSED, "tests/test_b.py::test_broken": PASSED}
    mine = full | {"tests/test_b.py::test_broken": FAILED}
    scenario = Scenario(RESOLVED, full, mine)
    verdict, gold_full = truth.tier_a(oracle, "candidate", run=scenario)
    assert verdict.tier == "INCORRECT_auto"
    assert verdict.evidence["full_suite_regressions"] == ["tests/test_b.py::test_broken"]
    assert gold_full is not None
    assert gold_full.statuses == full
    # The gold patch's full suite is reused for the task's next patch.
    again, _ = truth.tier_a(
        oracle, "another", gold_full=gold_full, run=Scenario(RESOLVED, {}, full)
    )
    assert again.tier == "PLAUSIBLE"


def test_tier_a_drops_a_regression_the_reruns_do_not_confirm() -> None:
    oracle = Oracle.from_record(record())
    full = {"tests/test_b.py::test_flaky": PASSED}
    scenario = Scenario(RESOLVED, full, {"tests/test_b.py::test_flaky": FAILED}, confirm=full)
    verdict, _ = truth.tier_a(oracle, "candidate", run=scenario)
    assert verdict.tier == "PLAUSIBLE"
    assert verdict.evidence["full_suite_flaky"] == ["tests/test_b.py::test_flaky"]
    assert ("candidate", "pytest --no-header -rA -p no:cacheprovider tests/test_b.py::test_flaky",
            truth.CONFIRM_RUNS) in scenario.calls  # fmt: skip


def test_a_run_with_no_valid_result_goes_to_people() -> None:
    oracle = Oracle.from_record(record())

    def broken(
        oracle: Oracle, patches: Sequence[str], command: str, repeat: int = 1
    ) -> ContainerRun:
        return ContainerRun(True, (), 1.0, "took over 1800 s")

    verdict, _ = truth.tier_a(oracle, "candidate", run=broken)
    assert verdict.tier == "NEEDS_REVIEW"


def test_tier_b_counts_only_stable_tests() -> None:
    oracle = Oracle.from_record(record())
    tests = "diff --git a/tests/test_d.py b/tests/test_d.py\n"
    runs = {
        "gold": [{"d::same": PASSED, "d::differs": PASSED, "d::flaky": PASSED}] * 2
        + [{"d::same": PASSED, "d::differs": PASSED, "d::flaky": FAILED}],
        "candidate": [{"d::same": PASSED, "d::differs": FAILED, "d::flaky": PASSED}] * 3,
    }

    def fake(oracle: Oracle, patches: Sequence[str], command: str, repeat: int = 1) -> ContainerRun:
        side = "gold" if patches[0] == oracle.gold_patch else "candidate"
        assert command.endswith("tests/test_d.py")
        assert repeat == 3
        return ContainerRun(True, tuple((s, 0) for s in runs[side]), 0.1)

    found = truth.differential(oracle, "candidate", tests, source="generated", reruns=3, run=fake)
    assert (found.divergent, found.unstable, found.stable) == (("d::differs",), ("d::flaky",), 2)
    assert truth.tier_b([found]).tier == "DIVERGENT"
    calm = truth.Divergence("generated", (), (), 4)
    assert truth.tier_b([calm]).tier == "CORRECT_auto"
    assert truth.tier_b([truth.Divergence("generated", (), ("x",), 0)]).tier == "NEEDS_REVIEW"


def test_utboost_tests_must_be_the_same_tasks() -> None:
    oracle = Oracle.from_record(record())
    same = {"instance_id": "o__r-1", "base_commit": "a" * 40, "test_patch": "diff --git x"}
    assert truth.utboost_patch(oracle, same) == "diff --git x"
    with pytest.raises(truth.OracleError, match="not o__r-1's"):
        truth.utboost_patch(oracle, same | {"base_commit": "b" * 40})


def test_the_files_a_diff_touches(tmp_path: Any) -> None:
    repo = Repo(tmp_path / "r")
    base = repo.commit({"a.py": "x = 1\n", "t/test_a.py": "def test(): pass\n"})
    head = repo.commit({"a.py": "x = 2\n", "t/test_b.py": "def test(): pass\n"})
    assert truth.changed_files(repo.git("diff", base, head)) == ("a.py", "t/test_b.py")


# -- the pipeline --------------------------------------------------------------------------------


class Written:
    """A model that writes one test module, for tier B's generated tests."""

    async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
        return AgentResult("ok", {"module": "def test_d():\n    assert True\n"})


def test_a_plausible_patch_goes_through_both_tiers_with_its_evidence() -> None:
    oracle = Oracle.from_record(record())
    prediction = Prediction("o__r-1", "agent-x", "diff --git a/src/m.py b/src/m.py\n+x\n")
    full = {"tests/test_b.py::test_kept": PASSED}

    def run(oracle: Oracle, patches: Sequence[str], command: str, repeat: int = 1) -> ContainerRun:
        if command == oracle.test_cmd:
            return ContainerRun(True, ((RESOLVED, 0),), 0.1)
        if "test_repro_difftest.py" in command:
            outcome = {"tests/test_repro_difftest.py::test_d": PASSED}
            return ContainerRun(True, tuple((outcome, 0) for _ in range(repeat)), 0.1)
        return ContainerRun(True, ((full, 0),), 0.1)

    utboost = {"instance_id": "o__r-1", "base_commit": "a" * 40,
               "test_patch": "diff --git a/tests/test_aug.py b/tests/test_aug.py\n"}  # fmt: skip
    row, gold_full = groundtruth.judge(
        oracle, prediction, "the issue", gold_full=None, utboost=None, backend=Written(),
        model="m", reruns=2, run=run,
    )  # fmt: skip
    assert gold_full is not None
    assert row["item"] == f"o__r-1@{prediction.patch_sha256[:12]}"
    assert row["tier_a"]["tier"] == "PLAUSIBLE"
    assert row["tier_b"]["tier"] == "CORRECT_auto"
    assert (row["auto_label"], row["needs_people"]) == ("CORRECT_auto", False)
    # With UTBoost's tests for the task, they run too, beside no written ones.
    row, _ = groundtruth.judge(
        oracle, prediction, "the issue", gold_full=gold_full, utboost=utboost, backend=None,
        model="m", reruns=2, run=run,
    )  # fmt: skip
    assert row["tier_b"]["evidence"]["sources"] == ["utboost"]
    assert row["auto_label"] == "CORRECT_auto"


def test_the_batch_holds_unsettled_patches_and_audits_of_each_automatic_label() -> None:
    task = record() | {"repo": "o/r", "problem_statement": "issue"}
    rows: list[dict[str, Any]] = [
        {"item": f"o__r-1@{n:012d}", "instance_id": "o__r-1", "tier_a": {"tier": tier},
         "auto_label": label, "needs_people": label is None}
        for n, (tier, label) in enumerate(
            [("PLAUSIBLE", None)] + [("PLAUSIBLE", "CORRECT_auto")] * 10
            + [("INCORRECT_auto", "INCORRECT_auto")] * 10
        )
    ]  # fmt: skip
    patches = {str(row["item"]): "diff" for row in rows}
    items = groundtruth.batch(rows, {"o__r-1": task}, patches, seed="s")
    assert len(items) == 1 + 2 + 2  # the unsettled one, then round(10 x 0.15) of each label
    assert rows[0]["item"] in {item["item"] for item in items}
    assert annotate.blinded(items[0])  # every item is one an annotator may see
