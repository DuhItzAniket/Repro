"""A crash mid-batch leaves a consistent database (roadmap C02).

A child process writes and is killed: once inside an open transaction, and repeatedly at
arbitrary moments while the writer commits batches of atomic groups. Afterwards the database
must open, pass SQLite's integrity and foreign-key checks, hold only whole groups with ``seq``
counting from 1 without gaps, and accept the next event at the next ``seq``.
"""

import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from repro.store import StoreReader
from store_support import log_line, started_writer

TESTS = Path(__file__).parent
GROUP = 25


def child(code: str, db: Path) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(TESTS), "REPRO_TEST_DB": str(db)}
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def check_consistent(db: Path) -> list[str]:
    """The database's integrity, and the messages of its one run's events in seq order."""
    connection = sqlite3.connect(db)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    with StoreReader(db) as reader:
        (run,) = reader.runs()
        events = list(reader.iter_events(run.id))
        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        return [event.envelope()["payload"]["message"] for event in events]


def test_a_crash_inside_an_open_transaction_loses_only_that_transaction(tmp_path: Path) -> None:
    db = tmp_path / "repro.db"
    process = child(
        """
        import os
        from pathlib import Path
        from store_support import log_line, run_record, started_writer
        from repro.store.writer import _insert

        db = Path(os.environ["REPRO_TEST_DB"])
        writer = started_writer(db)
        run = run_record()
        writer.create_run(run).result(30)
        writer.submit_group([log_line(run.id, f"committed {i}") for i in range(100)]).result(30)
        connection = writer._connection
        connection.execute("BEGIN IMMEDIATE")
        for i in range(50):
            _insert(connection, log_line(run.id, f"uncommitted {i}"), 101 + i)
        print("inside", flush=True)
        os._exit(1)  # killed with the transaction open
        """,
        db,
    )
    out, err = process.communicate(timeout=120)
    assert process.returncode == 1, err
    assert out.strip() == "inside"
    messages = check_consistent(db)
    assert messages == [f"committed {i}" for i in range(100)]
    # The store carries on at the next seq.
    with started_writer(db) as writer, StoreReader(db) as reader:
        (run,) = reader.runs()
        (event,) = writer.submit(log_line(run.id, "after the crash")).result(30)
    assert event.seq == 101


@pytest.mark.parametrize("delay", [0.05, 0.3, 0.9])
def test_a_writer_killed_at_any_moment_keeps_only_whole_groups(
    tmp_path: Path, delay: float
) -> None:
    db = tmp_path / "repro.db"
    process = child(
        f"""
        import os
        from pathlib import Path
        from store_support import log_line, run_record, started_writer

        db = Path(os.environ["REPRO_TEST_DB"])
        writer = started_writer(db, max_batch=200, max_delay=0.005)
        run = run_record()
        writer.create_run(run).result(30)
        group = 0
        while True:
            futures = [
                writer.submit_group(
                    [log_line(run.id, f"group {{group + g}} event {{k}}") for k in range({GROUP})]
                )
                for g in range(8)
            ]
            group += 8
            futures[0].result(30)
            if group == 8:
                print("writing", flush=True)
        """,
        db,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "writing"
    time.sleep(delay)
    process.kill()
    process.wait(60)
    messages = check_consistent(db)
    assert len(messages) >= GROUP  # at least the first group was committed
    assert len(messages) % GROUP == 0  # only whole groups
    expected = [f"group {g} event {k}" for g in range(len(messages) // GROUP) for k in range(GROUP)]
    assert messages == expected
    with started_writer(db) as writer, StoreReader(db) as reader:
        (run,) = reader.runs()
        (event,) = writer.submit(log_line(run.id, "after the crash")).result(30)
    assert event.seq == len(messages) + 1
