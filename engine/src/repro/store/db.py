"""SQLite connections for the store (ARCHITECTURE §11).

Every connection runs in explicit-transaction mode (``autocommit=True``: the library never opens
a transaction on its own, so ``BEGIN IMMEDIATE`` and ``COMMIT`` are ours), with foreign keys on
and a busy timeout. The write connection also sets WAL and ``synchronous=NORMAL``; read-only
connections open the file with ``mode=ro`` and can never write.
"""

import sqlite3
from pathlib import Path
from typing import Final

#: STRICT tables need SQLite 3.37.0 (https://www.sqlite.org/stricttables.html).
MIN_SQLITE: Final = (3, 37, 0)
BUSY_TIMEOUT_MS: Final = 5_000


class StoreError(RuntimeError):
    """The store cannot be used as it is."""


def sqlite_version() -> tuple[int, ...]:
    return tuple(int(part) for part in sqlite3.sqlite_version.split("."))


def require_sqlite() -> None:
    if sqlite_version() < MIN_SQLITE:
        need = ".".join(map(str, MIN_SQLITE))
        raise StoreError(f"SQLite {sqlite3.sqlite_version} is older than {need}")


def _configure(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def connect_writer(path: Path) -> sqlite3.Connection:
    """The write connection: creates the file and its directory if needed, WAL on."""
    require_sqlite()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    _configure(connection)
    mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        connection.close()
        raise StoreError(f"{path}: cannot use WAL (journal_mode is {mode})")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def connect_reader(path: Path) -> sqlite3.Connection:
    """A read-only connection to an existing database."""
    require_sqlite()
    if not path.is_file():
        raise StoreError(f"{path}: no database (nothing has been stored yet)")
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro", uri=True, autocommit=True, check_same_thread=False
    )
    return _configure(connection)
