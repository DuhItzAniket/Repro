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
- **A test's identity** is its file, relative to the project, and its full name:
  ``test/m.test.js::m adds``, the counterpart of a pytest node ID.

    repro js-run --repo <path> --base <ref> --head <ref> [--json <file>]
"""

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from repro.gitops import Git, snapshot
from repro.sandbox import Limits, ProcessSandbox

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


def runner_argv(project: JsProject, report: str, *, entry: str | None = None) -> list[str]:
    """The runner's command, with its JSON report written to ``report``; ``entry`` replaces the
    runner's entry point under ``node_modules`` (a test's)."""
    node = shutil.which("node")
    if node is None:
        raise JsError("node is not installed")
    script = entry or str(project.root / ENTRY[project.runner])
    if project.runner == "vitest":
        return [node, script, "run", "--reporter=json", f"--outputFile={report}"]
    return [node, script, "--ci", "--json", f"--outputFile={report}"]


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
        box = ProcessSandbox(work / "box", limits or Limits(timeout_s=900))
        report = work / "box" / REPORT
        run = box.run(
            runner_argv(project, str(report), entry=entry), cwd=tree, writable=(work / "box",)
        )
        if not report.is_file():
            said = run.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
            raise JsError(
                f"the tests wrote no report ({run.outcome}): {said[0][:300] if said else ''}"
            )
        side.outcomes = read_report(report.read_bytes(), tree)
    except JsError as exc:
        side.problem = str(exc)
    return side


def summary(base: Side, head: Side, found: Comparison | None) -> dict[str, object]:
    """What ``repro js-run`` reports: each side's counts, the comparison, and what is missing."""
    missing = ["function-level traces: no JavaScript tracer yet (ADR-0017, proposed)"]
    if base.problem or head.problem:
        missing.append(f"tests: {base.problem or head.problem}")
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
    return summary(sides[0], sides[1], found)
