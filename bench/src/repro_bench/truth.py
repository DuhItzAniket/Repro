"""Ground truth for an agent's patch, from the task's own tests (J02).

The protocol's procedure (``docs/paper/EVALUATION_PROTOCOL.md`` §4) labels each (task, patch)
pair in two automatic tiers, then by people:

- **Tier A.** The task's hidden tests (the test patch's FAIL_TO_PASS and PASS_TO_PASS) and the
  project's full test suite, in the task's environment image. A patch that does not resolve the
  task, or that breaks a test the gold patch keeps passing, is ``INCORRECT_auto``. PatchDiff
  found 7.8% of "resolved" patches fail the full developer suite [research/06 §4], so the full
  suite is run, not only the hidden tests.
- **Tier B**, for a patch that passes tier A (*plausible*): other tests run against the gold
  patch and the candidate, each many times; a test whose outcome is stable on both sides and
  differs is a divergence. The tests come from UTBoost's augmented test patches where they
  exist [UTBoost, HF ``Bertsekas/SWE-Bench_Verified_UTBoost``, MIT] or are written for the task
  (PatchDiff-style differential tests [Wang, Pradel, Liu, ICSE 2026]). No divergence:
  ``CORRECT_auto``; a divergence goes to the annotators.

**Grading is SWE-bench's**, reimplemented with the same semantics [SWE-bench
``swebench/harness/grading.py`` and ``log_parsers/python.py`` at 02e7a74, 2026-09-02, MIT]:
pytest's ``-rA`` summary lines give each test's status; a FAIL_TO_PASS test must pass (PASSED or
XFAIL), a PASS_TO_PASS test must pass or be skipped; a test missing from the log counts as
failed; an expected ID cut short inside its brackets matches the IDs it starts when they agree;
a log with no result and no sign the suite ran, or a non-zero exit with no failure, is invalid.

**Where it runs.** In the task's image (SWE-rebench's ``docker_image``), as SWE-bench's
evaluation does: the repository at base in ``/testbed`` with its environment installed. Each run
is a fresh container with no network; the patches go in on standard input, base64-encoded in the
script, and nothing is mounted from the host. The test command is the task's own
(``install_config.test_cmd``); the full suite is that command without the test patch's files.
"""

import base64
import json
import re
import shlex
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol

PASSED: Final = "PASSED"
FAILED: Final = "FAILED"
SKIPPED: Final = "SKIPPED"
ERROR: Final = "ERROR"
XFAIL: Final = "XFAIL"
STATUSES: Final = (FAILED, PASSED, SKIPPED, ERROR, XFAIL)
#: pytest's ``SKIPPED [N] path:line: reason`` summary, where ``[N]`` is not a test.
_SKIP_COUNT: Final = re.compile(r"^\[\d+\]$")
#: A pytest run's last line: ``==== 3 passed, 1 failed in 0.52s ====``.
_SUITE_RAN: Final = re.compile(r"^=+ .*\bin [\d.]+s(?: \([\d:]+\))? =+$", re.M)
_DIFF_FILE: Final = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)
START: Final = ">>>>> Start Test Output"
END: Final = ">>>>> End Test Output"
_EXIT: Final = re.compile(r"^>>>>> Exit (\d+)$", re.M)
_RUN: Final = re.compile(r"^>>>>> Run (\d+)$", re.M)
#: In the container, never on the host.
WORK: Final = "/tmp/repro-truth"  # noqa: S108
DEFAULT_TIMEOUT_S: Final = 1800.0
#: Reruns of each side for tier B, as PatchDiff did, to drop flaky tests (protocol §4).
RERUNS: Final = 20
CONFIRM_RUNS: Final = 3

Tier = Literal["INCORRECT_auto", "PLAUSIBLE", "CORRECT_auto", "DIVERGENT", "NEEDS_REVIEW"]


class OracleError(Exception):
    """A task the automatic tiers cannot judge; the message says why."""


# -- the task ------------------------------------------------------------------------------------


def _list(value: Any) -> tuple[str, ...]:
    found = json.loads(value) if isinstance(value, str) else value
    if not isinstance(found, list) or not all(isinstance(item, str) for item in found):
        raise OracleError("a test list is not a list of test IDs")
    return tuple(found)


