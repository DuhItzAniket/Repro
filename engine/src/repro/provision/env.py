"""A side's environment (D03; ADR-0004, ARCHITECTURE §8), in two steps so that no target code
ever runs with network access:

1. **Dependencies** (network, no target code): a virtual environment with the project's
   requirements and build requirements, from wheels only (``--no-build``: a source distribution
   would run its build code), from the index Repro names, with uv's configuration files
   ignored. It holds nothing of the project, so it is cached by the digest of what was asked
   for (interpreter, platform, requirements, cut-off date) and shared by both sides and by later
   runs.
2. **The project** (in the sandbox, no network): a copy of that environment for the side, and
   the project installed into it, editable and offline, by its own build backend: the first
   moment target code runs.

The host never runs an environment's interpreter once packages are in it: a package may ship a
``.pth`` file whose code runs at start-up. The Python version comes from the environment's base
interpreter (``pyvenv.cfg``'s ``home``), run with ``-I -S``: Repro's own interpreter, without
site-packages. Installed packages are counted from their ``.dist-info`` directories.

uv cannot use a read-only cache (measured in D03: it opens files in the cache for writing
whenever it initialises one), so the shared, read-only thing is the dependencies' environment,
copied per side, not a package cache.
"""

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.provision.project import Project
from repro.sandbox import DockerSandbox, ProcessSandbox
from repro.sandbox.docker import TMP

#: The index every dependency comes from.
PYPI: Final = "https://pypi.org/simple"
#: The interpreter both sides use (ARCHITECTURE §8: the same on both, 3.12 or newer).
PYTHON: Final = "3.13"
#: Where an environment is in a container: the same path in every one, so a copy still works.
ENV_MOUNT: Final = "/opt/env"
_DONE: Final = ".complete"
_TIMEOUT_S: Final = 900.0


class ProvisionError(Exception):
    """The environment could not be provisioned; the message is the reason (UNVERIFIABLE)."""


def environment_missing(side: str, reason: str) -> dict[str, Any]:
    """The ``missing.recorded`` payload for a side whose environment could not be provisioned
    (a ``ProvisionError`` or a ``ProjectError``): the change is UNVERIFIABLE, never passed."""
    return {
        "missing": {
            "reason": "environment_failed",
            "targets": [],
            "detail": f"{side}: {reason}"[:1000],
            "resolution": (
                "Make the project installable from the package index, with wheels for its "
                "dependencies, and its own build working offline"
            ),
        }
    }


