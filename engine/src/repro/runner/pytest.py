"""Running a side's tests under Repro's pytest plugin (D04), and reading what it wrote.

The command is Repro's, whatever the project configures: ``-o addopts=`` drops the project's
own default options, ``-p no:randomly`` and ``-p no:xdist`` keep order and process layout
fixed, ``-p no:cacheprovider`` keeps the snapshot unwritten, and ``-p repro_pytest`` loads the
plugin, which the sandboxes already put first on ``PYTHONPATH`` beside the audit hook.
``--continue-on-collection-errors`` keeps one module that fails to import from hiding every
other test's outcome. JUnit XML is written too, as an artifact for people and other tools.

The environment adds ``PYTHONUTF8=1`` and ``TZ=UTC`` to the sandbox's own (fixed hash seed,
no host variables), ``REPRO_SEED`` for the plugin's per-test random seeds, and
``REPRO_NET_GUARD=1`` so a test that needs the network fails at once, and the same way on
every isolation level.

What the plugin wrote comes from inside the target's process, so it is read as untrusted: a
record that is not well formed is counted and skipped, and a run with no session record (a
crash, a kill, a timeout) is incomplete, never passing.
"""

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from repro.provision.env import Environment
from repro.sandbox.docker import WORK, DockerSandbox
from repro.sandbox.process import Execution, ProcessSandbox, read_head

TestOutcome = Literal["passed", "failed", "skipped", "xfailed", "xpassed", "error"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"passed", "failed", "skipped", "xfailed", "xpassed", "error"}
)
PLUGIN: Final = "repro_pytest"
RESULTS: Final = "results.jsonl"
JUNIT: Final = "junit.xml"
#: At most this much of a results or JUnit file is read (a hostile run could write without end).
MAX_BYTES: Final = 64 * 1024 * 1024
MAX_RECORDS: Final = 200_000
_TEXT: Final = 2000


def pytest_argv(
    python: str, *, out_dir: str, tests: Sequence[str] = (), extra: Sequence[str] = ()
) -> list[str]:
    """The command: Repro's options, then the node IDs to run (all tests if none)."""
    return [
        python, "-m", "pytest", "-o", "addopts=", "-p", PLUGIN, "-p", "no:randomly",
        "-p", "no:xdist", "-p", "no:cacheprovider", "--continue-on-collection-errors",
        "--junitxml", f"{out_dir}/{JUNIT}", "-q", "-rN", *extra, *tests,
    ]  # fmt: skip


def plugin_env(out_dir: str, *, seed: int = 0, net_guard: bool = True) -> dict[str, str]:
    """What the plugin and the determinism controls need, on top of the sandbox's environment."""
    env = {"REPRO_OUT": out_dir, "REPRO_SEED": str(seed), "PYTHONUTF8": "1", "TZ": "UTC"}
    if net_guard:
        env["REPRO_NET_GUARD"] = "1"
    return env


@dataclass(frozen=True, slots=True)
class TestResult:
    nodeid: str
    outcome: TestOutcome
    duration_s: float
    phase: str | None  # where it did not pass: setup, call or teardown
    message: str | None


@dataclass(frozen=True, slots=True)
class CollectError:
    nodeid: str
    message: str


@dataclass(frozen=True, slots=True)
class PytestRun:
    tests: dict[str, TestResult]
    collect_errors: tuple[CollectError, ...]
    #: The session record: exit status, collected count, versions. None if the run never ended.
    session: dict[str, Any] | None
    malformed: int = 0
    notes: tuple[str, ...] = field(default=())

    @property
    def complete(self) -> bool:
        return self.session is not None

    def outcomes(self) -> dict[str, str]:
        return {nodeid: result.outcome for nodeid, result in self.tests.items()}


def _test(record: dict[str, Any]) -> TestResult:
    nodeid, outcome = record["nodeid"], record["outcome"]
    if not isinstance(nodeid, str) or not nodeid or outcome not in OUTCOMES:
        raise ValueError(record)
    phase, message = record.get("phase"), record.get("message")
    return TestResult(
        nodeid=nodeid[:_TEXT],
        outcome=outcome,
        duration_s=float(record.get("duration_s", 0.0)),
        phase=phase if phase in ("setup", "call", "teardown") else None,
        message=str(message)[:_TEXT] if message is not None else None,
    )


def _session(record: dict[str, Any]) -> dict[str, Any]:
    exitstatus, collected = record["exitstatus"], record["collected"]
    if not isinstance(exitstatus, int) or not isinstance(collected, int):
        raise ValueError(record)
    return {
        "exitstatus": exitstatus,
        "collected": collected,
        "pytest": str(record.get("pytest"))[:50],
        "python": str(record.get("python"))[:50],
        "seed": record.get("seed"),
    }


def read_results(data: bytes | None) -> PytestRun:
    """What the plugin wrote to ``results.jsonl`` (None: it wrote nothing at all)."""
    if data is None:
        return PytestRun({}, (), None, notes=("the plugin wrote no results",))
    tests: dict[str, TestResult] = {}
    errors: list[CollectError] = []
    session: dict[str, Any] | None = None
    malformed = 0
    notes: list[str] = []
    for count, line in enumerate(data.splitlines()):
        if count >= MAX_RECORDS:
            notes.append(f"more than {MAX_RECORDS} records: the rest were not read")
            break
        try:
            record = json.loads(line)
            kind = record["kind"]
            if kind == "test":
                result = _test(record)
                tests[result.nodeid] = result
            elif kind == "collect_error":
                nodeid, message = str(record["nodeid"]), str(record["message"])
                errors.append(CollectError(nodeid[:_TEXT], message[:_TEXT]))
            elif kind == "session":
                session = _session(record)
            else:
                raise ValueError(kind)
        except (ValueError, KeyError, TypeError):
            malformed += 1
    if session is None:
        notes.append("the run did not finish: no session record")
    return PytestRun(tests, tuple(errors), session, malformed, tuple(notes))


@dataclass(frozen=True, slots=True)
class TestRun:
    """One run of a side's tests: how the command ran, and what the plugin reported."""

    execution: Execution
    results: PytestRun
    junit: bytes | None


def run_tests(
    sandbox: ProcessSandbox | DockerSandbox,
    env: Environment,
    *,
    tests: Sequence[str] = (),
    seed: int = 0,
    timeout_s: float | None = None,
    stop: Callable[[], bool] | None = None,
) -> TestRun:
    """Runs ``tests`` (node IDs; all if empty) with ``env``'s interpreter in ``sandbox``."""
    name = f"pytest-{uuid.uuid4().hex[:12]}"
    if isinstance(sandbox, DockerSandbox):
        relative = f".repro/{name}"
        out = f"{WORK}/{relative}"
        execution = sandbox.run(
            pytest_argv(env.python, out_dir=out, tests=tests),
            env=plugin_env(out, seed=seed),
            timeout_s=timeout_s,
            stop=stop,
        )
        results = sandbox.read_file(f"{relative}/{RESULTS}", limit=MAX_BYTES)
        junit = sandbox.read_file(f"{relative}/{JUNIT}", limit=MAX_BYTES)
    else:
        directory = sandbox.work / name
        execution = sandbox.run(
            pytest_argv(env.python, out_dir=directory.as_posix(), tests=tests),
            cwd=env.project.root,
            env=plugin_env(str(directory), seed=seed),
            timeout_s=timeout_s,
            stop=stop,
            writable=(directory,),
        )
        results, junit = _read(directory / RESULTS), _read(directory / JUNIT)
    return TestRun(execution, read_results(results), junit)


def _read(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return read_head(path, MAX_BYTES)[0]
