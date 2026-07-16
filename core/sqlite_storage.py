from __future__ import annotations

import sqlite3
from pathlib import Path


SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MS = 5_000


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open SQLite with one consistent concurrency and integrity policy."""
    connection = sqlite3.connect(path, timeout=SQLITE_TIMEOUT_SECONDS)
    connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def enable_wal(connection: sqlite3.Connection) -> None:
    """Enable persistent WAL mode during schema initialization."""
    connection.execute("PRAGMA journal_mode=WAL")
