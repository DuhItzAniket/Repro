"""The container sandbox: L3, or L4 under gVisor (ADR-0004, ARCHITECTURE §8).

A commit is streamed into a Docker volume of its own: its tree object as a tar stream
(``gitops.tar_tree``: modes and symbolic links exactly as git stores them, whatever the host),
unpacked by a helper container with no network and owned by an unprivileged user. Repro's own
audit hook goes into a volume of its own the same way, owned by root and mounted read-only, so
nothing of the host is bind-mounted. Each command then runs in a fresh container that:

- has **no network** (``--network none``): the only level at which Repro reports the network as
  ``enforced``;
- has a **read-only root** with a ``/tmp`` tmpfs mounted ``exec`` (A08: ``noexec`` breaks real
  suites), so writes land only in the volume or ``/tmp``;
- drops **every capability**, cannot gain privileges, and runs as uid 1000;
- is limited in **processes, memory (no swap) and CPU**, and killed at its wall-clock timeout.

With ``runtime="runsc"``, the containers that run the target's code run under gVisor, a kernel
in user space between them and the host's (L4, H03; installed as https://gvisor.dev/docs/
user_guide/install/ says, checked 2026-10-17). The sandbox checks that Docker has the runtime
before it starts. Any other runtime named is passed on, and its level is what a probe sees
(K10): a container of that runtime whose kernel is not the engine's has a kernel of its own, a
microVM such as Kata Containers' (L5); otherwise the level stays L3. The name is never trusted
for it: ``scripts/kata/setup.sh`` names Kata's runtime ``kata``, but any name would do.

L1 detection still runs inside, so blocked attempts are still recorded. What a command leaves
(its audit log, result files) is read back with ``docker cp`` after it ends: no host directory
is writable from inside.
"""

import io
import json
import posixpath
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from repro.gitops import Git, TarredTree, tar_tree
from repro.sandbox.detect import (
    AUDIT_LOG_ENV,
    AUDIT_ROOTS_ENV,
    HOOK_DIR,
    Detections,
    read_detections,
)
from repro.sandbox.limits import Limits
from repro.sandbox.process import (
    HASH_SEED,
    POLL_S,
    Execution,
    Outcome,
    SandboxError,
    read_head,
)

#: Python 3.13 with uv on Debian bookworm, pinned by digest (A08 measured with this image).
DEFAULT_IMAGE: Final = (
    "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
    "@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca"
)
WORK: Final = "/work"
#: The container's own tmpfs, never the host's.
TMP: Final = "/tmp"  # noqa: S108
HOOK_MOUNT: Final = "/opt/repro/hook"
USER: Final = "1000:1000"
#: ``/tmp`` in the container: tmpfs, ``exec`` (A08), counted against the memory limit.
TMPFS_SIZE: Final = "512m"
#: How long Docker commands that only manage containers and volumes may take.
DOCKER_TIMEOUT_S: Final = 300.0
#: ``docker run`` exits 125 when Docker itself could not run the container.
DOCKER_FAILED: Final = 125


