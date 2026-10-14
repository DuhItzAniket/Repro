"""Reading the store: a run's events in order, runs, evidence and artifacts.

A reader holds its own read-only connection, so it never blocks the writer and never writes.
WAL lets it read a consistent snapshot while the writer commits.
"""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repro.store.db import StoreError, connect_reader
from repro.store.schema import SCHEMA_VERSION, user_version
from repro.store.writer import RunRecord, StoredEvent

DEFAULT_PAGE = 1_000


@dataclass(frozen=True, slots=True)
class ArtifactRow:
    run_id: str
    sha256: str
    path: str
    media_type: str
    size_bytes: int
    created_at: str


class StoreReader:
    """Read-only access to a store's database. Use as a context manager, or ``close``."""

    def __init__(self, path: Path) -> None:
        self._connection = connect_reader(path)
        version = user_version(self._connection)
        if version != SCHEMA_VERSION:
            self._connection.close()
            raise StoreError(
                f"{path}: schema version {version}, but this Repro reads {SCHEMA_VERSION}"
                + (" (start a writer to create or migrate it)" if version < SCHEMA_VERSION else "")
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "StoreReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._connection.execute(sql, params)

    # -- events ------------------------------------------------------------------------------

    def last_seq(self, run_id: str) -> int:
        """The run's last ``seq``; 0 before its first event."""
        row = self._query("SELECT MAX(seq) FROM events WHERE run_id = ?", (run_id,)).fetchone()
        return int(row[0] or 0)

    def events(self, run_id: str, after: int = 0, limit: int = DEFAULT_PAGE) -> list[StoredEvent]:
        """Up to ``limit`` events with ``seq > after``, in order."""
        rows = self._query(
            "SELECT run_id, seq, id, kind, body FROM events"
            " WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (run_id, after, limit),
        )
        return [StoredEvent(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def iter_events(
        self, run_id: str, after: int = 0, page: int = DEFAULT_PAGE
    ) -> Iterator[StoredEvent]:
        """Every event with ``seq > after``, in order, a page at a time."""
        while True:
            batch = self.events(run_id, after, page)
            yield from batch
            if len(batch) < page:
                return
            after = batch[-1].seq

    # -- runs --------------------------------------------------------------------------------

    def run(self, run_id: str) -> RunRecord | None:
        row = self._query(
            "SELECT id, repo, base, head, producer, created_at, status, finished_at FROM runs"
            " WHERE id = ?",
            (run_id,),
        )
        found = row.fetchone()
        return None if found is None else RunRecord(*found)

    def runs(self, limit: int = 50) -> list[RunRecord]:
        """The most recent runs first (IDs are ULIDs, so they sort by creation)."""
        rows = self._query(
            "SELECT id, repo, base, head, producer, created_at, status, finished_at FROM runs"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [RunRecord(*row) for row in rows]

    # -- evidence and artifacts ------------------------------------------------------------

    def evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self._query("SELECT body FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            return None
        value: dict[str, Any] = json.loads(row[0])
        return value

    def evidence_of(self, run_id: str) -> list[dict[str, Any]]:
        """A run's evidence, in the order it was created."""
        rows = self._query("SELECT body FROM evidence WHERE run_id = ? ORDER BY seq", (run_id,))
        return [json.loads(row[0]) for row in rows]

    def artifact(self, run_id: str, sha256: str) -> ArtifactRow | None:
        """A run's artifact by digest (its first path, if the content is stored at several)."""
        row = self._query(
            "SELECT run_id, sha256, path, media_type, size_bytes, created_at FROM artifacts"
            " WHERE run_id = ? AND sha256 = ? ORDER BY path LIMIT 1",
            (run_id, sha256),
        ).fetchone()
        return None if row is None else ArtifactRow(*row)
