"""How many agents run at once, and in which of the cockpit's dispatch slots (G01).

Each Agent SDK call is a Claude Code process of about 1 GiB (research/04 §1.10), so a run starts
at most ``min(12, free RAM in GiB)`` at once, and at least one (ARCHITECTURE §10.5). Free memory
is the memory available to new processes without swapping: ``ullAvailPhys`` from
``GlobalMemoryStatusEx`` on Windows, ``MemAvailable`` from ``/proc/meminfo`` on Linux (both per
their documentation: Microsoft Learn, MEMORYSTATUSEX; the Linux kernel's proc(5)); elsewhere it
is unknown, and one agent runs at a time.

The cockpit always shows 12 dispatch slots. An agent first takes the lowest free slot, where it
waits until it may start; an agent queued behind 12 others has no slot yet, and so no events.
"""

import asyncio
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

#: Dispatch slots the cockpit shows (DESIGN.md, the agents panel: 2 columns by 6 rows).
SLOTS: Final = 12
#: The most agents one run can name (``AgentId``: ``a`` and two or three digits).
MAX_AGENTS: Final = 999
GIB: Final = 1024**3
POLL_S: Final = 0.05

if sys.platform == "win32":
    import ctypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        )

    def _available_bytes() -> int | None:
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys)

else:

    def _available_bytes() -> int | None:
        try:
            lines = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
        except OSError:
            return None
        for line in lines:
            name, _, value = line.partition(":")
            if name == "MemAvailable" and value.split()[1:] == ["kB"]:
                return int(value.split()[0]) * 1024
        return None


def free_memory_gib() -> float | None:
    """The memory available to new processes, in GiB; None where it cannot be read."""
    available = _available_bytes()
    return None if available is None else available / GIB


def concurrency_for(free_gib: float | None) -> int:
    """``min(12, free RAM in GiB)``, at least 1; 1 when free memory is unknown."""
    if free_gib is None:
        return 1
    return max(1, min(SLOTS, int(free_gib)))


def default_concurrency() -> int:
    return concurrency_for(free_memory_gib())


class Dispatch:
    """A run's agents: their ids, their dispatch slots, and how many run at once.

    Thread-safe: the jobs that run agents each run in a thread of their own, with an event loop
    of their own; waiting polls, so it neither blocks a loop nor ties the jobs to one loop.
    """

    def __init__(self, concurrency: int) -> None:
        if not 1 <= concurrency <= SLOTS:
            raise ValueError(f"concurrency must be between 1 and {SLOTS}")
        self.concurrency = concurrency
        self._lock = threading.Lock()
        self._seated = [False] * SLOTS
        self._running = 0
        self._named = 0

    def agent_id(self) -> str:
        """The next agent's id: ``a01``, ``a02``, ... (``a100`` onwards past 99)."""
        with self._lock:
            if self._named == MAX_AGENTS:
                raise RuntimeError(f"a run has at most {MAX_AGENTS} agents")
            self._named += 1
            return f"a{self._named:02d}"

    def try_seat(self) -> int | None:
        """Takes the lowest free slot, or None if all 12 are taken."""
        with self._lock:
            for slot, seated in enumerate(self._seated):
                if not seated:
                    self._seated[slot] = True
                    return slot
            return None

    def try_start(self) -> bool:
        """Takes one of the ``concurrency`` places to run, if one is free."""
        with self._lock:
            if self._running == self.concurrency:
                return False
            self._running += 1
            return True

    def stop(self) -> None:
        """Gives back a place to run."""
        with self._lock:
            if self._running == 0:
                raise RuntimeError("no agent is running")
            self._running -= 1

    def unseat(self, slot: int) -> None:
        """Frees a slot for the next agent."""
        with self._lock:
            if not self._seated[slot]:
                raise RuntimeError(f"slot {slot} is free")
            self._seated[slot] = False

    async def seat(self, check: Callable[[], None]) -> int:
        """Waits for a slot; ``check`` raises to give up (the job was cancelled)."""
        while (slot := self.try_seat()) is None:
            check()
            await asyncio.sleep(POLL_S)
        return slot

    async def start(self, check: Callable[[], None]) -> None:
        """Waits for a place to run; ``check`` raises to give up."""
        while not self.try_start():
            check()
            await asyncio.sleep(POLL_S)
