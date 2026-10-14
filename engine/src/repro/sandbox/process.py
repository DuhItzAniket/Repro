"""The process sandbox: L0 to L2 (ADR-0004, ARCHITECTURE §8).

- **L0**: the command runs in a process tree of its own, from a given directory, with a minimal
  environment: a fresh home and temporary directory, fixed hash seed, no bytecode files, and only
  the host variables a process needs to start (no credentials, proxies or tokens).
- **L1**: every Python process it starts loads Repro's audit hook (``_hook/sitecustomize.py``),
  which records network, subprocess and file-write attempts. Detection only.
- **L2**: the tree is contained. Windows: a Job Object (the process is created suspended,
  assigned, resumed), with job-wide memory and process limits and kill-on-close. POSIX: a new
  session, so a process group, and resource limits set by a launcher before it ``exec``s the
  command. Both: a wall-clock timeout, after which the whole tree is killed, and any process
  left when the command itself ends is killed too, and reported.

Network is never enforced here: that needs L3 (a container with ``--network none``, D02).
"""

import contextlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from repro.sandbox.detect import (
    AUDIT_LOG_ENV,
    AUDIT_ROOTS_ENV,
    HOOK_DIR,
    Detections,
    read_detections,
)
from repro.sandbox.limits import Limits

Outcome = Literal["exited", "timeout", "stopped"]
POLL_S: Final = 0.05
#: The host variables a command may see: what a process needs to start, never credentials.
PASSED_VARIABLES: Final = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)
_LAUNCHER: Final = Path(__file__).with_name("_rlimits.py")


class SandboxError(RuntimeError):
    """The command could not be started in the sandbox."""


@dataclass(frozen=True, slots=True)
class Execution:
    """How a sandboxed command ran."""

    argv: tuple[str, ...]
    outcome: Outcome
    returncode: int | None  # None if it was killed for a timeout or a stop
    duration_s: float
    stdout: bytes
    stderr: bytes
    output_truncated: bool
    #: Processes were still running when the command itself ended; the sandbox killed them.
    left_running: bool
    detections: Detections
    #: Windows only: the most memory the command's processes committed at once.
    peak_memory_bytes: int | None = None
    #: Docker only: the kernel killed the command for exceeding its memory limit.
    oom_killed: bool = False


@dataclass
class _Tree:
    """The command's processes, however this platform holds them."""

    process: subprocess.Popen[bytes]
    job: Any = None  # winjob.Job on Windows
    peak_memory: int | None = field(default=None)

    def kill(self) -> None:
        if self.job is not None:
            self.job.terminate()
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.process.pid, signal.SIGKILL)  # type: ignore[attr-defined,unused-ignore]

    def others_running(self) -> bool:
        """Whether any process of the tree is still running, after the command itself ended."""
        if self.job is not None:
            return bool(self.job.active_processes() > 0)
        try:
            os.killpg(self.process.pid, 0)  # type: ignore[attr-defined,unused-ignore]
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def close(self) -> None:
        if self.job is not None:
            self.peak_memory = self.job.peak_memory()
            self.job.close()


