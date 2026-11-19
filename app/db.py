"""SQLite helpers: connections, custom SQL functions, transactions."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .constants import APOSTROPHES
from .grading import attendance_rate, round1
from .migrations import migrate

Row = dict[str, Any]

_UA_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_UA_ORDER = {ch: i for i, ch in enumerate(_UA_ALPHABET)}
_APOSTROPHE_MAP = str.maketrans({ch: "ʼ" for ch in APOSTROPHES})


def ulower(text: Any) -> Any:
    """Casefold (Unicode-aware) and normalize apostrophes to ʼ; used for search."""
    return text.casefold().translate(_APOSTROPHE_MAP) if isinstance(text, str) else text


def uupper(text: Any) -> Any:
    return text.upper() if isinstance(text, str) else text


def uk_sort_key(text: str) -> tuple:
    """Sort key following Ukrainian alphabet order."""
    key = []
    for ch in text.casefold():
        if ch in _UA_ORDER:
            key.append((1, _UA_ORDER[ch]))
        elif ch in APOSTROPHES or ch == "ʼ":
            continue  # apostrophes don't affect order
        else:
            key.append((0 if not ch.isalpha() else 2, ord(ch)))
    return tuple(key)


def _collate_uk(a: str, b: str) -> int:
    ka, kb = uk_sort_key(a), uk_sort_key(b)
    return (ka > kb) - (ka < kb)


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> Row:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection in autocommit mode; use transaction() for explicit transactions."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = _dict_factory
    # Built-in LOWER/UPPER/LIKE are ASCII-only; register Unicode-aware replacements
    conn.create_collation("UK", _collate_uk)
    conn.create_function("ulower", 1, ulower, deterministic=True)
    conn.create_function("uupper", 1, uupper, deterministic=True)
    # Expose app/grading.py formulas to SQL
    conn.create_function("round1", 1, round1, deterministic=True)
    conn.create_function("attendance_rate", 3, attendance_rate, deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: str) -> None:
    """Migrate the schema to the latest version and restrict DB file permissions."""
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
    finally:
        conn.close()
    if os.name == "posix" and db_path != ":memory:":
        os.chmod(db_path, 0o600)  # owner-only access


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic block; BEGIN IMMEDIATE takes the write lock up front so check-then-write is race-free."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        # SQLite may have already rolled back; a second ROLLBACK would mask the original error
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def one(conn: sqlite3.Connection, sql: str, params: Any = ()) -> Row | None:
    return conn.execute(sql, params).fetchone()


def all_rows(conn: sqlite3.Connection, sql: str, params: Any = ()) -> list[Row]:
    return conn.execute(sql, params).fetchall()


def scalar(conn: sqlite3.Connection, sql: str, params: Any = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else next(iter(row.values()))
