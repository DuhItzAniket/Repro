"""``repro doctor``: can this machine run Repro, and what should be fixed if not?

Each check is ``ok``, ``warn`` or ``fail``. Only required checks fail; a missing optional tool is
a warning that says what Repro does without it. Tools are probed with fixed argument vectors,
without a shell and with timeouts, through an injected ``Probe``, so every outcome is tested
without the tool installed. Doctor leaves the machine as it found it: it does not create the
data directory, only reads the Windows registry, and its write test removes its own file.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from repro.logs import get_logger
from repro.paths import RUN_ROOT_BUDGET
from repro.sandbox import containment
from repro.store.db import MIN_SQLITE, sqlite_version

Status = Literal["ok", "warn", "fail"]
Version = tuple[int, ...]

MIN_PYTHON: Version = (3, 12)
MIN_GIT: Version = (2, 40)
UV_BASELINE: Version = (0, 13)
UV_WINDOWS_FIX: Version = (0, 12, 18)
TIMEOUT_S = 15.0

log = get_logger("doctor")


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    summary: str
    hint: str | None = None
    detail: str | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    returncode: int
    stdout: str
    stderr: str


class ProbeTimeoutError(Exception):
    """The tool did not answer in time."""


class Probe(Protocol):
    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult | None:
        """Runs ``argv``; ``None`` when its program is not installed."""
        ...


class SubprocessProbe:
    """Runs a program found on ``PATH``: no shell, no stdin, text output, a timeout."""

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult | None:
        program = shutil.which(argv[0])
        if program is None:
            return None
        try:
            done = subprocess.run(  # noqa: S603 - a fixed argument vector, no shell
                [program, *argv[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProbeTimeoutError(" ".join(argv)) from exc
        except OSError as exc:
            return ProbeResult(127, "", str(exc))
        return ProbeResult(done.returncode, done.stdout, done.stderr)


def parse_version(text: str, pattern: str) -> Version | None:
    """The numeric groups of the first match of ``pattern`` in ``text``."""
    match = re.search(pattern, text)
    if match is None:
        return None
    return tuple(int(group) for group in match.groups() if group is not None)


def show(version: Version) -> str:
    return ".".join(str(part) for part in version)


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def check_python(version: Version, implementation: str) -> Check:
    found = f"{implementation} {show(version)}"
    if version[:2] >= MIN_PYTHON:
        return Check("python", "ok", found, required=True)
    return Check(
        "python",
        "fail",
        f"{found} is older than {show(MIN_PYTHON)}",
        hint="Repro needs Python 3.12 or newer (sys.monitoring): uv python install 3.13",
        required=True,
    )


def check_sqlite(version: Version) -> Check:
    """The SQLite library Python was built with: the store needs STRICT tables (3.37)."""
    found = f"SQLite {show(version)}"
    if version >= MIN_SQLITE:
        return Check("sqlite", "ok", found, required=True)
    return Check(
        "sqlite",
        "fail",
        f"{found} is older than {show(MIN_SQLITE)}",
        hint="Use a Python built with a newer SQLite: uv python install 3.13",
        required=True,
    )


def check_git(probe: Probe) -> Check:
    hint = f"Install git {show(MIN_GIT)} or newer (https://git-scm.com/downloads)"
    try:
        result = probe.run(["git", "--version"], timeout=TIMEOUT_S)
    except ProbeTimeoutError:
        return Check("git", "fail", "git --version timed out", hint=hint, required=True)
    if result is None:
        return Check("git", "fail", "not found on PATH", hint=hint, required=True)
    version = parse_version(result.stdout, r"git version (\d+)\.(\d+)(?:\.(\d+))?")
    if result.returncode != 0 or version is None:
        problem = _first_line(result.stderr) or _first_line(result.stdout) or "no output"
        return Check("git", "fail", f"git --version failed: {problem}", hint=hint, required=True)
    if version < MIN_GIT:
        return Check(
            "git", "fail", f"git {show(version)} is older than {show(MIN_GIT)}", hint, required=True
        )
    return Check("git", "ok", f"git {show(version)}", required=True)


def check_uv(probe: Probe) -> Check:
    install = "Install uv 0.13 or newer (https://docs.astral.sh/uv/)"
    why = "Repro provisions target environments with it from Stage D"
    try:
        result = probe.run(["uv", "--version"], timeout=TIMEOUT_S)
    except ProbeTimeoutError:
        return Check("uv", "warn", "uv --version timed out", hint=install)
    if result is None:
        return Check("uv", "warn", "not found on PATH", hint=f"{install}. {why}")
    version = parse_version(result.stdout, r"uv (\d+)\.(\d+)\.(\d+)")
    if result.returncode != 0 or version is None:
        problem = _first_line(result.stderr) or _first_line(result.stdout) or "no output"
        return Check("uv", "warn", f"uv --version failed: {problem}", hint=install)
    found = f"uv {show(version)}"
    if version < UV_WINDOWS_FIX:
        return Check(
            "uv",
            "warn",
            f"{found} is older than {show(UV_WINDOWS_FIX)}",
            hint=f"Upgrade (uv self update): {show(UV_WINDOWS_FIX)} fixed a wheel path traversal "
            "on Windows",
        )
    if version < UV_BASELINE:
        return Check(
            "uv",
            "warn",
            f"{found} is older than the toolchain baseline {show(UV_BASELINE)}",
            hint="Upgrade: uv self update",
        )
    return Check("uv", "ok", found)


def check_docker(probe: Probe, *, windows: bool) -> Check:
    without = (
        "without it Repro runs target code in a process sandbox and reports isolation: process"
    )
    install = (
        "Install Docker Desktop with the WSL2 backend"
        if windows
        else "Install Docker Engine (https://docs.docker.com/engine/install/)"
    )
    try:
        result = probe.run(["docker", "version", "--format", "{{json .}}"], timeout=TIMEOUT_S)
    except ProbeTimeoutError:
        return Check(
            "docker", "warn", "docker version timed out", hint="Check that Docker is running"
        )
    if result is None:
        return Check("docker", "warn", "not found on PATH", hint=f"{install}; {without}")
    try:
        info = json.loads(result.stdout.strip() or "null")
    except json.JSONDecodeError:
        info = None
    client = info.get("Client") if isinstance(info, dict) else None
    server = info.get("Server") if isinstance(info, dict) else None
    client_version = client.get("Version") if isinstance(client, dict) else None
    if not isinstance(server, dict) or not server.get("Version"):
        found = f"Docker CLI {client_version}" if client_version else "Docker CLI"
        start = "Start Docker Desktop" if windows else "Start the Docker service"
        problem = _first_line(result.stderr)
        return Check(
            "docker",
            "warn",
            f"{found}, but the daemon is not reachable",
            hint=f"{start}; {without}",
            detail=problem or None,
        )
    os_name, arch = str(server.get("Os", "?")), str(server.get("Arch", "?"))
    kernel = server.get("KernelVersion")
    found = f"Docker {server['Version']} ({os_name}/{arch})"
    detail = f"kernel {kernel}" if kernel else None
    if os_name != "linux":
        return Check(
            "docker",
            "warn",
            f"{found}: not Linux containers",
            hint="Switch Docker to Linux containers: Repro's sandbox images are Linux",
            detail=detail,
        )
    return Check("docker", "ok", found, detail=detail)


def check_containment(how: str | None) -> Check:
    """Whether this machine can contain a command's processes (L2, ADR-0004)."""
    network = "the network is detected, not enforced, until a container runs it (L3)"
    if how is None:
        return Check(
            "containment",
            "warn",
            "commands run at L1: not contained",
            hint="Repro contains commands on Windows and POSIX; this platform has neither",
            detail=network,
        )
    return Check("containment", "ok", f"L2: {how}", detail=network)


