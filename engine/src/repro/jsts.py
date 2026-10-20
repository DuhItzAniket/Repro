"""JavaScript and TypeScript targets: the project, its dependencies, and runs of its tests (K01,
K06, K07, K08; ADR-0017).

``repro run`` reproduces a JavaScript or TypeScript change with these (``repro.js_stage``, K08);
``repro js-run`` reports the same runs without a card (K01's command, kept for a quick look).

- **The project** (``JsProject.detect``): a ``package.json`` whose dependencies or ``test``
  script name Vitest or Jest. The package manager is read from the lockfile (npm, pnpm or
  Yarn); without one, dependencies cannot be installed reproducibly and the project is refused.
- **Dependencies** are installed from the lockfile with lifecycle scripts disabled
  (``--ignore-scripts``), so no code of the target or of its dependencies runs while the
  network is reachable [npm docs, "npm ci"; pnpm docs, "pnpm install"; checked 2026-10-18].
  This is the same rule as Python's provisioning (D03).
- **The tests** run in Repro's process sandbox (L2: a minimal environment, a contained process
  tree, a time limit), with the runner's JSON report. Vitest's report is "compatible with
  Jest's ``--json`` option" [vitest.dev, "Reporters", checked 2026-10-18], so one reader serves
  both. Each test's start (line and column, 1-based) comes with it: Vitest's
  ``--includeTaskLocation`` and Jest's ``--testLocationInResults`` (both in their ``--help``,
  Vitest 5.0.4 and Jest 30.5.2, checked 2026-10-20). Repro's network guard is a Python audit
  hook, so it does not see a Node process: neither blocked nor detected at L2. Node runs with
  WebAssembly's trap handler off and its heap capped (``NODE_OPTIONS``): the trap handler's
  address-space reservations do not fit the POSIX sandbox's memory limit.
- **A test's identity** is its file, relative to the project, and its full name:
  ``test/m.test.js::m adds``, the counterpart of a pytest node ID.
- **A test file that did not run** (a syntax error, an import that fails) has no tests in the
  report, only a message; Repro keeps it (``Side.broken``).

    repro js-run --repo <path> --base <ref> --head <ref> [--json <file>]
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

from repro import jsmap, jstrace
from repro.gitops import Git, snapshot
from repro.sandbox import GIB, Limits, ProcessSandbox

Runner = Literal["vitest", "jest"]
Manager = Literal["npm", "pnpm", "yarn"]
LOCKFILES: Final[Mapping[str, Manager]] = {
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
}
#: The runners' own entry points under ``node_modules``, run with ``node``.
ENTRY: Final[Mapping[Runner, str]] = {
    "vitest": "node_modules/vitest/vitest.mjs",
    "jest": "node_modules/jest/bin/jest.js",
}
REPORT: Final = "repro-report.json"
INSTALL_TIMEOUT_S: Final = 900.0
#: Node's options in the sandbox. V8 bounds-checks WebAssembly memory with a trap handler that
#: "requires allocating a big virtual memory cage (currently 10GB)" [nodejs.org, CLI docs,
#: ``--disable-wasm-trap-handler``, checked 2026-10-18], and the POSIX sandbox caps address
#: space. Measured on Linux with Node 22.23 and Vitest 5.0.4: with the trap handler, no report
#: below 48 GiB; without it, a report from 8 GiB. So it is off, and the heap has its own cap.
NODE_OPTIONS: Final = "--disable-wasm-trap-handler --max-old-space-size=4096"
if sys.platform == "win32":
    #: Windows limits committed memory, which a reservation does not use.
    MEMORY_BYTES: Final = 4 * GIB
else:
    #: POSIX limits address space, which V8 reserves far beyond what it commits: Vitest aborted
    #: at 4 GiB and ran from 8 GiB in the measurement above.
    MEMORY_BYTES: Final = 16 * GIB
#: The report's statuses, as Repro's outcomes. ``pending`` and ``todo`` are Jest's skips.
STATUS: Final = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "pending": "skipped",
    "todo": "skipped",
    "disabled": "skipped",
}
#: The dependency sections of ``package.json``, in the order a name is looked up.
SECTIONS: Final = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
#: A message keeps this much, as Python's do (``runner.pytest``).
_TEXT: Final = 2000
#: The terminal's colour codes, which Jest writes into its messages.
_ANSI: Final = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class JsError(Exception):
    """A project Repro cannot run, or a run it cannot read; the message says why."""


@dataclass(frozen=True)
class JsProject:
    root: Path
    runner: Runner
    manager: Manager

    @classmethod
    def detect(cls, root: Path) -> "JsProject":
        data = manifest(root)
        names = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        script = str(data.get("scripts", {}).get("test", ""))
        runner: Runner
        if "vitest" in names or "vitest" in script:
            runner = "vitest"
        elif "jest" in names or "jest" in script:
            runner = "jest"
        else:
            raise JsError("neither Vitest nor Jest is the project's test runner")
        manager = next((m for name, m in LOCKFILES.items() if (root / name).is_file()), None)
        if manager is None:
            raise JsError("no lockfile: dependencies cannot be installed reproducibly")
        return cls(root, runner, manager)

    @property
    def lockfile(self) -> Path:
        return self.root / next(name for name, m in LOCKFILES.items() if m == self.manager)


def manifest(root: Path) -> dict[str, Any]:
    manifest = root / "package.json"
    if not manifest.is_file():
        raise JsError("no package.json")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JsError(f"package.json cannot be read: {exc}") from None
    if not isinstance(data, dict):
        raise JsError("package.json is not an object")
    return data


def install_argv(project: JsProject) -> list[str]:
    """The install from the lockfile, lifecycle scripts off."""
    program = shutil.which(project.manager)
    if program is None:
        raise JsError(f"{project.manager} is not installed")
    return {
        "npm": [program, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        "pnpm": [program, "install", "--frozen-lockfile", "--ignore-scripts"],
        "yarn": [program, "install", "--frozen-lockfile", "--ignore-scripts"],
    }[project.manager]


def install_dependencies(project: JsProject) -> None:
    """Installs the project's dependencies from its lockfile, lifecycle scripts off."""
    try:
        done = subprocess.run(  # noqa: S603 - the package manager, scripts off
            install_argv(project),
            cwd=project.root,
            capture_output=True,
            timeout=INSTALL_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise JsError(f"the install took longer than {INSTALL_TIMEOUT_S:.0f} s") from None
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        raise JsError(f"the install failed: {said[0][:300] if said else done.returncode}")
    entry = ENTRY[project.runner]
    if not (project.root / entry).is_file():
        # Seen on Windows inside a packaged app, whose writes under AppData are redirected:
        # pnpm's links pointed at the unredirected path (docs/guide/troubleshooting.md).
        raise JsError(
            f"after the install, {entry} cannot be read: the runner is run from node_modules "
            "(Yarn's Plug'n'Play is not supported), and each link there must resolve"
        )


def node_version() -> str:
    """The host's Node.js version, ``22.23.0`` (``node --version`` runs none of the target)."""
    node = shutil.which("node")
    if node is None:
        raise JsError("node is not installed")
    done = subprocess.run([node, "--version"], capture_output=True, timeout=60, check=False)  # noqa: S603
    found = re.match(r"v?(\d+\.\d+\.\d+)", done.stdout.decode("ascii", "replace").strip())
    if found is None:
        raise JsError("node --version gave no version")
    return found.group(1)


def lock_sha256(project: JsProject) -> str:
    return hashlib.sha256(project.lockfile.read_bytes()).hexdigest()


def declared(root: Path) -> dict[str, str] | None:
    """What ``package.json`` asks for, by name (the first section that names it), or None if
    it cannot be read."""
    try:
        data = manifest(root)
    except JsError:
        return None
    found: dict[str, str] = {}
    for section in SECTIONS:
        names = data.get(section)
        if isinstance(names, dict):
            for name, wanted in names.items():
                found.setdefault(str(name), str(wanted)[:100])
    return found


def installed(root: Path) -> dict[str, str]:
    """The packages installed at the top of ``node_modules``, by name, with their version, read
    from their ``package.json`` files (no package's code runs)."""
    modules = root / "node_modules"
    found: dict[str, str] = {}
    if not modules.is_dir():
        return found
    folders = []
    for entry in modules.iterdir():
        if entry.name.startswith("@") and entry.is_dir():
            folders += [e for e in entry.iterdir() if e.is_dir()]
        elif not entry.name.startswith("."):
            folders.append(entry)
    for folder in folders:
        try:
            data = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            name = str(data.get("name") or folder.relative_to(modules).as_posix())
            found[name] = data["version"][:100]
    return found


def runner_argv(
    project: JsProject, report: str, *, entry: str | None = None, extra: Sequence[str] = ()
) -> list[str]:
    """The runner's command, with its JSON report written to ``report`` and each test's start
    in it; ``entry`` replaces the runner's entry point under ``node_modules`` (a test's),
    ``extra`` comes last (the map's setup, K06; the files to run, K08)."""
    node = shutil.which("node")
    if node is None:
        raise JsError("node is not installed")
    script = entry or str(project.root / ENTRY[project.runner])
    if project.runner == "vitest":
        return [
            node,
            script,
            "run",
            "--reporter=json",
            f"--outputFile={report}",
            "--includeTaskLocation",
            *extra,
        ]
    return [
        node,
        script,
        "--ci",
        "--json",
        f"--outputFile={report}",
        "--testLocationInResults",
        *extra,
    ]


def only(runner: Runner, files: Sequence[str]) -> list[str]:
    """The runner's arguments that run ``files`` alone: Vitest's filters are parts of a path,
    Jest's are patterns over its absolute path (either separator)."""
    if runner == "vitest":
        return list(files)
    patterns = []
    for file in files:
        escaped = "/".join(re.escape(part) for part in PurePosixPath(file).parts)
        patterns.append(escaped.replace("/", r"[\\/]") + "$")
    return patterns


@dataclass(frozen=True)
class Reported:
    """A test as the runner's report gives it."""

    outcome: str
    #: Where it starts in its file, (line, column), 1-based; None if the report does not say.
    start: tuple[int, int] | None = None
    message: str | None = None
    duration_ms: int = 0


def _relative(name: str, root: Path) -> str:
    try:
        return Path(name).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return PurePosixPath(Path(name).name).as_posix()


def _text(value: object) -> str | None:
    if isinstance(value, list):
        value = "\n".join(str(v) for v in value)
    text = _ANSI.sub("", str(value or "")).strip()
    return text[:_TEXT] or None


def read_tests(data: bytes, root: Path) -> tuple[dict[str, Reported], dict[str, str]]:
    """Each test, by ``<file relative to root>::<full name>``, and each test file that did not
    run, with its message."""
    try:
        report = json.loads(data)
    except ValueError as exc:
        raise JsError(f"the report is not JSON: {exc}") from None
    found: dict[str, Reported] = {}
    broken: dict[str, str] = {}
    for suite in report.get("testResults", []):
        file = _relative(suite["name"], root)
        tests = suite.get("assertionResults", [])
        if not tests and suite.get("status") == "failed":
            broken[file] = _text(suite.get("message")) or "the test file did not run"
        for test in tests:
            name = test.get("fullName") or " ".join(
                [*test.get("ancestorTitles", []), test["title"]]
            )
            where = test.get("location")
            start = (
                (int(where["line"]), int(where["column"]))
                if isinstance(where, dict) and "line" in where and "column" in where
                else None
            )
            outcome = STATUS.get(str(test.get("status")), "failed")
            message = _text(test.get("failureMessages")) if outcome == "failed" else None
            duration = test.get("duration")
            took = max(0, int(duration)) if isinstance(duration, int | float) else 0
            found[f"{file}::{name}"] = Reported(outcome, start, message, took)
    return found, broken


def read_report(data: bytes, root: Path) -> dict[str, str]:
    """Each test's outcome, by ``<file relative to root>::<full name>``."""
    return {test: found.outcome for test, found in read_tests(data, root)[0].items()}


@dataclass(frozen=True)
class Comparison:
    """How head's outcomes differ from base's."""

    regressions: tuple[str, ...]  # passed on base, failed on head
    fixed: tuple[str, ...]  # failed on base, passed on head
    new_failing: tuple[str, ...]  # only on head, failed
    new_passing: tuple[str, ...]  # only on head, passed
    removed: tuple[str, ...]  # only on base
    same: int


def compare(base: Mapping[str, str], head: Mapping[str, str]) -> Comparison:
    both = base.keys() & head.keys()
    only_head = head.keys() - base.keys()
    return Comparison(
        tuple(sorted(t for t in both if base[t] == "passed" and head[t] == "failed")),
        tuple(sorted(t for t in both if base[t] == "failed" and head[t] == "passed")),
        tuple(sorted(t for t in only_head if head[t] == "failed")),
        tuple(sorted(t for t in only_head if head[t] == "passed")),
        tuple(sorted(base.keys() - head.keys())),
        sum(1 for t in both if base[t] == head[t]),
    )


@dataclass
class Side:
    commit: str
    outcomes: dict[str, str] = field(default_factory=dict)
    problem: str = ""
    #: What each test ran (K06); None when the side did not run.
    map: jsmap.TestMap | None = None
    #: The traced calls (K07), as the runtime wrote them.
    calls: bytes = b""
    #: Each test's start and failure message (K08), and the test files that did not run.
    starts: dict[str, tuple[int, int]] = field(default_factory=dict)
    messages: dict[str, str] = field(default_factory=dict)
    durations: dict[str, int] = field(default_factory=dict)
    broken: dict[str, str] = field(default_factory=dict)
    #: How the run ended, as the sandbox says: ``exited``, ``timeout`` or ``stopped``.
    ended: str = "exited"


def run_tests(
    project: JsProject,
    box: ProcessSandbox,
    out: Path,
    commit: str,
    *,
    entry: str | None = None,
    trace: Mapping[str, Sequence[str]] | None = None,
    again: bool = False,
    mapped: bool = True,
    files: Sequence[str] = (),
    stop: Callable[[], bool] | None = None,
) -> Side:
    """One run of the project's tests in ``box``, its report, map and calls written in ``out``.
    ``mapped``: with the map's setup (K06); ``trace``: the functions to trace (K07); ``again``:
    in another order (base's second run, A2); ``files``: these test files alone."""
    out.mkdir(parents=True, exist_ok=True)
    side = Side(commit)
    report = out / REPORT
    map_file = out / jsmap.MAP_FILE
    calls = out / jstrace.TRACE_FILE
    env = {"NODE_OPTIONS": NODE_OPTIONS}
    unmapped = ""
    extra: list[str] = []
    try:
        if mapped or trace:
            env["REPRO_JS_MAP"] = str(map_file)
            if trace:
                env |= {
                    "REPRO_JS_TRACE_PLAN": json.dumps(dict(trace)),
                    "REPRO_JS_TRACE_OUT": str(calls),
                    "REPRO_JS_TRACE_SAMPLES": str(jstrace.SAMPLES),
                }
            extra, unmapped = _map_setup(project, box, env, entry, trace=bool(trace))
        if again:
            extra += jstrace.shuffled(project.runner)
        extra += only(project.runner, files)
        run = box.run(
            runner_argv(project, str(report), entry=entry, extra=extra),
            cwd=project.root,
            env=env,
            writable=(out,),
            stop=stop,
        )
        side.ended = run.outcome
        if not report.is_file():
            # Node ends a crash with its version: the error is the line that names one.
            lines = run.stderr.decode("utf-8", "replace").strip().splitlines()
            error = ([line for line in lines if "Error" in line] or lines or [""])[-1].strip()
            raise JsError(
                f"the tests wrote no report ({run.outcome}, exit {run.returncode}): {error[:300]}"
            )
        tests, side.broken = read_tests(report.read_bytes(), project.root)
        side.outcomes = {test: found.outcome for test, found in tests.items()}
        side.starts = {test: found.start for test, found in tests.items() if found.start}
        side.messages = {test: found.message for test, found in tests.items() if found.message}
        side.durations = {test: found.duration_ms for test, found in tests.items()}
        if mapped:
            side.map = _read_map(map_file, unmapped)
        side.calls = calls.read_bytes() if calls.is_file() else b""
    except JsError as exc:
        side.problem = str(exc)
    return side


def run_side(
    git: Git,
    commit: str,
    work: Path,
    *,
    install: bool = True,
    entry: str | None = None,
    limits: Limits | None = None,
    trace: Mapping[str, Sequence[str]] | None = None,
    again: bool = False,
) -> Side:
    """One side, for ``repro js-run``: its snapshot, its dependencies (unless ``install`` is
    off), its tests. With ``trace``, the functions it names are traced (K07); ``again`` runs
    the tests in another order (base's second run, A2)."""
    tree = work / "snapshot"
    snapshot(git, commit, tree)
    try:
        project = JsProject.detect(tree)
        if install:
            install_dependencies(project)
    except JsError as exc:
        return Side(commit, problem=str(exc))
    box = ProcessSandbox(work / "box", limits or Limits(timeout_s=900, memory_bytes=MEMORY_BYTES))
    return run_tests(project, box, work / "box", commit, entry=entry, trace=trace, again=again)


def _map_setup(
    project: JsProject,
    box: ProcessSandbox,
    env: Mapping[str, str],
    entry: str | None,
    *,
    trace: bool = False,
) -> tuple[list[str], str]:
    """The runner's extra arguments for the map (K06), and why there is no map if there is none:
    the tests then run as they would without it."""
    try:
        if project.runner == "vitest":
            return jsmap.vitest_setup(project.root, trace=trace), ""
        node = shutil.which("node")
        if node is None:
            raise JsError("node is not installed")
        script = entry or str(project.root / ENTRY[project.runner])
        shown = box.run([node, script, "--showConfig"], cwd=project.root, env=env)
        own = jsmap.jest_own_setup(shown.stdout)
        return jsmap.jest_setup(project.root, own, trace=trace), ""
    except (jsmap.MapError, OSError) as exc:
        return [], str(exc)


def _read_map(path: Path, unmapped: str) -> jsmap.TestMap:
    if unmapped:
        return jsmap.TestMap(problem=unmapped)
    if not path.is_file():
        return jsmap.TestMap(problem="the setup file wrote no map")
    try:
        return jsmap.read_map(path.read_bytes())
    except jsmap.MapError as exc:
        return jsmap.TestMap(problem=str(exc))


def summary(
    base: Side,
    head: Side,
    found: Comparison | None,
    *,
    changes: Sequence[jsmap.JsChange] = (),
    selected: Mapping[str, jsmap.Selected] | None = None,
    behaviour: Mapping[str, object] | None = None,
    notes: Sequence[str] = (),
) -> dict[str, object]:
    """What ``repro js-run`` reports: each side's counts, the comparison, the changed functions
    and the tests they select (K06), their calls compared (K07), and what is missing."""
    missing = ["a card: repro run makes one (K08)", *notes]
    if base.problem or head.problem:
        missing.append(f"tests: {base.problem or head.problem}")
    missing.extend(
        f"the test map ({side.commit[:12]}): {side.map.problem}"
        for side in (base, head)
        if side.map is not None and side.map.problem
    )
    if changes:
        missing.append(
            "selection by function name: functions of the same name in one file are not told "
            "apart (more tests, never fewer)"
        )
    return {
        "base": {"commit": base.commit, "tests": len(base.outcomes), "problem": base.problem},
        "head": {"commit": head.commit, "tests": len(head.outcomes), "problem": head.problem},
        "comparison": None
        if found is None
        else {
            "regressions": list(found.regressions),
            "fixed": list(found.fixed),
            "new_failing": list(found.new_failing),
            "new_passing": list(found.new_passing),
            "removed": list(found.removed),
            "same": found.same,
        },
        "changes": [
            {"file": c.file, "functions": sorted(c.functions), "module_level": c.module_level}
            for c in changes
        ],
        "selected": {test: list(why.why) for test, why in (selected or {}).items()},
        "behaviour": behaviour,
        "isolation": "L2 (process); a Node process's network use is neither blocked nor detected",
        "missing": missing,
    }


def run_change(
    git: Git, base: str, head: str, work: Path, *, install: bool = True, entry: str | None = None
) -> dict[str, object]:
    changes = jsmap.changed(git, base, head)
    traced = jstrace.plan(changes)
    sides = [
        run_side(git, commit, work / name, install=install, entry=entry, trace=traced)
        for name, commit in (("base", base), ("head", head))
    ]
    found = None if any(s.problem for s in sides) else compare(sides[0].outcomes, sides[1].outcomes)
    maps = [side.map for side in sides if side.map is not None]
    behaviour, notes = _behaviour(git, base, work, sides, traced, install=install, entry=entry)
    selected = jsmap.select(changes, maps)
    return summary(
        sides[0], sides[1], found, changes=changes, selected=selected,
        behaviour=behaviour, notes=notes,
    )  # fmt: skip


def _behaviour(
    git: Git,
    base: str,
    work: Path,
    sides: Sequence[Side],
    traced: Mapping[str, Sequence[str]],
    *,
    install: bool,
    entry: str | None,
) -> tuple[dict[str, object] | None, list[str]]:
    """Base again (A2), then A, A2 and H's calls compared (K07); what could not be traced."""
    if not traced:
        return None, []
    if any(side.problem for side in sides):
        return None, ["function-level traces: a side did not run"]
    again = run_side(
        git, base, work / "base-again", install=install, entry=entry, trace=traced, again=True
    )
    if again.problem:
        return None, [f"function-level traces: base's second run: {again.problem}"]
    found, listed = jstrace.behaviour(
        [(s.outcomes, s.calls) for s in (sides[0], again, sides[1])], jstrace.targets(traced)
    )
    project = JsProject.detect(work / "base" / "snapshot")
    return jstrace.summary(found, listed), trace_notes(project.runner)


def trace_notes(runner: Runner) -> list[str]:
    """What function-level traces leave out, for ``runner``."""
    notes = [
        "function-level traces: top-level functions, const and let functions and class methods "
        "are traced; nested functions and object literal methods are not"
    ]
    if runner == "jest":
        notes.append(
            "function-level traces (Jest): calls through a module's exports only; a call from "
            "inside the module is not traced"
        )
    return notes