def changed_files(diff: str) -> tuple[str, ...]:
    """The files a diff touches (its ``diff --git`` headers), in order."""
    return tuple(dict.fromkeys(b for _, b in _DIFF_FILE.findall(diff)))


@dataclass(frozen=True)
class Oracle:
    """What the dataset knows about one task: never a system's input (J01's contract)."""

    instance_id: str
    image: str
    base_commit: str
    gold_patch: str
    test_patch: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    test_cmd: str

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, image: str | None = None) -> "Oracle":
        config = record.get("install_config")
        config = json.loads(config) if isinstance(config, str) else config
        if not isinstance(config, dict) or not isinstance(config.get("test_cmd"), str):
            raise OracleError(f"{record.get('instance_id')}: no install_config.test_cmd")
        parser = config.get("log_parser")
        if parser != "parse_log_pytest":
            raise OracleError(f"{record['instance_id']}: log parser {parser!r} is not pytest's")
        chosen = image or record.get("docker_image")
        if not isinstance(chosen, str) or not chosen:
            raise OracleError(f"{record['instance_id']}: no environment image")
        return cls(
            str(record["instance_id"]),
            chosen,
            str(record["base_commit"]),
            str(record["patch"]),
            str(record["test_patch"]),
            _list(record["FAIL_TO_PASS"]),
            _list(record["PASS_TO_PASS"]),
            config["test_cmd"],
        )

    @property
    def test_files(self) -> tuple[str, ...]:
        return changed_files(self.test_patch)

    def full_suite_cmd(self) -> str:
        """The task's test command without the test patch's files: the project's whole suite."""
        files = set(self.test_files)
        kept = [
            token
            for token in shlex.split(self.test_cmd)
            if token not in files and token.partition("::")[0] not in files
        ]
        return shlex.join(kept)


# -- reading pytest's output ---------------------------------------------------------------------


def parse_pytest(log: str) -> dict[str, str]:
    """Each test's status from pytest's ``-rA`` summary (SWE-bench's ``parse_log_pytest``)."""
    found: dict[str, str] = {}
    for line in log.split("\n"):
        if not line.startswith(STATUSES):
            continue
        parts = (line.replace(" - ", " ") if line.startswith(FAILED) else line).split()
        if len(parts) <= 1:
            continue
        if parts[0] == SKIPPED and _SKIP_COUNT.match(parts[1]):
            continue
        found[parts[1]] = parts[0]
    return found


def _key(case: str, statuses: Mapping[str, str]) -> str | None:
    """The status map's key for ``case``; an ID cut short inside its brackets matches the IDs
    it starts when they agree on passing (SWE-bench's ``_resolve_case``)."""
    if case in statuses:
        return case
    if case.count("[") > case.count("]"):
        matches = [key for key in statuses if key.startswith(case)]
        if matches and len({statuses[key] in (PASSED, XFAIL) for key in matches}) == 1:
            return matches[0]
    return None


def passed(case: str, statuses: Mapping[str, str]) -> bool:
    key = _key(case, statuses)
    return key is not None and statuses[key] in (PASSED, XFAIL)


def maintained(case: str, statuses: Mapping[str, str]) -> bool:
    """PASS_TO_PASS: passing, or skipped (a skip is not a regression)."""
    key = _key(case, statuses)
    return passed(case, statuses) or (key is not None and statuses[key] == SKIPPED)


@dataclass(frozen=True)
class Grade:
    resolved: Literal["FULL", "PARTIAL", "NO"]
    fail_to_pass_failed: tuple[str, ...]
    pass_to_pass_failed: tuple[str, ...]


def grade(
    statuses: Mapping[str, str], fail_to_pass: Sequence[str], pass_to_pass: Sequence[str]
) -> Grade:
    """SWE-bench's resolution: every FAIL_TO_PASS passes and every PASS_TO_PASS is kept."""
    f2p_failed = tuple(case for case in fail_to_pass if not passed(case, statuses))
    p2p_failed = tuple(case for case in pass_to_pass if not maintained(case, statuses))
    f2p_rate = 1.0 if not fail_to_pass else 1 - len(f2p_failed) / len(fail_to_pass)
    if not f2p_failed and not p2p_failed:
        resolved: Literal["FULL", "PARTIAL", "NO"] = "FULL"
    elif 0 < f2p_rate < 1 and not p2p_failed:
        resolved = "PARTIAL"
    else:
        resolved = "NO"
    return Grade(resolved, f2p_failed, p2p_failed)


