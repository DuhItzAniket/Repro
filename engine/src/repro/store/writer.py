"""The single writer (ARCHITECTURE §11; IMPLEMENTATION_PLAN §6, Stage C).

One thread owns the only write connection. Callers submit events without ``seq``, singly or as
an atomic group; the thread gathers what is waiting into a batch (up to ``max_batch`` events, or
whatever arrived within ``max_delay`` seconds of the first), and in one ``BEGIN IMMEDIATE``
transaction gives each event its run's next ``seq``, inserts it and commits. Only after the
commit does it resolve the callers' futures and call ``on_commit`` with the stored events in
order: nothing is published that is not durable.

An ``evidence.created`` event carries its evidence record in ``payload.evidence``; the writer
sets the record's ``seq`` to the event's own and inserts the evidence row in the same
transaction, so evidence exists exactly when the event that created it does.

If a batch's transaction fails, its groups are retried one transaction each, so a bad group
fails alone. The run registry and artifact rows go through the same thread, in submission order
with the events, so a run's row is committed before its first event.
"""

import json
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import ValidationError

from repro.logs import get_logger
from repro.store.db import connect_writer
from repro.store.schema import migrate
from repro_events.models import ArtifactRef, Envelope, Evidence

log = get_logger("store.writer")

EVIDENCE_CREATED: Final = "evidence.created"
RunOutcome = Literal["completed", "failed", "cancelled"]


class WriteError(RuntimeError):
    """A submission the store refused, or a writer that is not running."""


