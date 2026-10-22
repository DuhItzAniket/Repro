"""A sandbox whose snapshot is not on this machine's filesystem: a Docker volume (D02) or an
E2B microVM (K09).

The snapshot is at ``WORK`` inside the sandbox, Repro's hook at ``HOOK_MOUNT``. What a command
leaves there is read back with ``read_file``, and what the run stage writes for it goes in with
``write_files``. The runners treat every such sandbox alike, whichever backend holds it.
"""

import posixpath
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, Self

from repro.sandbox.limits import Limits
from repro.sandbox.process import Execution, SandboxError

WORK: Final = "/work"
#: The sandbox's own temporary directory, never the host's.
TMP: Final = "/tmp"  # noqa: S108
HOOK_MOUNT: Final = "/opt/repro/hook"
USER: Final = "1000:1000"


class RemoteSandbox(ABC):
    """Runs commands on a commit held inside the sandbox, at ``WORK``."""

    backend: str
    #: A directory on this machine for what each command leaves here (its output).
    work: Path
    limits: Limits
    #: Directories put on every command's import path after the hook (J04).
    python_path: tuple[str, ...] = ()
    #: Variables every command gets, under the caller's own (J04).
    variables: dict[str, str]

    @staticmethod
    def container_path(relative: str) -> str:
        """Where a path of the snapshot (POSIX, relative to its root) is in the sandbox."""
        path = posixpath.normpath(posixpath.join(WORK, relative))
        if path != WORK and not path.startswith(WORK + "/"):
            raise SandboxError(f"{relative!r} is outside the snapshot")
        return path

    @property
    @abstractmethod
    def isolation_level(self) -> str: ...

    @abstractmethod
    def ready_payload(self, side: str) -> dict[str, str]:
        """The ``sandbox.ready`` payload."""

    @abstractmethod
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Execution:
        """Runs ``argv`` from ``cwd`` (relative to the snapshot), with no network."""

    @abstractmethod
    def write_files(self, directory: str, files: Mapping[str, bytes]) -> None:
        """Writes ``files`` (POSIX paths relative to ``directory``, itself relative to the
        snapshot), owned by the unprivileged user."""

    @abstractmethod
    def overlay(self, name: str, files: Mapping[str, bytes]) -> str:
        """A copy of the snapshot at ``.repro/<name>`` with ``files`` written over it; its path
        relative to the snapshot."""

    @abstractmethod
    def read_file(self, relative: str, *, limit: int = 64 * 1024 * 1024) -> bytes | None:
        """A file the commands left (relative to the snapshot's root), or None."""

    @abstractmethod
    def close(self) -> None:
        """Removes the sandbox and everything in it."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
