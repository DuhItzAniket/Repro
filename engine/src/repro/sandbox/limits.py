"""What a sandboxed command may use (ADR-0004, L2)."""

from dataclasses import dataclass
from typing import Final

GIB: Final = 1024**3
MIB: Final = 1024**2


@dataclass(frozen=True, slots=True)
class Limits:
    """A sandboxed command's limits.

    - ``timeout_s``: wall-clock time, then the whole process tree is killed.
    - ``memory_bytes``: on Windows, the memory committed by all the command's processes together
      (a Job Object's job-wide limit); on POSIX, each process's address space (``RLIMIT_AS``).
    - ``processes``: on Windows, the processes alive at once; on Linux, the processes (threads,
      in fact) the command may add to its user's, since ``RLIMIT_NPROC`` counts all of them.
    - ``output_bytes``: how much of stdout and of stderr is kept, each.
    """

    timeout_s: float = 600.0
    memory_bytes: int = 4 * GIB
    processes: int = 256
    output_bytes: int = 4 * MIB

    def __post_init__(self) -> None:
        if self.timeout_s <= 0 or self.memory_bytes <= 0 or self.processes < 1:
            raise ValueError("limits must be positive")
        if self.output_bytes < 0:
            raise ValueError("output_bytes must not be negative")