@dataclass(frozen=True, slots=True)
class EnvSpec:
    """What a dependencies' environment holds."""

    python: str
    platform: str
    requirements: tuple[str, ...]
    exclude_newer: str | None = None

    def text(self) -> str:
        return "".join(f"{line}\n" for line in self.requirements)

    @property
    def key(self) -> str:
        cut_off = self.exclude_newer or "-"
        head = f"python {self.python}\nplatform {self.platform}\ncut-off {cut_off}\n"
        return hashlib.sha256((head + self.text()).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Environment:
    side: str
    project: Project
    python: str  # the interpreter tests run with, as the sandbox sees it
    python_version: str
    installed_packages: int
    cache_hit: bool
    duration_ms: int

    def payload(self) -> dict[str, Any]:
        """The ``env.provisioned`` payload."""
        return {
            "side": self.side,
            "project_kind": self.project.kind,
            "python_version": self.python_version,
            "lock_sha256": self.project.lock_sha256,
            "installed_packages": self.installed_packages,
            "cache_hit": self.cache_hit,
            "duration_ms": self.duration_ms,
        }


def spec_for(
    project: Project, *, platform: str, exclude_newer: str | None, python: str = PYTHON
) -> EnvSpec:
    return EnvSpec(
        python=python,
        platform=platform,
        requirements=(*project.requirements, *project.build_requires),
        exclude_newer=exclude_newer,
    )


#: Prints the interpreter's full version; run with ``-I -S`` (no site-packages, no ``.pth``).
_VERSION = "import platform; print(platform.python_version())"


def pyvenv_home(pyvenv_cfg: str) -> str:
    """The base interpreter's directory a ``pyvenv.cfg`` records."""
    for line in pyvenv_cfg.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return value.strip()
    raise ProvisionError("the environment's pyvenv.cfg names no base interpreter")


def _tail(text: bytes, lines: int = 6) -> str:
    kept = text.decode("utf-8", "replace").strip().splitlines()[-lines:]
    return " | ".join(line.strip() for line in kept) or "no output"


def _install_args(python: str, index: str, spec: EnvSpec, requirements: str) -> list[str]:
    args = [
        "pip", "install", "--python", python, "--no-build", "--link-mode", "copy",
        "--index-url", index, "-r", requirements,
    ]  # fmt: skip
    if spec.exclude_newer:
        args += ["--exclude-newer", spec.exclude_newer]
    return args


def _project_install(python: str) -> list[str]:
    """The project, editable, offline, without its dependencies (they are installed)."""
    return [
        "uv", "pip", "install", "--python", python, "--offline", "--no-index", "--no-deps",
        "--no-build-isolation", "--link-mode", "copy", "-e", ".",
    ]  # fmt: skip


class HostProvisioner:
    """Environments on the host, for the process sandbox (L2), with uv's Python ``python``
    (3.13 unless asked: the plugin's own tests use 3.12 to 3.15)."""

    def __init__(
        self,
        cache: Path,
        *,
        uv: str = "uv",
        index: str = PYPI,
        exclude_newer: str | None = None,
        python: str = PYTHON,
    ) -> None:
        self.cache = cache
        self.python = python
        self.uv = uv
        self.index = index
        self.exclude_newer = exclude_newer

    def _uv(self, *args: str, cwd: Path) -> None:
        env = {**os.environ, "UV_NO_CONFIG": "1", "UV_CACHE_DIR": str(self.cache / "uv")}
        try:
            done = subprocess.run(  # noqa: S603 - uv, with Repro's own arguments
                [self.uv, *args],
                cwd=cwd,
                env=env,
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionError(f"uv {args[0]}: {exc}") from None
        if done.returncode != 0:
            raise ProvisionError(f"installing the dependencies failed: {_tail(done.stderr)}")

    def dependencies(self, spec: EnvSpec) -> tuple[Path, bool]:
        """The dependencies' environment for ``spec``, built if needed; whether it was cached."""
        final = self.cache / "envs" / spec.key[:32]
        if (final / _DONE).is_file():
            return final, True
        building = self.cache / "envs" / f"building-{uuid.uuid4().hex[:12]}"
        building.mkdir(parents=True)
        try:
            (building / "requirements.txt").write_text(spec.text(), encoding="utf-8")
            venv = building / "venv"
            self._uv("venv", "--relocatable", "--python", spec.python, str(venv), cwd=building)
            python = str(_venv_python(venv))
            self._uv(*_install_args(python, self.index, spec, "requirements.txt"), cwd=building)
            (building / _DONE).write_text(spec.key, encoding="utf-8")
            try:
                building.rename(final)
            except OSError:  # built meanwhile by another run: use that one
                if not (final / _DONE).is_file():
                    raise
        finally:
            if building.exists():
                shutil.rmtree(building, ignore_errors=True)
        return final, False

    def provision(self, side: str, project: Project, sandbox: ProcessSandbox) -> Environment:
        started = time.monotonic()
        spec = spec_for(
            project, platform=_host_platform(), exclude_newer=self.exclude_newer, python=self.python
        )
        cached, hit = self.dependencies(spec)
        env_dir = sandbox.work / "env"
        shutil.copytree(cached / "venv", env_dir, symlinks=True)
        python = _venv_python(env_dir)
        home = Path(pyvenv_home((env_dir / "pyvenv.cfg").read_text(encoding="utf-8")))
        version = _host_version(home)
        if project.installable:
            run = sandbox.run(
                _project_install(str(python)),
                cwd=project.root,
                env={"UV_NO_CONFIG": "1", "UV_CACHE_DIR": str(sandbox.work / "uv-cache")},
            )
            if run.returncode != 0:
                reason = _tail(run.stderr) if run.outcome == "exited" else run.outcome
                raise ProvisionError(f"the project's own install failed: {reason}")
        return Environment(
            side=side,
            project=project,
            python=str(python),
            python_version=version,
            installed_packages=len(list(env_dir.glob("**/site-packages/*.dist-info"))),
            cache_hit=hit,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


class DockerProvisioner:
    """Environments in Docker volumes, for the container sandbox (L3)."""

    def __init__(
        self,
        image: str,
        *,
        docker: str = "docker",
        index: str = PYPI,
        exclude_newer: str | None = None,
    ) -> None:
        self.image = image
        self.docker = docker
        self.index = index
        self.exclude_newer = exclude_newer

    def _docker(
        self,
        *args: str,
        stdin: bytes | None = None,
        check: bool = True,
        what: str = "a Docker step",
    ) -> bytes:
        try:
            done = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
                [self.docker, *args],
                input=stdin,
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProvisionError(f"docker {args[0]}: {exc}") from None
        if check and done.returncode != 0:
            raise ProvisionError(f"{what} failed: {_tail(done.stderr)}")
        return done.stdout

    def _in(
        self,
        volume: str,
        command: str,
        *,
        network: bool = False,
        root: bool = False,
        stdin: bytes | None = None,
        check: bool = True,
        what: str = "a Docker step",
    ) -> bytes:
        """A shell command in a helper container with ``volume`` at the environment's path:
        hardened like a sandbox, unprivileged unless ``root`` (only to hand the volume to the
        unprivileged user), and with no network unless ``network``."""
        if root:
            isolation = ["--network", "none", "--user", "0:0"]
        else:
            isolation = [
                *([] if network else ["--network", "none"]),
                "--read-only", "--tmpfs", f"{TMP}:rw,exec,size=512m", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "1000:1000",
            ]  # fmt: skip
        return self._docker(
            "run", "--rm", "-i", *isolation, "-v", f"{volume}:{ENV_MOUNT}",
            "-e", f"HOME={TMP}", "-e", "UV_NO_CONFIG=1", "-e", f"UV_CACHE_DIR={TMP}/uv",
            "--entrypoint", "sh", self.image, "-c", command,
            stdin=stdin, check=check, what=what,
        )  # fmt: skip

    def dependencies(self, spec: EnvSpec) -> tuple[str, bool]:
        """The volume holding the dependencies' environment for ``spec``; whether it was cached."""
        volume = f"repro-env-{spec.key[:24]}"
        done = self._in(volume, f"test -f {ENV_MOUNT}/{_DONE} && echo yes", check=False)
        if done.strip() == b"yes":
            return volume, True
        self._docker("volume", "rm", "-f", volume, check=False)
        self._docker("volume", "create", volume)
        self._in(volume, f"chown 1000:1000 {ENV_MOUNT}", root=True)
        self._in(volume, f"cat > {ENV_MOUNT}/requirements.txt", stdin=spec.text().encode())
        install = " ".join(
            _install_args(
                f"{ENV_MOUNT}/venv/bin/python", self.index, spec, f"{ENV_MOUNT}/requirements.txt"
            )
        )
        script = (
            f"uv venv {ENV_MOUNT}/venv --python /usr/local/bin/python3 && uv {install} "
            f"&& echo {spec.key} > {ENV_MOUNT}/{_DONE}"
        )
        try:  # the only step with network: no target code runs in it
            self._in(volume, script, network=True, what="installing the dependencies")
        except ProvisionError:
            self._docker("volume", "rm", "-f", volume, check=False)
            raise
        return volume, False

    def provision(self, side: str, project: Project, sandbox: DockerSandbox) -> Environment:
        started = time.monotonic()
        spec = spec_for(project, platform=f"linux, {self.image}", exclude_newer=self.exclude_newer)
        cached, hit = self.dependencies(spec)
        env_volume = f"{sandbox.volume}-env"
        self._docker("volume", "create", env_volume, what="creating the side's environment")
        sandbox.adopt_volume(env_volume, ENV_MOUNT)
        self._in(env_volume, f"chown 1000:1000 {ENV_MOUNT}", root=True)
        self._docker(
            "run", "--rm", "--network", "none", "--user", "1000:1000",
            "-v", f"{cached}:/from:ro", "-v", f"{env_volume}:{ENV_MOUNT}",
            "--entrypoint", "cp", self.image, "-a", "/from/.", f"{ENV_MOUNT}/",
            what="copying the dependencies' environment",
        )  # fmt: skip
        python = f"{ENV_MOUNT}/venv/bin/python"
        home = pyvenv_home(self._in(env_volume, f"cat {ENV_MOUNT}/venv/pyvenv.cfg").decode())
        version = self._in(env_volume, f"{home}/python3 -I -S -c '{_VERSION}'").decode().strip()
        if project.installable:
            run = sandbox.run(
                _project_install(python), env={"UV_NO_CONFIG": "1", "UV_CACHE_DIR": f"{TMP}/uv"}
            )
            if run.returncode != 0:
                reason = _tail(run.stderr) if run.outcome == "exited" else run.outcome
                raise ProvisionError(f"the project's own install failed: {reason}")
        count = self._in(
            env_volume, f"ls -d {ENV_MOUNT}/venv/lib/python*/site-packages/*.dist-info | wc -l"
        )
        return Environment(
            side=side,
            project=project,
            python=python,
            python_version=version,
            installed_packages=int(count.strip() or 0),
            cache_hit=hit,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def _host_version(home: Path) -> str:
    """The full version of a base interpreter (never an environment's: see the module)."""
    executable = home / ("python.exe" if sys.platform == "win32" else "python3")
    try:
        done = subprocess.run(  # noqa: S603 - the base interpreter uv installed, isolated
            [str(executable), "-I", "-S", "-c", _VERSION],
            capture_output=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProvisionError(f"the base interpreter cannot report its version: {exc}") from None
    return done.stdout.decode().strip()


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _host_platform() -> str:
    return f"{sys.platform}-{platform.machine().lower()}"
