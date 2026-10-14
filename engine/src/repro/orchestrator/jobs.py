"""Jobs and what a job can do while it runs: emit events, check for cancellation, run tools."""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from repro.store import StoredEvent

Stage = Literal["read", "build", "run", "diff", "check", "review", "card"]
STAGES: Final[tuple[Stage, ...]] = ("read", "build", "run", "diff", "check", "review", "card")
#: How a finished job ended.
JobStatus = Literal["ok", "failed", "timeout", "skipped", "cancelled"]
#: A ``log.line``'s level (the event schema's enum).
LogLevel = Literal["debug", "info", "warning", "error"]

POLL_S: Final = 0.05


class JobCancelled(Exception):  # noqa: N818 - a signal for a job to stop, not an error
    """The job was cancelled or abandoned: it must stop, and it can emit nothing more."""


class SubprocessTimeoutError(Exception):
    """A tool did not finish in time and was killed with its children."""


@dataclass(frozen=True, slots=True)
class OnFailure:
    """What the run cannot verify if a job does not succeed (a missing item, ARCHITECTURE §6.1)."""

    reason: str
    detail: str
    targets: tuple[Mapping[str, str], ...] = ()
    resolution: str | None = None


@dataclass(frozen=True, slots=True)
class Job:
    """One unit of a run's work. ``run`` raises to fail; it should poll ``ctx.check()``."""

    name: str
    stage: Stage
    run: Callable[["JobContext"], None]
    on_failure: OnFailure
    needs: tuple[str, ...] = ()
    timeout_s: float = 600.0


Emit = Callable[..., "Future[list[StoredEvent]]"]


@dataclass(slots=True)
class JobContext:
    """Handed to a running job. Closed when the job ends, times out or the run is cancelled."""

    run_id: str
    job: Job
    _emit: Emit
    deadline: float
    _cancel: threading.Event = field(default_factory=threading.Event)
    _closed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        """Raises ``JobCancelled`` if the job should stop."""
        if self._cancel.is_set():
            raise JobCancelled(self.job.name)

    def wait(self, seconds: float) -> None:
        """Sleeps up to ``seconds``, waking (and raising) as soon as the job is cancelled."""
        if self._cancel.wait(seconds):
            raise JobCancelled(self.job.name)

    def cancel(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        """No more events from this job (it ended, or it was abandoned)."""
        with self._lock:
            self._closed = True
        self._cancel.set()

    def emit(
        self,
        kind: str,
        *,
        status: str,
        payload: Mapping[str, Any],
        target: Mapping[str, Any] | None = None,
        agent: str | None = None,
        stage: Stage | None = None,
    ) -> "Future[list[StoredEvent]]":
        """Emits an event in the job's stage; the future gives it once committed."""
        with self._lock:
            if self._closed:
                raise JobCancelled(f"{self.job.name} is closed")
            return self._emit(
                self.run_id,
                kind,
                stage=stage or self.job.stage,
                status=status,
                payload=payload,
                target=target,
                agent=agent,
            )

    def log(self, message: str, *, level: LogLevel = "info", status: str = "progress") -> None:
        """A line for the investigation feed."""
        payload = {"level": level, "verb": self.job.stage, "message": message[:2000]}
        self.emit("log.line", status=status, payload=payload)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> "subprocess.CompletedProcess[str]":
        """Runs a tool to completion, or kills it and its children on timeout or cancellation.

        The limit is the earlier of ``timeout_s`` and the job's own deadline.
        """
        self.check()
        limit = (
            self.deadline if timeout_s is None else min(self.deadline, time.monotonic() + timeout_s)
        )
        process = subprocess.Popen(  # noqa: S603 - argv from the engine, never a shell
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_new_process_group(),
        )
        while True:
            try:
                stdout, stderr = process.communicate(timeout=POLL_S)
            except subprocess.TimeoutExpired:
                cancelled = self._cancel.is_set()
                if cancelled or time.monotonic() >= limit:
                    kill_tree(process)
                    process.communicate()
                    if cancelled:
                        raise JobCancelled(self.job.name) from None
                    raise SubprocessTimeoutError(" ".join(argv[:3])) from None
                continue
            return subprocess.CompletedProcess(list(argv), process.returncode, stdout, stderr)


if sys.platform == "win32":

    def _new_process_group() -> dict[str, Any]:
        """A tool in its own process group, so it can be killed with its children."""
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

    def _kill_group(process: "subprocess.Popen[str]") -> None:
        taskkill = shutil.which("taskkill")
        if taskkill is not None:
            subprocess.run(  # noqa: S603 - a fixed argv
                [taskkill, "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
                timeout=30,
            )

else:

    def _new_process_group() -> dict[str, Any]:
        """A tool in its own session, so it can be killed with its children."""
        return {"start_new_session": True}

    def _kill_group(process: "subprocess.Popen[str]") -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def kill_tree(process: "subprocess.Popen[str]") -> None:
    """Kills a process and every process it started."""
    if process.poll() is not None:
        return
    _kill_group(process)
    if process.poll() is None:
        process.kill()