class ProcessSandbox:
    """Runs commands at L0 to L2 in a directory of its own (``work``)."""

    backend: Final = "process"

    def __init__(self, work: Path, limits: Limits | None = None) -> None:
        self.work = work
        self.limits = limits or Limits()
        self._runs = 0
        self._lock = threading.Lock()

    @property
    def isolation_level(self) -> str:
        return "L2" if containment() is not None else "L1"

    def ready_payload(self, side: str) -> dict[str, str]:
        """The ``sandbox.ready`` payload: the level actually achieved, never more."""
        return {
            "side": side,
            "backend": self.backend,
            "isolation_level": self.isolation_level,
            "network": "detected-only",
            "platform": f"{platform.platform()} {platform.python_implementation()} "
            f"{platform.python_version()}"[:200],
        }

    def environment(
        self, cwd: Path, run_dir: Path, extra: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """The command's environment: minimal, and Repro's hook first on ``PYTHONPATH``."""
        home, tmp = run_dir / "home", run_dir / "tmp"
        for directory in (home, tmp):
            directory.mkdir(parents=True, exist_ok=True)
        env = {name: os.environ[name] for name in PASSED_VARIABLES if name in os.environ}
        env.update(
            HOME=str(home),
            USERPROFILE=str(home),
            APPDATA=str(home / "AppData" / "Roaming"),
            LOCALAPPDATA=str(home / "AppData" / "Local"),
            XDG_CACHE_HOME=str(home / ".cache"),
            TMPDIR=str(tmp),
            TEMP=str(tmp),
            TMP=str(tmp),
            PYTHONHASHSEED="0",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
        )
        extra = dict(extra or {})
        python_path = [str(HOOK_DIR)]
        if extra.get("PYTHONPATH"):
            python_path.append(extra["PYTHONPATH"])
        env.update(extra)
        env["PYTHONPATH"] = os.pathsep.join(python_path)  # the hook first, always
        env[AUDIT_LOG_ENV] = str(run_dir / "audit.jsonl")
        env[AUDIT_ROOTS_ENV] = os.pathsep.join([str(cwd), str(run_dir)])
        return env

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        """Runs ``argv`` to its end, its timeout, or until ``stop()`` says so."""
        if not argv:
            raise SandboxError("no command")
        with self._lock:
            self._runs += 1
            run_dir = self.work / f"run-{self._runs}"
        run_dir.mkdir(parents=True, exist_ok=False)
        environment = self.environment(cwd, run_dir, env)
        executable = shutil.which(argv[0], path=environment.get("PATH"))
        if executable is None:
            if not Path(argv[0]).is_file():
                raise SandboxError(f"{argv[0]!r} is not a command on the sandbox's PATH")
            executable = argv[0]
        command = [executable, *argv[1:]]
        timeout = timeout_s if timeout_s is not None else self.limits.timeout_s
        out_path, err_path = run_dir / "stdout", run_dir / "stderr"
        started = time.monotonic()
        with out_path.open("wb") as out, err_path.open("wb") as err:
            tree = _start(command, cwd=cwd, env=environment, out=out, err=err, limits=self.limits)
            outcome: Outcome = "exited"
            try:
                while tree.process.poll() is None:
                    if time.monotonic() - started > timeout:
                        outcome = "timeout"
                        break
                    if stop is not None and stop():
                        outcome = "stopped"
                        break
                    time.sleep(POLL_S)
                if outcome != "exited":
                    tree.kill()
                tree.process.wait()
                # Killed only while it may still be running: once the command is reaped, its
                # process group's ID could be reused, so the group is probed before a kill.
                left_running = outcome == "exited" and tree.others_running()
                if left_running:
                    tree.kill()
            except BaseException:
                tree.kill()
                tree.process.wait()
                raise
            finally:
                tree.close()  # Windows: closing the job kills whatever is left in it
        duration = time.monotonic() - started
        stdout, cut_out = read_head(out_path, self.limits.output_bytes)
        stderr, cut_err = read_head(err_path, self.limits.output_bytes)
        return Execution(
            argv=tuple(argv),
            outcome=outcome,
            returncode=tree.process.returncode if outcome == "exited" else None,
            duration_s=duration,
            stdout=stdout,
            stderr=stderr,
            output_truncated=cut_out or cut_err,
            left_running=left_running,
            detections=read_detections(run_dir / "audit.jsonl"),
            peak_memory_bytes=tree.peak_memory,
        )


def read_head(path: Path, limit: int) -> tuple[bytes, bool]:
    """The first ``limit`` bytes of a file, and whether there were more."""
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    return data[:limit], len(data) > limit


if sys.platform == "win32":
    from repro.sandbox.winjob import Job

    _CREATE_SUSPENDED: Final = 0x00000004

    def containment() -> str | None:
        """How this machine contains a command's processes (L2), or None if it cannot."""
        return "Job Object"

    def _start(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        out: Any,
        err: Any,
        limits: Limits,
    ) -> _Tree:
        job = Job(limits)
        try:
            process = subprocess.Popen(  # noqa: S603 - the sandboxed command
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                creationflags=_CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except OSError as exc:
            job.close()
            raise SandboxError(f"cannot start {command[0]!r}: {exc.strerror or exc}") from None
        try:
            job.adopt_suspended(process.pid)
        except OSError as exc:
            process.kill()
            process.wait()
            job.close()
            raise SandboxError(f"cannot contain {command[0]!r}: {exc}") from None
        return _Tree(process, job)

else:

    def containment() -> str | None:
        """How this machine contains a command's processes (L2), or None if it cannot."""
        return "process group and resource limits" if _LAUNCHER.exists() else None

    def _start(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        out: Any,
        err: Any,
        limits: Limits,
    ) -> _Tree:
        launcher = [
            sys.executable,
            "-I",
            "-S",
            str(_LAUNCHER),
            json.dumps({"memory_bytes": limits.memory_bytes, "processes": limits.processes}),
            "--",
            *command,
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - Repro's launcher, then the command
                launcher,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        except OSError as exc:
            raise SandboxError(f"cannot start {command[0]!r}: {exc.strerror or exc}") from None
        return _Tree(process)
