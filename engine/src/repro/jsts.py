"""JavaScript and TypeScript targets: the project, its dependencies, and runs of its tests (K01,
K06, K07, K08, K11; ADR-0017).

``repro run`` reproduces a JavaScript or TypeScript change with these (``repro.js_stage``, K08);
``repro js-run`` reports the same runs without a card (K01's command, kept for a quick look).

- **The project** (``JsProject.detect``): a ``package.json`` whose dependencies or ``test``
  script name Vitest or Jest. The package manager is read from the lockfile (npm, pnpm or
  Yarn); without one, dependencies cannot be installed reproducibly and the project is refused.
- **Dependencies** are installed from the lockfile with lifecycle scripts disabled
  (``--ignore-scripts``), and pnpm's hooks file and Yarn's ``yarn-path`` ignored
  (``INSTALL_ENV``), so no code of the target or of its dependencies runs while the
  network is reachable [npm docs, "npm ci"; pnpm docs, "pnpm install"; checked 2026-10-18].
  This is the same rule as Python's provisioning (D03). On the host (``install_dependencies``)
  or, at L3 (K11), in a container of their own on the sandbox's volume, the only one with the
  network (``install_in_container``), with the Node.js image's package managers.
- **The tests** run in a ``Tree``: the process sandbox on the host's copy of the project (L2: a
  minimal environment, a contained process tree, a time limit; ``HostTree``), or fresh
  containers with no network on a volume (L3, K11; ``VolumeTree``). The runner writes its JSON
  report. Vitest's report is "compatible with Jest's ``--json`` option" [vitest.dev,
  "Reporters", checked 2026-10-18], so one reader serves both. Each test's start (line and
  column, 1-based) comes with it: Vitest's ``--includeTaskLocation`` and Jest's
  ``--testLocationInResults`` (both in their ``--help``, Vitest 5.0.4 and Jest 30.5.2, checked
  2026-10-20). Repro's network guard is a Python audit hook, so it does not see a Node process:
  at L2 its network use is neither blocked nor detected; at L3 it is blocked, and still not
  detected. Node runs with WebAssembly's trap handler off and its heap capped
  (``NODE_OPTIONS``): the trap handler's address-space reservations do not fit the POSIX
  sandbox's memory limit.
- **A test's identity** is its file, relative to the project, and its full name:
  ``test/m.test.js::m adds``, the counterpart of a pytest node ID. A container's paths are
  POSIX, under ``/work``; the identity is the same on either tree.
- **A test file that did not run** (a syntax error, an import that fails) has no tests in the
  report, only a message; Repro keeps it (``Side.broken``).

    repro js-run --repo <path> --base <ref> --head <ref> [--json <file>]
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Final, Literal, Protocol

from repro import jsmap, jstrace
from repro.gitops import Git, snapshot
from repro.sandbox import GIB, DockerSandbox, Execution, Limits, ProcessSandbox, SandboxError
from repro.sandbox.docker import TMP, TMPFS_SIZE, USER, WORK

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
#: The install from the lockfile, lifecycle scripts off: the package manager's arguments.
INSTALL: Final[Mapping[Manager, tuple[str, ...]]] = {
    "npm": ("ci", "--ignore-scripts", "--no-audit", "--no-fund"),
    "pnpm": ("install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile"),
    "yarn": ("install", "--frozen-lockfile", "--ignore-scripts"),
}
#: What else keeps the project's own code from running during an install, with the network on
#: (K11; measured in the Node.js image on 2026-10-20, each wrote a file when allowed):
#: - pnpm loads the project's ``.pnpmfile.cjs`` whatever ``--ignore-scripts`` says:
#:   ``--ignore-pnpmfile`` (above; "Disable pnpm hooks defined in .pnpmfile.cjs", pnpm 10.34.7's
#:   ``pnpm install --help``);
#: - Yarn classic runs the file ``.yarnrc``'s ``yarn-path`` names in place of itself, unless
#:   ``YARN_IGNORE_PATH`` is set (Yarn 1.22.22's ``lib/cli.js``).
INSTALL_ENV: Final[Mapping[str, str]] = {"YARN_IGNORE_PATH": "1"}
#: Where a container's install keeps the package managers' caches (K11): in the volume, not in
#: the memory-backed ``/tmp``, and removed when it ends (they are not the project's, and Jest
#: would index them).
CACHE: Final = ".repro/cache"
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
    """The install from the lockfile, lifecycle scripts off, with the host's package manager."""
    program = shutil.which(project.manager)
    if program is None:
        raise JsError(f"{project.manager} is not installed")
    return [program, *INSTALL[project.manager]]


#: Lines that end a failed install's output without saying why: npm's pointer to its log, and
#: the version Node.js prints after an uncaught error.
_NOT_WHY: Final = re.compile(r"A complete log of this run|^Node\.js v\d")