def check_data_dir(path: Path) -> Check:
    """Writable if it exists (one temporary file, removed), else creatable where it would go."""
    if path.exists():
        if not path.is_dir():
            return Check(
                "data dir",
                "fail",
                f"{path} is not a directory",
                hint="Set REPRO_DATA_DIR",
                required=True,
            )
        try:
            with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True):
                pass
        except OSError as exc:
            return Check(
                "data dir",
                "fail",
                f"{path} is not writable: {exc.strerror or exc}",
                hint="Fix its permissions or set REPRO_DATA_DIR",
                required=True,
            )
        return Check("data dir", "ok", f"{path} (writable)", required=True)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        return Check("data dir", "ok", f"{path} (created on first use)", required=True)
    return Check(
        "data dir",
        "fail",
        f"{path} cannot be created under {parent}",
        hint="Set REPRO_DATA_DIR to a writable directory",
        required=True,
    )


def check_run_root(path: Path, *, windows: bool) -> Check:
    """On Windows, short enough to leave room for a target repository's own paths."""
    length = len(str(path))
    if windows and length > RUN_ROOT_BUDGET:
        return Check(
            "run root",
            "warn",
            f"{path} is {length} characters (budget {RUN_ROOT_BUDGET})",
            hint="Set REPRO_RUN_ROOT to a short path such as C:\\r: target repositories add "
            "their own paths under it",
        )
    return Check("run root", "ok", f"{path} ({length} characters)")


