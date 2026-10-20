"""The event bus (ARCHITECTURE §3, §5): the one way events enter the store.

``emit`` builds an event's envelope (a ULID, the time, ``v``, the kind's payload version and the
producer), removes recognised credentials from its payload and target, validates the complete
event against its kind's generated model (payload and stage), and hands it to the store's
writer, which alone assigns ``seq`` (and an ``evidence.created`` event's evidence ``seq``, the
same number). Events emitted at once from several jobs can reach the writer in another order
than they were stamped; the writer raises a ``ts`` that would go backwards to its run's latest.
When the writer commits, the bus passes the stored events to
its subscribers in ``seq`` order: nothing is published that is not durable.

Subscribers are called on the writer's thread and must not block (C04 hands events to each
client's bounded queue). A subscriber that raises is dropped, so it cannot stop the others.
"""

import threading
import typing
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from typing import Any, Final

from pydantic import ValidationError

from repro import __version__
from repro.clock import now_timestamp
from repro.ids import new_event_id
from repro.logs import get_logger
from repro.scrub import scrub
from repro.store import StoredEvent, StoreWriter
from repro_events.models import EVENT_ADAPTER, Event

log = get_logger("bus")

Listener = Callable[[Sequence[StoredEvent]], None]


class EventError(ValueError):
    """An event that does not match its kind's schema."""


def _payload_versions() -> dict[str, int]:
    """Each kind's payload version, read from the generated event models."""
    versions: dict[str, int] = {}
    union = typing.get_args(Event)[0]  # Annotated[Union[...], Field(discriminator="kind")]
    for model in typing.get_args(union):
        (kind,) = typing.get_args(model.model_fields["kind"].annotation)
        (pv,) = typing.get_args(model.model_fields["pv"].annotation)
        versions[kind] = pv
    return versions


PAYLOAD_VERSIONS: Final = _payload_versions()


def producer_tag() -> str:
    """``repro/<version>``, as the envelope's ``producer`` (the schema's pattern)."""
    version = __version__ if __version__[:1].isdigit() else "0.0.0"
    return f"repro/{version}"


class EventBus:
    """Builds, checks and stores events, and publishes them once committed."""

    def __init__(
        self,
        writer: StoreWriter,
        *,
        producer: str | None = None,
        clock: Callable[[], str] = now_timestamp,
        new_id: Callable[[], str] = new_event_id,
    ) -> None:
        self.writer = writer
        self.producer = producer or producer_tag()
        self._clock = clock
        self._new_id = new_id
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        writer.on_commit = self._publish

    def envelope(
        self,
        run_id: str,
        kind: str,
        *,
        stage: str,
        status: str,
        payload: Mapping[str, Any],
        target: Mapping[str, Any] | None = None,
        agent: str | None = None,
        parent: str | None = None,
    ) -> dict[str, Any]:
        """A complete, validated event without ``seq``."""
        pv = PAYLOAD_VERSIONS.get(kind)
        if pv is None:
            raise EventError(f"unknown event kind {kind!r}")
        envelope: dict[str, Any] = {
            "id": self._new_id(),
            "run_id": run_id,
            "ts": self._clock(),
            "stage": stage,
            "agent": agent,
            "kind": kind,
            "target": scrub(dict(target), escape=False) if target is not None else None,
            "status": status,
            "payload": scrub(dict(payload)),
            "v": 1,
            "pv": pv,
            "producer": self.producer,
        }
        if parent is not None:
            envelope["parent"] = parent
        draft = {**envelope, "seq": 1}  # the writer assigns the real one
        evidence = draft["payload"].get("evidence")
        if kind == "evidence.created" and isinstance(evidence, Mapping) and "seq" not in evidence:
            draft["payload"] = {**draft["payload"], "evidence": {**evidence, "seq": 1}}
        try:
            EVENT_ADAPTER.validate_python(draft)
        except ValidationError as exc:
            raise EventError(f"invalid {kind} event: {exc}") from None
        return envelope

    def emit(self, run_id: str, kind: str, **fields: Any) -> "Future[list[StoredEvent]]":
        """Builds, checks and stores one event; the future gives it once committed."""
        return self.writer.submit(self.envelope(run_id, kind, **fields))

    def emit_group(self, envelopes: Sequence[Mapping[str, Any]]) -> "Future[list[StoredEvent]]":
        """Stores events built with ``envelope`` together, or not at all."""
        return self.writer.submit_group(envelopes)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Calls ``listener`` with each committed batch; returns a function that unsubscribes."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _publish(self, events: Sequence[StoredEvent]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(events)
            except Exception:  # A subscriber must not stop the others, or the writer.
                log.exception("subscriber failed; dropped")
                with self._lock:
                    if listener in self._listeners:
                        self._listeners.remove(listener)