def _failed(done: subprocess.CompletedProcess[bytes]) -> str:
    """Why an install failed: the last line that says, from stderr, else from stdout (pnpm
    writes its errors there)."""
    for stream in (done.stderr, done.stdout):
        lines = [line.strip() for line in stream.decode("utf-8", "replace").splitlines()]
        said = [line for line in lines if line and not _NOT_WHY.search(line)]
        if said:
            return f"the install failed: {said[-1][:300]}"
    return f"the install failed: exit {done.returncode}"


def _no_runner(entry: str) -> JsError:
    return JsError(
        f"after the install, {entry} cannot be read: the runner is run from node_modules "
        "(Yarn's Plug'n'Play is not supported), and each link there must resolve"
    )


def install_dependencies(project: JsProject) -> None:
    """Installs the project's dependencies from its lockfile, lifecycle scripts off."""
    try:
        done = subprocess.run(  # noqa: S603 - the package manager, scripts off
            install_argv(project),
            cwd=project.root,
            env={**os.environ, **INSTALL_ENV},
            capture_output=True,
            timeout=INSTALL_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise JsError(f"the install took longer than {INSTALL_TIMEOUT_S:.0f} s") from None
    if done.returncode != 0:
        raise JsError(_failed(done))
    entry = ENTRY[project.runner]
    if not (project.root / entry).is_file():
        # Seen on Windows inside a packaged app, whose writes under AppData are redirected:
        # pnpm's links pointed at the unredirected path (docs/guide/troubleshooting.md).
        raise _no_runner(entry)


def install_in_container(box: DockerSandbox, project: JsProject) -> None:
    """Installs the project's dependencies into ``box``'s volume from its lockfile, lifecycle
    scripts off (K11): ``INSTALL``'s commands, with the image's package managers, in a
    container of their own. It is the only one with the network, and is otherwise hardened as
    the sandbox's are: a read-only root, no capabilities, the unprivileged user. Corepack works
    from a copy of the image's in ``/tmp``, so that a version the project names can be fetched
    into it."""
    cache = f"{WORK}/{CACHE}"
    script = (
        f"set -e; trap 'rm -rf {cache}' EXIT; "
        f'cp -R "$COREPACK_HOME" {TMP}/corepack; export COREPACK_HOME={TMP}/corepack; '
        + " ".join([project.manager, *INSTALL[project.manager]])
    )
    name = f"repro-install-{uuid.uuid4().hex[:12]}"
    command = [
        box.docker, "run", "--rm", "--name", name,
        *(["--runtime", box.runtime] if box.runtime is not None else []),
        "--read-only", "--tmpfs", f"{TMP}:rw,exec,size={TMPFS_SIZE}",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", USER,
        "-v", f"{box.volume}:{WORK}", "-w", WORK,
        "-e", f"HOME={TMP}", "-e", f"TMPDIR={TMP}",
        "-e", f"npm_config_cache={cache}/npm", "-e", f"npm_config_store_dir={cache}/pnpm",
        "-e", f"YARN_CACHE_FOLDER={cache}/yarn",
        *[flag for key, value in INSTALL_ENV.items() for flag in ("-e", f"{key}={value}")],
        "--entrypoint", "sh", box.image, "-c", script,
    ]  # fmt: skip
    try:
        done = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
            command, capture_output=True, timeout=INSTALL_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
            [box.docker, "rm", "-f", name], capture_output=True, timeout=60, check=False
        )
        raise JsError(f"the install took longer than {INSTALL_TIMEOUT_S:.0f} s") from None
    except OSError as exc:
        raise SandboxError(f"docker run: {exc}") from None
    if done.returncode != 0:
        raise JsError(_failed(done))


#: Run with ``node -e`` in the sandbox, after the install, with no network: Node's version (what
#: ``node --version`` prints), whether the runner's entry (the argument) is there, and the
#: packages at the top of ``node_modules``, as ``installed`` reads them (their ``package.json``:
#: no package's code runs).
_ENVIRONMENT: Final = """
const fs = require("node:fs");
const read = (path) => { try { return fs.readdirSync(path); } catch { return []; } };
const isDir = (path) => { try { return fs.statSync(path).isDirectory(); } catch { return false; } };
const folders = [];
for (const name of read("node_modules")) {
  if (name.startsWith("@") && isDir(`node_modules/${name}`)) {
    for (const inner of read(`node_modules/${name}`))
      if (isDir(`node_modules/${name}/${inner}`)) folders.push(`${name}/${inner}`);
  } else if (!name.startsWith(".")) folders.push(name);
}
const installed = {};
for (const folder of folders) {
  try {
    const data = JSON.parse(fs.readFileSync(`node_modules/${folder}/package.json`, "utf8"));
    if (data && typeof data.version === "string")
      installed[String(data.name || folder)] = data.version.slice(0, 100);
  } catch {}
}
const entry = fs.existsSync(process.argv[1]);
console.log(JSON.stringify({ node: process.version, entry, installed }));
"""