# -- running tests in the task's image -----------------------------------------------------------


@dataclass(frozen=True)
class ContainerRun:
    """One container's run of a test command, possibly several times over."""

    applied: bool
    #: Each repetition's statuses, in order, with its exit code.
    runs: tuple[tuple[Mapping[str, str], int | None], ...]
    seconds: float
    problem: str = ""  # why there is no valid result, when there is none

    @property
    def statuses(self) -> Mapping[str, str]:
        return self.runs[0][0] if self.runs else {}

    @property
    def valid(self) -> bool:
        return self.applied and not self.problem


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class Target(Protocol):
    """Where tests run: a task's image, its base commit, and the files reset to base first."""

    @property
    def image(self) -> str: ...
    @property
    def base_commit(self) -> str: ...
    @property
    def test_files(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class Environment:
    """A task's image and base commit alone: what a system under evaluation may run in (J03's
    CI-only baseline), with nothing of the ground truth."""

    image: str
    base_commit: str
    test_files: tuple[str, ...] = ()


def script(target: Target, patches: Sequence[str], command: str, repeat: int = 1) -> str:
    """The bash script a container runs: reset the test files, apply the patches in order (the
    candidate first, then test patches), then run ``command`` ``repeat`` times."""
    lines = [
        "set -u",
        "cd /testbed",
        "git config --global --add safe.directory /testbed",
        f"mkdir -p {WORK}",
    ]
    if target.test_files:
        files = " ".join(shlex.quote(f) for f in target.test_files)
        lines.append(
            f"git checkout -q {shlex.quote(target.base_commit)} -- {files} 2>/dev/null || true"
        )
    for number, patch in enumerate(patches):
        diff = f"{WORK}/{number}.diff"
        lines += [
            f"echo {_b64(patch)} | base64 -d > {diff}",
            f"if ! git apply -v {diff} >{WORK}/apply.log 2>&1; then",
            f"  if ! patch --batch --fuzz=5 -p1 -i {diff} >>{WORK}/apply.log 2>&1; then",
            f'    echo ">>>>> Patch {number} failed"; tail -5 {WORK}/apply.log; exit 3',
            "  fi",
            "fi",
        ]
    lines += [
        f"for run in $(seq 1 {repeat}); do",
        '  echo ">>>>> Run $run"',
        f'  echo "{START}"',
        f"  {command}",
        '  echo ">>>>> Exit $?"',
        f'  echo "{END}"',
        "done",
    ]
    return "\n".join(lines) + "\n"


def _repetitions(log: str) -> list[tuple[dict[str, str], int | None]]:
    found = []
    for chunk in _RUN.split(log)[2::2]:
        body = chunk.split(START, 1)[-1].split(END, 1)[0]
        exit_code = _EXIT.search(chunk)
        found.append((parse_pytest(body), int(exit_code[1]) if exit_code else None))
    return found


def _problem(statuses: Mapping[str, str], exit_code: int | None, body: str) -> str:
    """Why a repetition's result is not valid (SWE-bench's checks), or ``""``."""
    if not statuses and not _SUITE_RAN.search(body):
        return "no test result, and no sign the suite ran"
    if exit_code not in (None, 0) and not any(s in (FAILED, ERROR) for s in statuses.values()):
        return f"exit status {exit_code} with no failing test reported"
    return ""


def run_tests(
    target: Target,
    patches: Sequence[str],
    command: str,
    *,
    repeat: int = 1,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    docker: str = "docker",
    memory: str = "4g",
) -> ContainerRun:
    """Runs ``command`` in a fresh container of ``target``'s image, with no network."""
    name = f"repro-truth-{uuid.uuid4().hex[:12]}"
    argv = [
        docker, "run", "--rm", "-i", "--name", name, "--network", "none",
        "--memory", memory, "--pids-limit", "4096", "--entrypoint", "bash", target.image, "-s",
    ]  # fmt: skip
    started = time.monotonic()
    try:
        done = subprocess.run(  # noqa: S603 - docker, with the task's image and our script
            argv,
            input=script(target, patches, command, repeat).encode("utf-8"),
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "rm", "-f", name], capture_output=True, check=False, timeout=120)  # noqa: S603
        return ContainerRun(True, (), time.monotonic() - started, f"took over {timeout_s:g} s")
    seconds = round(time.monotonic() - started, 1)
    log = done.stdout.decode("utf-8", "replace")
    failed = re.search(r"^>>>>> Patch (\d+) failed$", log, re.M)
    if failed:
        return ContainerRun(False, (), seconds, f"patch {failed[1]} does not apply")
    runs = _repetitions(log)
    if not runs:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        return ContainerRun(
            True, (), seconds, f"no run: {said[0][:200] if said else done.returncode}"
        )
    bodies = [c.split(START, 1)[-1].split(END, 1)[0] for c in _RUN.split(log)[2::2]]
    problem = next(
        (p for (s, e), body in zip(runs, bodies, strict=True) if (p := _problem(s, e, body))), ""
    )
    return ContainerRun(True, tuple(runs), seconds, problem)


