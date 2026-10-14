"""The schema enforces the event log's rules itself (C02)."""

import re
import sqlite3
from pathlib import Path

import pytest

from repro.store import RUN_STATES, SCHEMA_VERSION, SchemaError, StoreError, StoreReader
from repro.store.db import connect_reader, connect_writer
from repro.store.schema import MIGRATIONS, migrate, user_version
from store_support import run_record


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    connection = connect_writer(tmp_path / "repro.db")
    migrate(connection)
    run = run_record("run_01J9ZQ4R6M3X8T2K5V7N0P1QWE")
    connection.execute(
        "INSERT INTO runs (id, repo, base, head, producer, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run.id, run.repo, run.base, run.head, run.producer, run.created_at),
    )
    return connection


RUN = "run_01J9ZQ4R6M3X8T2K5V7N0P1QWE"


def insert(
    db: sqlite3.Connection, seq: int, *, event_id: str | None = None, kind: str = "log.line"
) -> None:
    event_id = event_id or f"evt_01J9ZQ4R6M3X8T2K5V7N0P{seq:04d}"
    db.execute(
        "INSERT INTO events (run_id, seq, id, ts, kind, stage, status, body)"
        " VALUES (?, ?, ?, '2026-10-14T00:00:00.000Z', ?, 'read', 'ok', '{}')",
        (RUN, seq, event_id, kind),
    )


def test_a_fresh_database_reaches_the_current_version(tmp_path: Path) -> None:
    connection = connect_writer(tmp_path / "repro.db")
    assert user_version(connection) == 0
    assert migrate(connection) == SCHEMA_VERSION
    assert user_version(connection) == SCHEMA_VERSION
    assert migrate(connection) == 0  # idempotent
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"runs", "events", "evidence", "artifacts", "cards"} <= tables


def test_the_write_connection_uses_wal_and_foreign_keys(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_a_newer_database_is_refused(tmp_path: Path) -> None:
    connection = connect_writer(tmp_path / "repro.db")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaError, match="newer than this Repro knows"):
        migrate(connection)


def test_a_reader_refuses_a_database_without_the_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "repro.db"
    with pytest.raises(StoreError, match="no database"):
        StoreReader(path)
    connect_writer(path).close()
    with pytest.raises(StoreError, match="schema version 0"):
        StoreReader(path)


def test_the_primary_key_is_run_id_and_seq(db: sqlite3.Connection) -> None:
    """UNIQUE(run_id, seq): the table's primary key, checked in the schema itself."""
    columns = db.execute("PRAGMA table_info(events)").fetchall()
    key = sorted((column[5], column[1]) for column in columns if column[5] > 0)
    assert key == [(1, "run_id"), (2, "seq")]
    insert(db, 1)
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, 1, event_id="evt_01J9ZQ4R6M3X8T2K5V7N0PZZZZ")  # the same (run_id, seq)


def test_the_primary_key_holds_even_without_the_seq_trigger(db: sqlite3.Connection) -> None:
    insert(db, 1)
    db.execute("DROP TRIGGER events_seq_is_next")
    with pytest.raises(
        sqlite3.IntegrityError, match=r"UNIQUE constraint failed: events\.run_id, events\.seq"
    ):
        insert(db, 1, event_id="evt_01J9ZQ4R6M3X8T2K5V7N0PZZZZ")


def test_seq_must_be_the_runs_next_number(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="next number"):
        insert(db, 2)  # a gap before the first event
    insert(db, 1)
    insert(db, 2)
    with pytest.raises(sqlite3.IntegrityError, match="next number"):
        insert(db, 4)


def test_event_ids_are_unique(db: sqlite3.Connection) -> None:
    insert(db, 1, event_id="evt_01J9ZQ4R6M3X8T2K5V7N0PAAAA")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert(db, 2, event_id="evt_01J9ZQ4R6M3X8T2K5V7N0PAAAA")


def test_events_and_evidence_are_append_only(db: sqlite3.Connection) -> None:
    insert(db, 1, kind="evidence.created")
    db.execute(
        "INSERT INTO evidence (id, run_id, seq, type, body)"
        " VALUES ('ev_01J9ZQ4R6M3X8T2K5V7N0P1QWE', ?, 1, 'test_outcome', '{}')",
        (RUN,),
    )
    for statement in (
        "UPDATE events SET status = 'fail'",
        "DELETE FROM events",
        "UPDATE evidence SET type = 'api_diff'",
        "DELETE FROM evidence",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute(statement)


def test_evidence_needs_an_evidence_created_event(db: sqlite3.Connection) -> None:
    insert(db, 1, kind="log.line")
    for seq in (1, 2):  # the wrong kind, then no event at all
        with pytest.raises(sqlite3.IntegrityError, match=r"evidence\.created"):
            db.execute(
                "INSERT INTO evidence (id, run_id, seq, type, body)"
                " VALUES (?, ?, ?, 'test_outcome', '{}')",
                (f"ev_01J9ZQ4R6M3X8T2K5V7N0P000{seq}", RUN, seq),
            )


def test_events_need_their_run(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO events (run_id, seq, id, ts, kind, stage, status, body) VALUES"
            " ('run_01J9ZQ4R6M3X8T2K5V7N0PXXXX', 1, 'evt_01J9ZQ4R6M3X8T2K5V7N0PXXXX', 't', 'k',"
            " 'read', 'ok', '{}')"
        )


def test_bodies_must_be_json(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(
            "INSERT INTO events (run_id, seq, id, ts, kind, stage, status, body) VALUES"
            " (?, 1, 'evt_01J9ZQ4R6M3X8T2K5V7N0PXXXX', 't', 'k', 'read', 'ok', 'not json')",
            (RUN,),
        )


def test_run_states_match_the_migration() -> None:
    """Migration 1 spells the states out; this keeps RUN_STATES in step with it."""
    found = re.search(r"CHECK \(status IN \(([^)]*)\)\)", MIGRATIONS[0])
    assert found is not None
    assert tuple(part.strip().strip("'") for part in found.group(1).split(",")) == RUN_STATES


def test_a_running_run_has_no_finish_time(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute("UPDATE runs SET finished_at = 't' WHERE id = ?", (RUN,))
    db.execute("UPDATE runs SET status = 'completed', finished_at = 't' WHERE id = ?", (RUN,))


def test_a_reader_cannot_write(db: sqlite3.Connection, tmp_path: Path) -> None:
    reader = connect_reader(tmp_path / "repro.db")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.execute("UPDATE runs SET repo = 'x'")