def hook_archive() -> bytes:
    """Repro's hook (``sandbox/_hook``) as a tar archive: its files, readable by everyone.

    Copied into a volume rather than bind-mounted: H06 found the hook of a Repro installed with
    ``uv tool install`` unreadable to the container's user on Docker Desktop for Windows ("Input/
    output error"), so no test ran in a container."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for path in sorted(p for p in HOOK_DIR.iterdir() if p.is_file()):
            data = path.read_bytes()
            info = tarfile.TarInfo(path.name)
            info.size, info.mode, info.mtime = len(data), 0o644, int(path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
    return archive.getvalue()


def docker_available(docker: str = "docker") -> bool:
    """Whether a Docker daemon with Linux containers answers."""
    try:
        done = subprocess.run(  # noqa: S603 - docker, by name
            [docker, "version", "--format", "{{.Server.Os}}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and done.stdout.strip() == b"linux"


#: gVisor's Docker runtime: the one that makes a container L4.
GVISOR: Final = "runsc"
#: The names a Kata Containers runtime goes by, for ``run.started`` (K10); its level is probed.
KATA_NAMES: Final = ("kata", "io.containerd.kata")


class DockerSandbox:
    """Runs commands at L3 on commit ``commit`` of ``git``'s repository, held in a volume."""

    backend: Final = "docker"

    def __init__(
        self,
        work: Path,
        git: Git,
        commit: str,
        *,
        limits: Limits | None = None,
        image: str = DEFAULT_IMAGE,
        docker: str = "docker",
        runtime: str | None = None,
    ) -> None:
        self.work = work
        self.limits = limits or Limits()
        self.image = image
        self.docker = docker
        self.runtime = runtime
        self.volume = f"repro-{uuid.uuid4().hex[:12]}"
        #: Repro's hook, mounted read-only in every command's container.
        self.hook = f"repro-hook-{self.volume[6:]}"
        #: Volumes adopted for every command's container: volume -> path (an environment).
        self.mounts: dict[str, str] = {}
        #: Directories put on every command's import path after the hook: the snapshot's own,
        #: when the image's environment is used as it is (J04).
        self.python_path: tuple[str, ...] = ()
        #: Variables every command gets, under the caller's own: an environment's ``PATH`` (J04).
        self.variables: dict[str, str] = {}
        self._runs = 0
        self._lock = threading.Lock()
        self.work.mkdir(parents=True, exist_ok=True)
        self._server = self._docker("version", "--format", "{{.Server.Version}}").decode().strip()
        if runtime is not None:
            self._check_runtime(runtime)
        if not self._docker("image", "inspect", "--format", "{{.Id}}", self.image, check=False):
            self._docker("pull", "--quiet", self.image)
        #: Whether the runtime gives each container a kernel of its own (K10): probed.
        self.own_kernel = runtime not in (None, GVISOR) and self._own_kernel(runtime)
        self._docker("volume", "create", self.volume)
        try:
            self._load_hook()
            self.tree = self._load(git, commit)
        except BaseException:
            self.close()
            raise

    @property
    def isolation_level(self) -> str:
        """L4 under gVisor; L5 when the runtime gave a container a kernel of its own (a microVM,
        K10); else L3."""
        if self.runtime == GVISOR:
            return "L4"
        return "L5" if self.own_kernel else "L3"

    def _own_kernel(self, runtime: str) -> bool:
        """Whether a container of ``runtime`` runs on a kernel other than the engine's: its
        ``uname -r`` from Repro's own image, with no network, against ``docker info``'s."""
        host = self._docker("info", "--format", "{{.KernelVersion}}").decode().strip()
        guest = self._docker(
            "run", "--rm", "--runtime", runtime, "--network", "none",
            "--entrypoint", "uname", self.image, "-r", check=False,
        ).decode().strip()  # fmt: skip
        return bool(host) and bool(guest) and guest != host

    def _check_runtime(self, runtime: str) -> None:
        listed = self._docker("info", "--format", "{{json .Runtimes}}").decode().strip()
        try:
            known = json.loads(listed) if listed else {}
        except ValueError:
            known = {}
        if not isinstance(known, dict) or runtime not in known:
            have = ", ".join(sorted(known)) if isinstance(known, dict) else "none listed"
            raise SandboxError(
                f"Docker has no runtime {runtime!r} (it has: {have}); gVisor's is installed "
                "with `runsc install` (https://gvisor.dev/docs/user_guide/install/)"
            )

    # -- the volume --------------------------------------------------------------------------

    def _docker(self, *args: str, check: bool = True, stdin: bytes | None = None) -> bytes:
        try:
            done = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
                [self.docker, *args],
                input=stdin,
                capture_output=True,
                timeout=DOCKER_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError(f"docker {args[0]}: {exc}") from None
        if check and done.returncode != 0:
            problem = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise SandboxError(f"docker {args[0]} failed: {problem[-1] if problem else '?'}")
        return done.stdout

    def _load_hook(self) -> None:
        """Copies Repro's hook into its own volume, owned by root (``hook_archive``)."""
        self._docker("volume", "create", self.hook)
        self._docker(
            "run", "--rm", "-i", "--network", "none", "-v", f"{self.hook}:{HOOK_MOUNT}",
            "--user", "0:0", "--entrypoint", "tar", self.image, "-x", "-C", HOOK_MOUNT,
            stdin=hook_archive(),
        )  # fmt: skip

    def _load(self, git: Git, commit: str) -> TarredTree:
        """Streams the commit into the volume, owned by the unprivileged user."""
        unpack = (
            f"tar -x -C {WORK} --no-same-owner && mkdir -p {WORK}/.repro && chown -R {USER} {WORK}"
        )
        copy = [
            self.docker, "run", "--rm", "-i", "--network", "none",
            "-v", f"{self.volume}:{WORK}", "--user", "0:0",
            "--entrypoint", "sh", self.image, "-c", unpack,
        ]  # fmt: skip
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(  # noqa: S603 - docker, with Repro's own arguments
                copy,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=errors,
            )
            if process.stdin is None:  # pragma: no cover - a pipe was asked for
                raise SandboxError("docker run has no stdin")
            try:
                tree = tar_tree(git, commit, process.stdin)
                process.stdin.close()
                code = process.wait(timeout=DOCKER_TIMEOUT_S)
            except BaseException:
                process.kill()
                process.wait()
                raise
            if code != 0:
                errors.seek(0)
                problem = errors.read().decode("utf-8", "replace").strip().splitlines()
                raise SandboxError(
                    f"copying the snapshot failed: {problem[-1] if problem else code}"
                )
        return tree

    def overlay(self, name: str, files: Mapping[str, bytes]) -> str:
        """A copy of the snapshot at ``.repro/<name>`` with ``files`` (POSIX paths relative to
        the snapshot) written over it; returns its path relative to the snapshot."""
        if not name.isidentifier():
            raise SandboxError(f"{name!r} is not a plain name")
        relative = f".repro/{name}"
        target = self.container_path(relative)
        script = (
            f"set -e; mkdir -p {target}; cd {WORK}; "
            f"tar --exclude=./.repro -cf - . | tar -x -C {target}; "
            f"tar -x -C {target} --no-same-owner"
        )
        self._untar(script, files, "the overlay")
        return relative

    def write_files(self, directory: str, files: Mapping[str, bytes]) -> None:
        """Writes ``files`` (POSIX paths relative to ``directory``, itself relative to the
        snapshot) into the volume, owned by the unprivileged user."""
        target = self.container_path(directory)
        inside = {f"{directory}/{path}": data for path, data in files.items()}
        self._untar(
            f"set -e; mkdir -p {target}; tar -x -C {WORK} --no-same-owner", inside, directory
        )

    def _untar(self, script: str, files: Mapping[str, bytes], what: str) -> None:
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            for path, data in sorted(files.items()):
                inside = self.container_path(path)  # refuses paths outside the snapshot
                info = tarfile.TarInfo(inside[len(WORK) + 1 :])
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))
        command = [
            self.docker, "run", "--rm", "-i", "--network", "none",
            "-v", f"{self.volume}:{WORK}", "--user", USER,
            "--entrypoint", "sh", self.image, "-c", script,
        ]  # fmt: skip
        try:
            done = subprocess.run(  # noqa: S603 - docker, with Repro's own arguments
                command,
                input=archive.getvalue(),
                capture_output=True,
                timeout=DOCKER_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxError(f"docker run: {exc}") from None
        if done.returncode != 0:
            problem = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise SandboxError(f"writing {what} failed: {problem[-1] if problem else '?'}")

    def adopt_volume(self, volume: str, path: str) -> None:
        """Mounts ``volume`` at ``path`` in every later command, and removes it on ``close``."""
        self.mounts[volume] = path

    def close(self) -> None:
        """Removes the volume, the hook's, the volumes it adopted, and everything in them."""
        for volume in [*self.mounts, self.volume, self.hook]:
            self._docker("volume", "rm", "-f", volume, check=False)

    def __enter__(self) -> "DockerSandbox":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- running -----------------------------------------------------------------------------

    def ready_payload(self, side: str) -> dict[str, str]:
        """The ``sandbox.ready`` payload: L3 (L4 under gVisor), the network enforced."""
        runtime = f", runtime {self.runtime}" if self.runtime is not None else ""
        return {
            "side": side,
            "backend": self.backend,
            "isolation_level": self.isolation_level,
            "network": "enforced",
            "platform": f"Docker {self._server} linux{runtime}, {self.image}"[:200],
        }

    @staticmethod
    def container_path(relative: str) -> str:
        """Where a path of the snapshot (POSIX, relative to its root) is in the container."""
        path = posixpath.normpath(posixpath.join(WORK, relative))
        if path != WORK and not path.startswith(WORK + "/"):
            raise SandboxError(f"{relative!r} is outside the snapshot")
        return path

    def read_file(self, relative: str, *, limit: int = 64 * 1024 * 1024) -> bytes | None:
        """A file the commands left in the volume (relative to its root), or None."""
        name = f"repro-read-{uuid.uuid4().hex[:12]}"
        self._docker(
            "create", "--name", name, "--network", "none", "-v", f"{self.volume}:{WORK}:ro",
            "--entrypoint", "true", self.image,
        )  # fmt: skip
        try:
            return self._copy_out(name, self.container_path(relative), limit)
        finally:
            self._docker("rm", "-f", name, check=False)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        """Runs ``argv`` in a fresh hardened container, from ``cwd`` (relative to the snapshot)."""
        if not argv:
            raise SandboxError("no command")
        with self._lock:
            self._runs += 1
            number = self._runs
        run_dir = self.work / f"run-{number}"
        run_dir.mkdir(parents=True, exist_ok=False)
        audit = f"{WORK}/.repro/audit-{number}.jsonl"
        name = f"repro-{self.volume[6:]}-{number}"
        command = [
            self.docker, "run", "--name", name, *self._hardening(),
            "-v", f"{self.volume}:{WORK}", "-v", f"{self.hook}:{HOOK_MOUNT}:ro",
            *[flag for volume, path in self.mounts.items() for flag in ("-v", f"{volume}:{path}")],
            "-w", self.container_path(cwd),
            *_env_flags(self._environment(audit, env)),
            "--entrypoint", argv[0], self.image, *argv[1:],
        ]  # fmt: skip
        timeout = timeout_s if timeout_s is not None else self.limits.timeout_s
        out_path, err_path = run_dir / "stdout", run_dir / "stderr"
        started = time.monotonic()
        outcome: Outcome = "exited"
        try:
            with out_path.open("wb") as out, err_path.open("wb") as err:
                process = subprocess.Popen(  # noqa: S603 - docker, with Repro's own arguments
                    command, stdin=subprocess.DEVNULL, stdout=out, stderr=err
                )
                try:
                    while process.poll() is None:
                        if time.monotonic() - started > timeout:
                            outcome = "timeout"
                            break
                        if stop is not None and stop():
                            outcome = "stopped"
                            break
                        time.sleep(POLL_S)
                finally:
                    if process.poll() is None:
                        self._docker("kill", name, check=False)
                    process.wait()
            duration = time.monotonic() - started
            state = self._docker(
                "inspect", name, "--format", "{{.State.ExitCode}} {{.State.OOMKilled}}", check=False
            ).split()
            stdout, cut_out = read_head(out_path, self.limits.output_bytes)
            stderr, cut_err = read_head(err_path, self.limits.output_bytes)
            if process.returncode == DOCKER_FAILED and not state:
                tail = stderr.decode("utf-8", "replace")[-500:]
                raise SandboxError(f"docker run failed: {tail}")
            log = self._copy_out(name, audit, limit=64 * 1024 * 1024)
        finally:
            self._docker("rm", "-f", name, check=False)
        log_path = run_dir / "audit.jsonl"
        if log is not None:
            log_path.write_bytes(log)
        return Execution(
            argv=tuple(argv),
            outcome=outcome,
            returncode=int(state[0]) if outcome == "exited" and state else None,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
            output_truncated=cut_out or cut_err,
            left_running=False,  # when a container's first process ends, the kernel ends the rest
            detections=read_detections(log_path) if log else Detections((), 0, truncated=False),
            oom_killed=len(state) > 1 and state[1] == b"true",
        )

    def _hardening(self) -> list[str]:
        memory = str(self.limits.memory_bytes)
        return [
            *(["--runtime", self.runtime] if self.runtime is not None else []),
            "--network", "none",
            "--read-only",
            "--tmpfs", f"{TMP}:rw,exec,size={TMPFS_SIZE}",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", USER,
            "--pids-limit", str(self.limits.processes),
            "--memory", memory,
            "--memory-swap", memory,  # equal to --memory: no swap
            "--cpus", f"{self.limits.cpus:g}",
        ]  # fmt: skip

    def _environment(self, audit: str, extra: Mapping[str, str] | None) -> dict[str, str]:
        """No host variables at all: the image's own PATH, a home in ``/tmp``, the hook."""
        extra = dict(extra or {})
        python_path = [HOOK_MOUNT, *self.python_path]
        if extra.get("PYTHONPATH"):
            python_path.append(extra["PYTHONPATH"])
        env = {
            "HOME": TMP,
            "TMPDIR": TMP,
            "PYTHONHASHSEED": str(HASH_SEED),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            **self.variables,
            **extra,
        }
        env["PYTHONPATH"] = ":".join(python_path)  # the hook first, always
        env[AUDIT_LOG_ENV] = audit
        env[AUDIT_ROOTS_ENV] = f"{WORK}:{TMP}"
        return env

    def _copy_out(self, container: str, path: str, limit: int) -> bytes | None:
        archive = self._docker("cp", f"{container}:{path}", "-", check=False)
        if not archive:
            return None
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            member = next((m for m in tar.getmembers() if m.isfile()), None)
            handle = tar.extractfile(member) if member is not None else None
            return handle.read(limit) if handle is not None else None


def _env_flags(env: Mapping[str, str]) -> list[str]:
    flags: list[str] = []
    for key, value in env.items():
        flags += ["-e", f"{key}={value}"]
    return flags
