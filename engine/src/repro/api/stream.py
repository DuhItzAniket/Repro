"""A run's events over a WebSocket: replay, then live, without gaps (ARCHITECTURE §11).

1. The connection's mailbox is subscribed to the bus **first**.
2. Stored events with ``seq > from`` are sent in pages.
3. Mailbox events already sent are dropped; the rest follow in order.
4. ``{"type": "caught_up", "seq": n}`` marks the end of the replay.
5. Live events follow, batched every ``FRAME_INTERVAL_S``.
6. After ``run.finished`` the server closes normally.

Nothing a client does can slow the engine: the bus calls the mailbox's listener on the writer's
thread, and the listener only hands the events to the event loop. A mailbox holding more than
``max_pending`` events is abandoned and the client closed with 4000 "resync"; it reconnects with
``?from=`` its last ``seq``, and the store, which is authoritative, replays the rest.

Frames carry the stored JSON bodies verbatim, so a streamed event is byte-identical to the
stored one.
"""

import asyncio
import contextlib
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Final

from starlette.websockets import WebSocket, WebSocketDisconnect

from repro.bus import EventBus
from repro.logs import get_logger
from repro.store import StoredEvent, StoreReader

log = get_logger("api.stream")

FRAME_INTERVAL_S: Final = 0.025
REPLAY_PAGE: Final = 500
#: Close codes (4000 to 4999 are free for applications, RFC 6455 §7.4.2).
RESYNC: Final = 4000
BAD_REQUEST: Final = 4400
UNKNOWN_RUN: Final = 4404


def events_frame(events: Sequence[StoredEvent]) -> str:
    return '{"type":"events","events":[' + ",".join(event.body for event in events) + "]}"


class Mailbox:
    """One connection's live events, handed from the writer's thread to the event loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop, run_id: str, max_pending: int) -> None:
        self.loop = loop
        self.run_id = run_id
        self.max_pending = max_pending
        self.pending: deque[StoredEvent] = deque()
        self.overflowed = False
        self.ready = asyncio.Event()

    def listener(self, events: Sequence[StoredEvent]) -> None:
        """Called on the writer's thread: never blocks."""
        mine = [event for event in events if event.run_id == self.run_id]
        if mine:
            with contextlib.suppress(RuntimeError):  # the loop has closed: the client is gone
                self.loop.call_soon_threadsafe(self._offer, mine)

    def _offer(self, events: list[StoredEvent]) -> None:
        if self.overflowed:
            return
        if len(self.pending) + len(events) > self.max_pending:
            self.overflowed = True
            self.pending.clear()
        else:
            self.pending.extend(events)
        self.ready.set()

    def take_after(self, last: int) -> list[StoredEvent] | None:
        """The waiting events after ``last``, in order; ``None`` if one is missing."""
        taken: list[StoredEvent] = []
        while self.pending:
            event = self.pending.popleft()
            if event.seq <= last:
                continue  # already sent in the replay
            if event.seq != last + 1:
                return None
            taken.append(event)
            last = event.seq
        return taken


async def stream_run(
    websocket: WebSocket,
    run_id: str,
    after: int,
    *,
    open_reader: Callable[[], StoreReader],
    bus: EventBus | None,
    max_pending: int,
) -> None:
    """Serves one accepted connection until the run ends, the client leaves, or it must resync.

    The connection's store reader lives on one thread of its own. A SQLite connection must never
    be used by two threads at once, and a client that leaves mid-replay cancels this coroutine
    while a read may still be running: closing on the same single thread queues the close behind
    that read instead of racing it.
    """
    loop = asyncio.get_running_loop()
    thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="repro-stream-reader")
    reader = await loop.run_in_executor(thread, open_reader)
    unsubscribe: Callable[[], None] | None = None
    gone = asyncio.Event()
    watcher = asyncio.create_task(_watch_disconnect(websocket, gone))
    try:
        if await loop.run_in_executor(thread, reader.run, run_id) is None:
            await websocket.close(UNKNOWN_RUN, "unknown run")
            return
        mailbox = Mailbox(loop, run_id, max_pending)
        if bus is not None:
            unsubscribe = bus.subscribe(mailbox.listener)
        last = after
        while True:  # the replay
            page = await loop.run_in_executor(thread, reader.events, run_id, last, REPLAY_PAGE)
            if not page:
                break
            await websocket.send_text(events_frame(page))
            last = page[-1].seq
            if page[-1].kind == "run.finished":
                await websocket.send_json({"type": "caught_up", "seq": last})
                await websocket.close(1000, "finished")
                return
        await websocket.send_json({"type": "caught_up", "seq": last})
        if bus is None:  # no live events in this process: the replay is all there is
            await websocket.close(1000, "replayed")
            return
        await _relay(websocket, mailbox, last, gone)
    except WebSocketDisconnect:
        pass
    finally:
        if unsubscribe is not None:
            unsubscribe()
        watcher.cancel()
        thread.submit(
            reader.close
        )  # after any read still in flight; not awaited: we may be cancelled
        thread.shutdown(wait=False)


async def _relay(websocket: WebSocket, mailbox: Mailbox, last: int, gone: asyncio.Event) -> None:
    """Live events in batches, until run.finished, a resync or the client leaving."""
    while True:
        if not mailbox.pending and not mailbox.overflowed:
            mailbox.ready.clear()
            waiting = asyncio.create_task(mailbox.ready.wait())
            leaving = asyncio.create_task(gone.wait())
            await asyncio.wait({waiting, leaving}, return_when=asyncio.FIRST_COMPLETED)
            waiting.cancel()
            leaving.cancel()
            if gone.is_set():
                return
        await asyncio.sleep(FRAME_INTERVAL_S)  # let a burst gather into one frame
        if mailbox.overflowed:
            await _resync(websocket, "the client fell behind")
            return
        batch = mailbox.take_after(last)
        if batch is None:
            await _resync(websocket, "an event was missing from the live feed")
            return
        if not batch:
            continue
        await websocket.send_text(events_frame(batch))
        last = batch[-1].seq
        if batch[-1].kind == "run.finished":
            await websocket.close(1000, "finished")
            return


async def _resync(websocket: WebSocket, why: str) -> None:
    log.info("client asked to resync", extra={"fields": {"why": why}})
    await websocket.close(RESYNC, "resync")


async def _watch_disconnect(websocket: WebSocket, gone: asyncio.Event) -> None:
    """Notices a client that leaves while the server is waiting for events."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    gone.set()


def parse_after(raw: str | None) -> int | None:
    """``?from=``: a non-negative integer, exclusive; ``None`` if malformed."""
    if raw is None or raw == "":
        return 0
    if not raw.isdigit():
        return None
    return int(raw)