# -- the tiers -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """An automatic tier's label, and the evidence for it."""

    tier: Tier
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


def regressions(gold: Mapping[str, str], candidate: Mapping[str, str]) -> list[str]:
    """Tests the gold patch keeps passing that the candidate does not (failed or missing)."""
    return sorted(
        test
        for test, status in gold.items()
        if status in (PASSED, XFAIL) and not passed(test, candidate)
    )


def _rerunnable(tests: Iterable[str]) -> list[str]:
    """Node IDs pytest can be given again: an ID cut at a space falls back to its file."""
    return sorted({t if t.count("[") == t.count("]") else t.partition("::")[0] for t in tests})


def tier_a(  # noqa: PLR0911 - one return per way tier A can end
    oracle: Oracle,
    candidate: str,
    *,
    gold_full: ContainerRun | None = None,
    run: Any = run_tests,
) -> tuple[Verdict, ContainerRun | None]:
    """Tier A for ``candidate``; also returns the gold patch's full-suite run, to reuse for the
    task's other patches."""
    hidden = run(oracle, [candidate, oracle.test_patch], oracle.test_cmd)
    if not hidden.applied:
        return Verdict(
            "INCORRECT_auto", f"the candidate does not apply: {hidden.problem}"
        ), gold_full
    if not hidden.valid:
        return Verdict(
            "NEEDS_REVIEW", f"the hidden tests gave no valid result: {hidden.problem}"
        ), gold_full
    graded = grade(hidden.statuses, oracle.fail_to_pass, oracle.pass_to_pass)
    evidence: dict[str, Any] = {
        "resolved": graded.resolved,
        "fail_to_pass_failed": list(graded.fail_to_pass_failed),
        "pass_to_pass_failed": list(graded.pass_to_pass_failed),
    }
    if graded.resolved != "FULL":
        return Verdict("INCORRECT_auto", "the hidden tests do not pass", evidence), gold_full
    full_cmd = oracle.full_suite_cmd()
    if gold_full is None:
        gold_full = run(oracle, [oracle.gold_patch, oracle.test_patch], full_cmd)
    if not gold_full.valid:
        evidence["full_suite"] = (
            f"the gold patch's full suite gave no valid result: {gold_full.problem}"
        )
        return Verdict("NEEDS_REVIEW", "the full suite could not be compared", evidence), gold_full
    mine = run(oracle, [candidate, oracle.test_patch], full_cmd)
    if not mine.valid:
        evidence["full_suite"] = f"the candidate's full suite gave no valid result: {mine.problem}"
        return Verdict("NEEDS_REVIEW", "the full suite could not be compared", evidence), gold_full
    broken = regressions(gold_full.statuses, mine.statuses)
    if broken:
        confirmed = _confirm(oracle, candidate, broken, run)
        evidence["full_suite_regressions"] = confirmed
        evidence["full_suite_flaky"] = sorted(set(broken) - set(confirmed))
        if confirmed:
            return Verdict(
                "INCORRECT_auto",
                "the candidate breaks tests the gold patch keeps passing",
                evidence,
            ), gold_full
    evidence["full_suite_tests"] = len(gold_full.statuses)
    return Verdict("PLAUSIBLE", "resolves the task and keeps the full suite", evidence), gold_full