def container_environment(box: DockerSandbox, project: JsProject) -> tuple[str, dict[str, str]]:
    """Node.js's version in ``box`` (``22.23.3``) and the packages installed there, by name with
    their version, read in a sandboxed run (K11). The runner's entry must be there, as after
    ``install_dependencies``."""
    entry = ENTRY[project.runner]
    run = box.run(["node", "-e", _ENVIRONMENT, entry])
    lines = run.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        found = json.loads(lines[-1]) if run.returncode == 0 and lines else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        said = run.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        error = said[0][:300] if said else run.outcome
        raise JsError(f"node did not report in the container: {error}")
    version = re.match(r"v?(\d+\.\d+\.\d+)", str(found.get("node", "")))
    if version is None:
        raise JsError("node --version gave no version")
    if found.get("entry") is not True:
        raise _no_runner(entry)
    listed = found.get("installed")
    installed = {str(k): str(v) for k, v in listed.items()} if isinstance(listed, dict) else {}
    return version.group(1), installed


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


class Tree(Protocol):
    """Where a project's tests run (K11): its files and its commands, as they see them.
    ``HostTree``: the host's copy, in the process sandbox (L2); ``VolumeTree``: a container
    sandbox's volume (L3)."""

    @property
    def root(self) -> PurePath:
        """The project's root."""
        ...

    @property
    def node(self) -> str:
        """Node.js, the program."""
        ...

    def outputs(self, out: Path) -> PurePath:
        """A directory for one run's files, kept in ``out`` on the host."""
        ...

    def write(self, files: Mapping[str, bytes]) -> None:
        """Writes ``files`` (POSIX paths relative to the project's root) into the project."""
        ...

    def read(self, path: PurePath) -> bytes | None:
        """A file a command left, or None."""
        ...

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        """Runs ``argv`` from the project's root."""
        ...


class HostTree:
    """The project on the host, its commands in the process sandbox (L2)."""

    def __init__(self, root: Path, box: ProcessSandbox) -> None:
        self.root = root
        self.box = box
        self._outputs: list[Path] = []

    @property
    def node(self) -> str:
        node = shutil.which("node")
        if node is None:
            raise JsError("node is not installed")
        return node

    def outputs(self, out: Path) -> Path:
        out.mkdir(parents=True, exist_ok=True)
        self._outputs.append(out)
        return out

    def write(self, files: Mapping[str, bytes]) -> None:
        for name, data in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(data)

    def read(self, path: PurePath) -> bytes | None:
        found = Path(path)
        return found.read_bytes() if found.is_file() else None

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        return self.box.run(argv, cwd=self.root, env=env, writable=tuple(self._outputs), stop=stop)


class VolumeTree:
    """The project in a container sandbox's volume, its commands in fresh containers with no
    network (L3, K11). Paths are POSIX, under ``/work``; a run's files go in ``.repro/runs``
    and are read back with ``docker cp``."""

    node: Final = "node"

    def __init__(self, box: DockerSandbox) -> None:
        self.box = box
        self.root = PurePosixPath(WORK)

    def outputs(self, out: Path) -> PurePosixPath:
        out.mkdir(parents=True, exist_ok=True)
        relative = f".repro/runs/{out.name}"
        self.box.write_files(relative, {})  # the directory, owned by the unprivileged user
        return self.root / relative

    def write(self, files: Mapping[str, bytes]) -> None:
        self.box.write_files(".", files)

    def read(self, path: PurePath) -> bytes | None:
        return self.box.read_file(PurePosixPath(path).relative_to(self.root).as_posix())

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        return self.box.run(argv, env=env, stop=stop)


def runner_argv(
    project: JsProject, report: str, *, node: str, script: str, extra: Sequence[str] = ()
) -> list[str]:
    """The runner's command, ``node script``, with its JSON report written to ``report`` and
    each test's start in it; ``extra`` comes last (the map's setup, K06; the files to run,
    K08)."""
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


def _relative(name: str, root: PurePath) -> str:
    if not isinstance(root, Path):  # a container's root (K11): POSIX, nothing here to resolve
        try:
            return PurePosixPath(name).relative_to(root).as_posix()
        except ValueError:
            return PurePosixPath(name).name
    try:
        return Path(name).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return PurePosixPath(Path(name).name).as_posix()


def _text(value: object) -> str | None:
    if isinstance(value, list):
        value = "\n".join(str(v) for v in value)
    text = _ANSI.sub("", str(value or "")).strip()
    return text[:_TEXT] or None