def canonical_json(value: Any) -> str:
    """Stable JSON for storage: sorted keys, no spaces, UTF-8 text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """An event as committed: its ``seq`` assigned and its canonical JSON body."""

    run_id: str
    seq: int
    id: str
    kind: str
    body: str

    def envelope(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.body)
        return value


@dataclass(frozen=True, slots=True)
class RunRecord:
    """A row of the run registry."""

    id: str
    repo: str
    base: str
    head: str
    producer: str
    created_at: str
    status: str = "running"
    finished_at: str | None = None


def check_draft(envelope: Mapping[str, Any]) -> None:
    """Rejects anything that is not an event envelope missing only its ``seq``."""
    if "seq" in envelope:
        raise WriteError("the writer assigns seq: submit the envelope without it")
    try:
        Envelope.model_validate({**envelope, "seq": 1})
    except ValidationError as exc:
        raise WriteError(f"not an event envelope: {exc}") from None
    if envelope["kind"] == EVIDENCE_CREATED:
        evidence = envelope["payload"].get("evidence")
        if not isinstance(evidence, Mapping):
            raise WriteError("an evidence.created event carries payload.evidence")
        try:
            Evidence.model_validate({**evidence, "seq": 1})
        except ValidationError as exc:
            raise WriteError(f"not an evidence record: {exc}") from None
        if evidence["run_id"] != envelope["run_id"]:
            raise WriteError("evidence belongs to the run of its evidence.created event")


@dataclass(slots=True)
class _Group:
    """Events committed together, or not at all."""

    drafts: tuple[Mapping[str, Any], ...]
    future: "Future[list[StoredEvent]]"


@dataclass(slots=True)
class _Call:
    """A registry or maintenance operation, run in the writer thread in its own transaction."""

    action: Callable[[sqlite3.Connection], object]
    future: "Future[object]"
    transaction: bool = True


_STOP: Final = None  # put on the queue by close()


class StoreWriter:
    """The only writer of a store's database. Use as a context manager, or ``start``/``close``."""

    def __init__(
        self,
        path: Path,
        *,
        max_batch: int = 512,
        max_delay: float = 0.02,
        on_commit: Callable[[Sequence[StoredEvent]], None] | None = None,
    ) -> None:
        if max_batch < 1 or max_delay < 0:
            raise ValueError("max_batch must be at least 1 and max_delay not negative")
        self.path = path
        self.max_batch = max_batch
        self.max_delay = max_delay
        self.on_commit = on_commit
        self._queue: queue.SimpleQueue[_Group | _Call | None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._connection: sqlite3.Connection | None = None
        self._next_seq: dict[str, int] = {}
        self._closed = False
        self._lock = threading.Lock()
        #: Transactions committed, for tests and diagnostics.
        self.transactions = 0

    # -- lifecycle ---------------------------------------------------------------------------

    def start(self) -> "StoreWriter":
        with self._lock:
            if self._thread is not None:
                raise WriteError("the writer is already running")
            connection = connect_writer(self.path)
            try:
                migrate(connection)
            except BaseException:
                connection.close()
                raise
            self._connection = connection
            self._thread = threading.Thread(
                target=self._run, name="repro-store-writer", daemon=True
            )
            self._thread.start()
        return self

    def close(self, timeout: float | None = None) -> None:
        """Writes everything submitted so far, then stops the thread and closes the database."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._thread is not None:
            self._queue.put(_STOP)
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise WriteError("the writer did not stop in time")
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "StoreWriter":
        return self if self._thread is not None else self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- submissions ------------------------------------------------------------------------

    def _put(self, item: _Group | _Call) -> None:
        if self._closed or self._thread is None:
            raise WriteError("the writer is not running")
        self._queue.put(item)

    def submit(self, envelope: Mapping[str, Any]) -> "Future[list[StoredEvent]]":
        """One event, without ``seq``. The future gives the stored event once committed."""
        return self.submit_group([envelope])

    def submit_group(self, envelopes: Sequence[Mapping[str, Any]]) -> "Future[list[StoredEvent]]":
        """Events committed together or not at all, in this order."""
        if not envelopes:
            raise WriteError("an empty group")
        for envelope in envelopes:
            check_draft(envelope)
        future: Future[list[StoredEvent]] = Future()
        self._put(_Group(tuple(envelopes), future))
        return future

    def _call(
        self, action: Callable[[sqlite3.Connection], object], *, transaction: bool = True
    ) -> "Future[object]":
        future: Future[object] = Future()
        self._put(_Call(action, future, transaction))
        return future

    def create_run(self, run: RunRecord) -> "Future[object]":
        """Registers a run; its events can follow."""

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                "INSERT INTO runs (id, repo, base, head, producer, status, created_at,"
                " finished_at) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL)",
                (run.id, run.repo, run.base, run.head, run.producer, run.created_at),
            )

        return self._call(insert)

    def finish_run(self, run_id: str, outcome: RunOutcome, finished_at: str) -> "Future[object]":
        """Records how a running run ended."""

        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ? AND status = 'running'",
                (outcome, finished_at, run_id),
            )
            if cursor.rowcount != 1:
                raise WriteError(f"{run_id} is not a running run")

        return self._call(update)

    def record_artifact(self, run_id: str, ref: ArtifactRef, created_at: str) -> "Future[object]":
        """Records a stored artifact file. The same content at the same path is kept once."""

        def insert(connection: sqlite3.Connection) -> bool:
            existing = connection.execute(
                "SELECT sha256 FROM artifacts WHERE run_id = ? AND path = ?", (run_id, ref.path)
            ).fetchone()
            if existing is not None:
                if existing[0] != ref.sha256:
                    raise WriteError(f"{ref.path} already holds other content in {run_id}")
                return False
            connection.execute(
                "INSERT INTO artifacts (run_id, sha256, path, media_type, size_bytes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, ref.sha256, ref.path, ref.media_type, ref.size_bytes, created_at),
            )
            return True

        return self._call(insert)

    def checkpoint(self) -> "Future[object]":
        """Copies the WAL into the database and truncates it (at the end of a run)."""

        def truncate(connection: sqlite3.Connection) -> tuple[int, int, int]:
            busy, frames, done = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return int(busy), int(frames), int(done)

        return self._call(truncate, transaction=False)

    # -- the writer thread -------------------------------------------------------------------

    def _run(self) -> None:
        stopping = False
        while not stopping:
            first = self._queue.get()
            if first is _STOP:
                break
            items: list[_Group | _Call] = [first]
            events = len(first.drafts) if isinstance(first, _Group) else 0
            deadline = time.monotonic() + self.max_delay
            while events < self.max_batch:
                remaining = deadline - time.monotonic()
                try:
                    if remaining > 0:
                        item = self._queue.get(timeout=remaining)
                    else:
                        item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _STOP:
                    stopping = True
                    break
                items.append(item)
                if isinstance(item, _Group):
                    events += len(item.drafts)
            self._process(items)
        # Anything submitted before close() is still written.
        leftovers: list[_Group | _Call] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not _STOP:
                leftovers.append(item)
        if leftovers:
            self._process(leftovers)

    def _process(self, items: Sequence[_Group | _Call]) -> None:
        """Runs consecutive groups as one batch, and each call on its own, in order."""
        pending: list[_Group] = []
        for item in items:
            if isinstance(item, _Group):
                pending.append(item)
                continue
            if pending:
                self._write_batch(pending)
                pending = []
            self._run_call(item)
        if pending:
            self._write_batch(pending)

    def _run_call(self, call: _Call) -> None:
        connection = self._require()
        try:
            if call.transaction:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    result = call.action(connection)
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                self.transactions += 1
            else:
                result = call.action(connection)
        except Exception as exc:  # noqa: BLE001 - handed to the caller through its future
            call.future.set_exception(_as_write_error(exc))
            return
        call.future.set_result(result)

    def _write_batch(self, groups: Sequence[_Group]) -> None:
        try:
            stored = self._transaction(groups)
        except Exception as exc:  # noqa: BLE001 - the thread must survive; callers get it
            if len(groups) == 1:
                groups[0].future.set_exception(_as_write_error(exc))
                return
            log.warning(
                "batch failed; retrying its groups one by one",
                extra={"fields": {"groups": len(groups), "error": str(exc)}},
            )
            for group in groups:
                try:
                    events = self._transaction([group])[0]
                except Exception as alone:  # noqa: BLE001 - as above
                    group.future.set_exception(_as_write_error(alone))
                    continue
                group.future.set_result(events)
                self._publish(events)
            return
        for group, events in zip(groups, stored, strict=True):
            group.future.set_result(events)
        self._publish([event for events in stored for event in events])

    def _transaction(self, groups: Sequence[_Group]) -> list[list[StoredEvent]]:
        connection = self._require()
        next_seq: dict[str, int] = {}
        stored: list[list[StoredEvent]] = []
        connection.execute("BEGIN IMMEDIATE")
        try:
            for group in groups:
                events = []
                for draft in group.drafts:
                    run_id = str(draft["run_id"])
                    seq = next_seq.get(run_id) or self._seq_after(connection, run_id)
                    events.append(_insert(connection, draft, seq))
                    next_seq[run_id] = seq + 1
                stored.append(events)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            # The database may hold numbers this cache does not: read them again next time.
            for run_id in next_seq:
                self._next_seq.pop(run_id, None)
            raise
        self._next_seq.update(next_seq)
        self.transactions += 1
        return stored

    def _seq_after(self, connection: sqlite3.Connection, run_id: str) -> int:
        cached = self._next_seq.get(run_id)
        if cached is not None:
            return cached
        row = connection.execute("SELECT MAX(seq) FROM events WHERE run_id = ?", (run_id,))
        return int(row.fetchone()[0] or 0) + 1

    def _publish(self, events: Sequence[StoredEvent]) -> None:
        if self.on_commit is None or not events:
            return
        try:
            self.on_commit(events)
        except Exception:  # The writer must outlive a failing subscriber hook.
            log.exception("on_commit failed")

    def _require(self) -> sqlite3.Connection:
        if self._connection is None:
            raise WriteError("the writer is not running")
        return self._connection


def _insert(connection: sqlite3.Connection, draft: Mapping[str, Any], seq: int) -> StoredEvent:
    envelope = {**draft, "seq": seq}
    evidence: dict[str, Any] | None = None
    if draft["kind"] == EVIDENCE_CREATED:
        evidence = {**draft["payload"]["evidence"], "seq": seq}
        envelope["payload"] = {**draft["payload"], "evidence": evidence}
    body = canonical_json(envelope)
    connection.execute(
        "INSERT INTO events (run_id, seq, id, ts, kind, stage, status, body)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            envelope["run_id"], seq, envelope["id"], envelope["ts"], envelope["kind"],
            envelope["stage"], envelope["status"], body,
        ),
    )  # fmt: skip
    if evidence is not None:
        connection.execute(
            "INSERT INTO evidence (id, run_id, seq, type, body) VALUES (?, ?, ?, ?, ?)",
            (evidence["id"], evidence["run_id"], seq, evidence["type"], canonical_json(evidence)),
        )
    return StoredEvent(str(envelope["run_id"]), seq, str(envelope["id"]), str(draft["kind"]), body)


def _as_write_error(exc: Exception) -> Exception:
    if isinstance(exc, WriteError):
        return exc
    if isinstance(exc, sqlite3.Error):
        error = WriteError(f"the store refused the write: {exc}")
        error.__cause__ = exc
        return error
    return exc