def check_long_paths(enabled: bool | None) -> Check:
    """Windows only: whether paths over 260 characters work for Python and the tools."""
    if enabled:
        return Check("long paths", "ok", "Windows long paths are enabled")
    state = "off" if enabled is False else "unknown (the registry could not be read)"
    return Check(
        "long paths",
        "warn",
        f"Windows long paths are {state}",
        hint="Enable them (LongPathsEnabled, Group Policy or registry, needs an administrator), "
        "or keep the run root short. Repro passes -c core.longpaths=true to git itself",
    )


if sys.platform == "win32":
    import winreg

    def windows_long_paths() -> bool | None:
        """Reads ``LongPathsEnabled`` from the registry; ``None`` when it cannot."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
            ) as key:
                value: object = winreg.QueryValueEx(key, "LongPathsEnabled")[0]
        except OSError:
            return None
        return value == 1

else:

    def windows_long_paths() -> bool | None:
        """Long paths are a Windows setting: there is nothing to read elsewhere."""
        return None


@dataclass(frozen=True, slots=True)
class Machine:
    """What doctor inspects; the real machine by default, a fake in tests."""

    probe: Probe = field(default_factory=SubprocessProbe)
    python: Version = tuple(sys.version_info[:3])
    sqlite: Version = field(default_factory=sqlite_version)
    implementation: str = platform.python_implementation()
    windows: bool = os.name == "nt"
    long_paths: Callable[[], bool | None] = windows_long_paths


@dataclass(frozen=True, slots=True)
class Report:
    checks: tuple[Check, ...]
    version: str
    system: str

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    def to_json(self) -> str:
        return json.dumps(
            {
                "repro": self.version,
                "system": self.system,
                "ok": self.ok,
                "checks": [asdict(check) for check in self.checks],
            },
            indent=2,
            ensure_ascii=True,
        )

    def to_text(self) -> str:
        lines = [f"repro {self.version} doctor - {self.system}"]
        width = max(len(check.name) for check in self.checks)
        for check in self.checks:
            lines.append(f"  {check.status:<4}  {check.name:<{width}}  {check.summary}")
            if check.detail:
                lines.append(f"  {'':<4}  {'':<{width}}  {check.detail}")
            if check.hint and check.status != "ok":
                lines.append(f"  {'':<4}  {'':<{width}}  -> {check.hint}")
        failed = [check.name for check in self.checks if check.status == "fail"]
        if failed:
            lines.append(f"Not ready: {', '.join(failed)} failed.")
        else:
            warned = sum(check.status == "warn" for check in self.checks)
            lines.append(
                "Ready: every required check passed"
                + (f" ({warned} warning{'s' if warned != 1 else ''})." if warned else ".")
            )
        return "\n".join(lines)


def system_name() -> str:
    return f"{platform.system()} {platform.release()} {platform.machine()}".strip()


def diagnose(
    *,
    data_dir: Path,
    run_root: Path,
    version: str,
    machine: Machine | None = None,
    extra: Sequence[Check] = (),
) -> Report:
    """Runs every check. ``extra`` comes first (a configuration problem, for example)."""
    machine = Machine() if machine is None else machine
    checks: list[Check] = [
        *extra,
        check_python(machine.python, machine.implementation),
        check_sqlite(machine.sqlite),
        check_git(machine.probe),
        check_uv(machine.probe),
        check_docker(machine.probe, windows=machine.windows),
        check_containment(containment()),
        check_data_dir(data_dir),
        check_run_root(run_root, windows=machine.windows),
    ]
    if machine.windows:
        checks.append(check_long_paths(machine.long_paths()))
    for check in checks:
        log.debug("checked", extra={"fields": {"check": check.name, "status": check.status}})
    return Report(tuple(checks), version, system_name())