def read_tests(data: bytes, root: PurePath) -> tuple[dict[str, Reported], dict[str, str]]:
    """Each test, by ``<file relative to root>::<full name>``, and each test file that did not
    run, with its message. ``root`` is the project's root as the runner saw it: a host path,
    or a container's (a ``PurePosixPath``, K11)."""
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


def read_report(data: bytes, root: PurePath) -> dict[str, str]:
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
    tree: Tree,
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
    """One run of the project's tests in ``tree``, its report, map and calls kept in ``out``.
    ``mapped``: with the map's setup (K06); ``trace``: the functions to trace (K07); ``again``:
    in another order (base's second run, A2); ``files``: these test files alone."""
    side = Side(commit)
    env = {"NODE_OPTIONS": NODE_OPTIONS}
    unmapped = ""
    extra: list[str] = []
    try:
        here = tree.outputs(out)
        report, map_file, calls = (
            here / REPORT,
            here / jsmap.MAP_FILE,
            here / jstrace.TRACE_FILE,
        )
        if mapped or trace:
            env["REPRO_JS_MAP"] = str(map_file)
            if trace:
                env |= {
                    "REPRO_JS_TRACE_PLAN": json.dumps(dict(trace)),
                    "REPRO_JS_TRACE_OUT": str(calls),
                    "REPRO_JS_TRACE_SAMPLES": str(jstrace.SAMPLES),
                }
            extra, unmapped = _map_setup(project, tree, env, entry, trace=bool(trace))
        if again:
            extra += jstrace.shuffled(project.runner)
        extra += only(project.runner, files)
        script = _script(tree, project, entry)
        run = tree.run(
            runner_argv(project, str(report), node=tree.node, script=script, extra=extra),
            env=env,
            stop=stop,
        )
        side.ended = run.outcome
        data = _kept(tree, report, out)
        if data is None:
            # Node ends a crash with its version: the error is the line that names one.
            lines = run.stderr.decode("utf-8", "replace").strip().splitlines()
            error = ([line for line in lines if "Error" in line] or lines or [""])[-1].strip()
            raise JsError(
                f"the tests wrote no report ({run.outcome}, exit {run.returncode}): {error[:300]}"
            )
        tests, side.broken = read_tests(data, tree.root)
        side.outcomes = {test: found.outcome for test, found in tests.items()}
        side.starts = {test: found.start for test, found in tests.items() if found.start}
        side.messages = {test: found.message for test, found in tests.items() if found.message}
        side.durations = {test: found.duration_ms for test, found in tests.items()}
        if mapped:
            side.map = _read_map(None if unmapped else _kept(tree, map_file, out), unmapped)
        side.calls = _kept(tree, calls, out) or b""
    except JsError as exc:
        side.problem = str(exc)
    except SandboxError as exc:  # the container sandbox itself (K11), not the tests
        side.problem = f"the sandbox: {exc}"
    return side


def _script(tree: Tree, project: JsProject, entry: str | None) -> str:
    """The runner's entry point: ``entry`` (a test's own), or the project's under
    ``node_modules``."""
    return entry or str(tree.root / ENTRY[project.runner])


def _kept(tree: Tree, path: PurePath, out: Path) -> bytes | None:
    """A file a run left, read back; a container's is kept in ``out`` too, as the host's is."""
    data = tree.read(path)
    kept = out / path.name
    if data is not None and not kept.is_file():
        kept.write_bytes(data)
    return data


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
    host = HostTree(project.root, box)
    return run_tests(project, host, work / "box", commit, entry=entry, trace=trace, again=again)


def _map_setup(
    project: JsProject,
    tree: Tree,
    env: Mapping[str, str],
    entry: str | None,
    *,
    trace: bool = False,
) -> tuple[list[str], str]:
    """The runner's extra arguments for the map (K06), and why there is no map if there is none:
    the tests then run as they would without it."""
    try:
        if project.runner == "vitest":
            tree.write(jsmap.vitest_files(project.root, trace=trace))
            return ["--config", jsmap.WRAPPER], ""
        script = _script(tree, project, entry)
        shown = tree.run([tree.node, script, "--showConfig"], env=env)
        own = jsmap.jest_own_setup(shown.stdout)
        tree.write(jsmap.jest_files(trace=trace))
        return jsmap.jest_args(own, str(tree.root / jsmap.JEST_SETUP)), ""
    except (jsmap.MapError, OSError, SandboxError) as exc:
        return [], str(exc)


def _read_map(data: bytes | None, unmapped: str) -> jsmap.TestMap:
    if unmapped:
        return jsmap.TestMap(problem=unmapped)
    if data is None:
        return jsmap.TestMap(problem="the setup file wrote no map")
    try:
        return jsmap.read_map(data)
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
