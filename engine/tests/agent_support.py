"""A scripted ``LLMBackend`` for tests: it plays back progress and a result, no model involved."""

import asyncio
import threading
from collections.abc import Sequence

from repro.agents import AgentRequest, AgentResult, OnProgress, Progress


class ScriptedBackend:
    """Reports ``progress``, then returns ``result``; ``hold`` keeps every call running until
    it is set. Records the requests, how many calls ran at once, and cancelled calls."""

    def __init__(
        self,
        result: AgentResult,
        progress: Sequence[Progress] = (),
        *,
        hold: threading.Event | None = None,
    ) -> None:
        self.result = result
        self.progress = tuple(progress)
        self.hold = hold
        self.requests: list[AgentRequest] = []
        self.running = 0
        self.peak = 0
        self.cancelled = 0
        self._lock = threading.Lock()

    async def run(
        self, request: AgentRequest, on_progress: OnProgress | None = None
    ) -> AgentResult:
        with self._lock:
            self.requests.append(request)
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            for update in self.progress:
                if on_progress is not None:
                    on_progress(update)
                await asyncio.sleep(0)
            while self.hold is not None and not self.hold.is_set():
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.02)  # long enough for calls to overlap
            return self.result
        except asyncio.CancelledError:
            with self._lock:
                self.cancelled += 1
            raise
        finally:
            with self._lock:
                self.running -= 1