def _confirm(oracle: Oracle, candidate: str, broken: Sequence[str], run: Any) -> list[str]:
    """The regressions that hold over ``CONFIRM_RUNS`` reruns of both sides: pass with gold
    every time, fail with the candidate every time."""
    command = f"{oracle.full_suite_cmd()} {shlex.join(_rerunnable(broken))}"
    gold = run(oracle, [oracle.gold_patch, oracle.test_patch], command, repeat=CONFIRM_RUNS)
    mine = run(oracle, [candidate, oracle.test_patch], command, repeat=CONFIRM_RUNS)
    if not (gold.applied and mine.applied) or not gold.runs or not mine.runs:
        return list(broken)
    return [
        test
        for test in broken
        if all(passed(test, s) for s, _ in gold.runs)
        and all(not passed(test, s) for s, _ in mine.runs)
    ]


@dataclass(frozen=True)
class Divergence:
    source: str  # "utboost" or "generated"
    divergent: tuple[str, ...]  # stable on both sides, different outcomes
    unstable: tuple[str, ...]  # an outcome that changed across a side's reruns
    stable: int


def _stable(runs: Sequence[tuple[Mapping[str, str], int | None]]) -> dict[str, bool]:
    """Each test's pass/fail where every rerun agrees."""
    tests = set().union(*(set(s) for s, _ in runs)) if runs else set()
    outcome = {}
    for test in tests:
        seen = {passed(test, s) for s, _ in runs}
        if len(seen) == 1:
            outcome[test] = seen.pop()
    return outcome


def differential(
    oracle: Oracle,
    candidate: str,
    tests_patch: str,
    *,
    source: str,
    reruns: int = RERUNS,
    run: Any = run_tests,
) -> Divergence:
    """Runs the tests ``tests_patch`` adds against the gold patch and the candidate, ``reruns``
    times each: a test stable on both sides with different outcomes is a divergence."""
    files = changed_files(tests_patch)
    command = f"{oracle.full_suite_cmd()} {shlex.join(files)}"
    gold = run(oracle, [oracle.gold_patch, tests_patch], command, repeat=reruns)
    mine = run(oracle, [candidate, tests_patch], command, repeat=reruns)
    if not (gold.runs and mine.runs):
        raise OracleError(
            f"{oracle.instance_id}: the {source} tests did not run: {gold.problem or mine.problem}"
        )
    on_gold, on_mine = _stable(gold.runs), _stable(mine.runs)
    every = set().union(*(set(s) for s, _ in gold.runs + mine.runs))
    both = on_gold.keys() & on_mine.keys()
    return Divergence(
        source,
        tuple(sorted(t for t in both if on_gold[t] != on_mine[t])),
        tuple(sorted(every - both)),
        len(both),
    )


def utboost_patch(oracle: Oracle, augmented: Mapping[str, Any]) -> str:
    """UTBoost's augmented test patch for the task, checked to be the same task."""
    if (
        augmented.get("instance_id") != oracle.instance_id
        or augmented.get("base_commit") != oracle.base_commit
    ):
        raise OracleError(f"the UTBoost record is not {oracle.instance_id}'s")
    return str(augmented["test_patch"])


def tier_b(divergences: Sequence[Divergence]) -> Verdict:
    """``CORRECT_auto`` when no test diverges; ``DIVERGENT`` (to the annotators) otherwise."""
    found = {d.source: list(d.divergent) for d in divergences if d.divergent}
    evidence = {
        "sources": [d.source for d in divergences],
        "stable_tests": sum(d.stable for d in divergences),
        "unstable_tests": sum(len(d.unstable) for d in divergences),
    }
    if found:
        return Verdict(
            "DIVERGENT",
            "a test the gold patch passes behaves differently",
            evidence | {"divergent": found},
        )
    if not evidence["stable_tests"]:
        return Verdict("NEEDS_REVIEW", "no stable differential test", evidence)
    return Verdict("CORRECT_auto", "no stable test diverges from the gold patch", evidence)


def summary(verdicts: Iterable[Verdict]) -> dict[str, int]:
    return dict(sorted(Counter(v.tier for v in verdicts).items()))


def save(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_bytes("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8"))
