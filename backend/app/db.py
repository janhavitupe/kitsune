import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

SCHEMA = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    return settings.data_dir / "kitsune.db"


def connect() -> sqlite3.Connection:
    """Open a connection in autocommit mode; use `transaction()` for multi-statement writes."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # background jobs write while requests read
    return conn


# Columns added after a table first shipped: (table, column, definition). CREATE TABLE IF NOT EXISTS
# doesn't touch existing tables, so databases made earlier get them here.
ADDED_COLUMNS = [
    ("repos", "private_mode", "INTEGER NOT NULL DEFAULT 0"),
]


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        for table, column, definition in ADDED_COLUMNS:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    # IMMEDIATE takes the write lock up front, so reads inside (e.g. next seq, branch head) can't go stale.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
