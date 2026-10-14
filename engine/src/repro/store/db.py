"""SQLite connections for the store (ARCHITECTURE §11).

Every connection runs in explicit-transaction mode (``autocommit=True``: the library never opens
a transaction on its own, so ``BEGIN IMMEDIATE`` and ``COMMIT`` are ours), with foreign keys on
and a busy timeout. The write connection also sets WAL and ``synchronous=NORMAL``; read-only
connections open the file with ``mode=ro`` and can never write.
"""

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from repro.logs import get_logger

log = get_logger("store.db")

#: STRICT tables need SQLite 3.37.0 (https://www.sqlite.org/stricttables.html).
MIN_SQLITE: Final = (3, 37, 0)
BUSY_TIMEOUT_MS: Final = 5_000
#: How long opening a database keeps retrying a transient I/O error (see ``open_retrying``).
OPEN_RETRY_S: Final = 5.0


class StoreError(RuntimeError):
    """The store cannot be used as it is."""


def sqlite_version() -> tuple[int, ...]:
    return tuple(int(part) for part in sqlite3.sqlite_version.split("."))


def require_sqlite() -> None:
    if sqlite_version() < MIN_SQLITE:
        need = ".".join(map(str, MIN_SQLITE))
        raise StoreError(f"SQLite {sqlite3.sqlite_version} is older than {need}")


def open_retrying[T](
    action: Callable[[], T],
    *,
    budget_s: float = OPEN_RETRY_S,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Runs ``action`` (open a connection and touch the file), retrying a transient I/O error.

    After a process that held the database is killed, Windows releases its file locks with a
    delay that "depends upon available system resources", and until then "access to these files
    may be denied" (LockFileEx, https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex).
    SQLite reports that as a disk I/O error. Restarting right after a crash must not fail for
    it, so opening retries with growing delays for up to ``budget_s`` seconds; any other error,
    or one that outlasts the budget, is raised.
    """
    delay = 0.05
    waited = 0.0
    while True:
        try:
            return action()
        except sqlite3.OperationalError as exc:
            if "disk i/o error" not in str(exc).lower() or waited >= budget_s:
                raise
            log.warning(
                "database not ready; retrying",
                extra={"fields": {"error": str(exc), "waited_s": round(waited, 2)}},
            )
            sleep(delay)
            waited += delay
            delay = min(delay * 2, 1.0)


def _configure(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect_writer(path: Path) -> sqlite3.Connection:
    """The write connection: creates the file and its directory if needed, WAL on."""
    require_sqlite()
    path.parent.mkdir(parents=True, exist_ok=True)

    def open_() -> tuple[sqlite3.Connection, str]:
        connection = sqlite3.connect(path, autocommit=True, check_same_thread=False)
        try:
            _configure(connection)
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            connection.execute("PRAGMA synchronous = NORMAL")
        except BaseException:
            connection.close()
            raise
        return connection, mode

    connection, mode = open_retrying(open_)
    if mode.lower() != "wal":
        connection.close()
        raise StoreError(f"{path}: cannot use WAL (journal_mode is {mode})")
    return connection


def connect_reader(path: Path) -> sqlite3.Connection:
    """A read-only connection to an existing database."""
    require_sqlite()
    if not path.is_file():
        raise StoreError(f"{path}: no database (nothing has been stored yet)")
    uri = f"{path.resolve().as_uri()}?mode=ro"

    def open_() -> sqlite3.Connection:
        connection = sqlite3.connect(uri, uri=True, autocommit=True, check_same_thread=False)
        try:
            _configure(connection)
            connection.execute("PRAGMA schema_version").fetchone()  # touches the file
        except BaseException:
            connection.close()
            raise
        return connection

    return open_retrying(open_)
