"""JavaScript and TypeScript targets, at the level of test outcomes (K01; ADR-0017, proposed).

Repro's pipeline is built for Python: its tracer, its symbol and import analysis, and its
provisioning. This module is the first slice of a second language. It does what the evidence
model needs before any tracer: run a change's test suite on base and on head, the same way on
both, and compare the outcomes of each test. The rest of the design, a V8-side tracer and the
card, is ADR-0017, proposed and awaiting the owner's approval.

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
  both. Repro's network guard is a Python audit hook, so it does not see a Node process: the
  run is ``network: none-detected`` only at L3, in a container (``sandbox_image`` with Node).
  Node runs with WebAssembly's trap handler off and its heap capped (``NODE_OPTIONS``): the
  trap handler's address-space reservations do not fit the POSIX sandbox's memory limit.
- **A test's identity** is its file, relative to the project, and its full name:
  ``test/m.test.js::m adds``, the counterpart of a pytest node ID.

    repro js-run --repo <path> --base <ref> --head <ref> [--json <file>]
"""

import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from repro import jsmap
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


class JsError(Exception):
    """A project Repro cannot run, or a run it cannot read; the message says why."""


@dataclass(frozen=True)
class JsProject:
    root: Path
    runner: Runner
    manager: Manager

    @classmethod
    def detect(cls, root: Path) -> "JsProject":
        manifest = root / "package.json"
        if not manifest.is_file():
            raise JsError("no package.json")
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise JsError(f"package.json cannot be read: {exc}") from None
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


def runner_argv(
    project: JsProject, report: str, *, entry: str | None = None, extra: Sequence[str] = ()
) -> list[str]:
    """The runner's command, with its JSON report written to ``report``; ``entry`` replaces the
    runner's entry point under ``node_modules`` (a test's), ``extra`` comes last (the map's
    setup, K06)."""
    node = shutil.which("node")
    if node is None:
        raise JsError("node is not installed")
    script = entry or str(project.root / ENTRY[project.runner])
    if project.runner == "vitest":
        return [node, script, "run", "--reporter=json", f"--outputFile={report}", *extra]
    return [node, script, "--ci", "--json", f"--outputFile={report}", *extra]


def read_report(data: bytes, root: Path) -> dict[str, str]:
    """Each test's outcome, by ``<file relative to root>::<full name>``."""
    try:
        report = json.loads(data)
    except ValueError as exc:
        raise JsError(f"the report is not JSON: {exc}") from None
    found: dict[str, str] = {}
    for suite in report.get("testResults", []):
        try:
            file = PurePosixPath(
                Path(suite["name"]).resolve().relative_to(root.resolve()).as_posix()
            )
        except ValueError:
            file = PurePosixPath(Path(suite["name"]).name)
        for test in suite.get("assertionResults", []):
            name = test.get("fullName") or " ".join(
                [*test.get("ancestorTitles", []), test["title"]]
            )
            found[f"{file}::{name}"] = STATUS.get(str(test.get("status")), "failed")
    return found


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


def run_side(
    git: Git,
    commit: str,
    work: Path,
    *,
    install: bool = True,
    entry: str | None = None,
    limits: Limits | None = None,
) -> Side:
    """One side: its snapshot, its dependencies (unless ``install`` is off), its tests."""
    tree = work / "snapshot"
    snapshot(git, commit, tree)
    side = Side(commit)
    try:
        project = JsProject.detect(tree)
        if install:
            done = subprocess.run(  # noqa: S603 - the package manager, scripts off
                install_argv(project),
                cwd=tree,
                capture_output=True,
                timeout=INSTALL_TIMEOUT_S,
                check=False,
            )
            if done.returncode != 0:
                said = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
                raise JsError(f"the install failed: {said[0][:300] if said else done.returncode}")
        box = ProcessSandbox(
            work / "box", limits or Limits(timeout_s=900, memory_bytes=MEMORY_BYTES)
        )
        report = work / "box" / REPORT
        mapped = work / "box" / jsmap.MAP_FILE
        env = {"NODE_OPTIONS": NODE_OPTIONS, "REPRO_JS_MAP": str(mapped)}
        extra, unmapped = _map_setup(project, tree, box, env, entry)
        run = box.run(
            runner_argv(project, str(report), entry=entry, extra=extra),
            cwd=tree,
            env=env,
            writable=(work / "box",),
        )
        if not report.is_file():
            # Node ends a crash with its version: the error is the line that names one.
            lines = run.stderr.decode("utf-8", "replace").strip().splitlines()
            error = ([line for line in lines if "Error" in line] or lines or [""])[-1].strip()
            raise JsError(
                f"the tests wrote no report ({run.outcome}, exit {run.returncode}): {error[:300]}"
            )
        side.outcomes = read_report(report.read_bytes(), tree)
        side.map = _read_map(mapped, unmapped)
    except JsError as exc:
        side.problem = str(exc)
    return side


def _map_setup(
    project: JsProject, tree: Path, box: ProcessSandbox, env: Mapping[str, str], entry: str | None
) -> tuple[list[str], str]:
    """The runner's extra arguments for the map (K06), and why there is no map if there is none:
    the tests then run as they would without it."""
    try:
        if project.runner == "vitest":
            return jsmap.vitest_setup(tree), ""
        node = shutil.which("node")
        if node is None:
            raise JsError("node is not installed")
        script = entry or str(project.root / ENTRY[project.runner])
        shown = box.run([node, script, "--showConfig"], cwd=tree, env=env)
        return jsmap.jest_setup(tree, jsmap.jest_own_setup(shown.stdout)), ""
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
    changes: Sequence[jsmap.JsChange] = (),
    selected: Mapping[str, list[str]] | None = None,
) -> dict[str, object]:
    """What ``repro js-run`` reports: each side's counts, the comparison, the changed functions
    and the tests they select (K06), and what is missing."""
    missing = ["function-level traces: no JavaScript tracer yet (ADR-0017 phase 3, K07)"]
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
        "selected": dict(selected or {}),
        "isolation": "L2 (process); a Node process's network use is not detected",
        "missing": missing,
    }


def run_change(
    git: Git, base: str, head: str, work: Path, *, install: bool = True, entry: str | None = None
) -> dict[str, object]:
    sides = [
        run_side(git, commit, work / name, install=install, entry=entry)
        for name, commit in (("base", base), ("head", head))
    ]
    found = None if any(s.problem for s in sides) else compare(sides[0].outcomes, sides[1].outcomes)
    changes = jsmap.changed(git, base, head)
    maps = [side.map for side in sides if side.map is not None]
    return summary(sides[0], sides[1], found, changes, jsmap.select(changes, maps))
