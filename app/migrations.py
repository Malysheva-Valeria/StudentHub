"""Versioned schema migrations.

The version is stored in PRAGMA user_version; each pending migration (SQL script or
Python function) runs in its own transaction.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

log = logging.getLogger("studenthub")


class MigrationError(RuntimeError):
    """A migration failed; the DB stays at the previous version."""


def _uppercase_record_books(conn: sqlite3.Connection) -> None:
    """Uppercase record book numbers; case-insensitive duplicates (except the lowest id) get a "-<id>" suffix."""
    rows = conn.execute("SELECT id, record_book FROM students ORDER BY id").fetchall()
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[r["record_book"].upper()].append(r)
    taken = set(by_key)
    new_values: dict[int, str] = {}
    renamed = []
    for key, same in by_key.items():
        for i, r in enumerate(same):
            value = key
            if i > 0:  # case-insensitive duplicate
                value = f"{key}-{r['id']}"
                while value in taken:
                    value += f"-{r['id']}"
                taken.add(value)
                renamed.append(f"id {r['id']}: «{r['record_book']}» → «{value}»")
            if value != r["record_book"]:
                new_values[r["id"]] = value
    # Two passes via temporary values so intermediate states don't violate UNIQUE
    conn.executemany("UPDATE students SET record_book = ? WHERE id = ?", [(f"#tmp#{sid}", sid) for sid in new_values])
    conn.executemany("UPDATE students SET record_book = ? WHERE id = ?", [(v, sid) for sid, v in new_values.items()])
    if renamed:
        log.warning("Міграція v5: номери залікових книжок, що збігалися без урахування регістру, змінено: %s",
                    "; ".join(renamed))


Step = str | Callable[[sqlite3.Connection], None]

# (version, description, SQL or function). Append only.
MIGRATIONS: list[tuple[int, str, Step]] = [
    (1, "Базова схема", SCHEMA_PATH.read_text(encoding="utf-8")),
    (2, "Одна оцінка на заняття: унікальний індекс (студент, дисципліна, дата, тип)", """
        -- keep only the newest of existing duplicates
        DELETE FROM grades WHERE id NOT IN (
            SELECT MAX(id) FROM grades GROUP BY student_id, subject_id, date, type);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_grades_lesson ON grades(student_id, subject_id, date, type);
    """),
    (3, "Індекс для пошуку груп за дисципліною", """
        CREATE INDEX IF NOT EXISTS idx_group_subjects_subject ON group_subjects(subject_id);
    """),
    (4, "Серверні сесії", """
        CREATE TABLE IF NOT EXISTS sessions (
            id           TEXT    PRIMARY KEY,               -- secrets.token_urlsafe(32)
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at   INTEGER NOT NULL,                  -- Unix time, seconds
            last_seen_at INTEGER NOT NULL,
            expires_at   INTEGER NOT NULL                   -- absolute expiry
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    """),
    (5, "Номер залікової книжки великими літерами (унікальність без урахування регістру)", _uppercase_record_books),
    (6, "Група, в якій виставлено оцінку / відмічено відвідуваність (знімок на момент запису)", """
        ALTER TABLE grades     ADD COLUMN group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL;
        ALTER TABLE attendance ADD COLUMN group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL;
        -- backfill with the student's current group
        UPDATE grades     SET group_id = (SELECT s.group_id FROM students s WHERE s.id = grades.student_id);
        UPDATE attendance SET group_id = (SELECT s.group_id FROM students s WHERE s.id = attendance.student_id);
        CREATE INDEX IF NOT EXISTS idx_grades_group     ON grades(group_id, subject_id, date);
        CREATE INDEX IF NOT EXISTS idx_attendance_group ON attendance(group_id, subject_id, date);
    """),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()["user_version"]


def _apply(conn: sqlite3.Connection, version: int, step: Step) -> None:
    # Bump user_version inside the same transaction as the schema change
    if isinstance(step, str):
        conn.executescript(f"BEGIN IMMEDIATE;\n{step}\nPRAGMA user_version = {version:d};\nCOMMIT;")
        return
    conn.execute("BEGIN IMMEDIATE")
    step(conn)
    conn.execute(f"PRAGMA user_version = {version:d}")
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; return how many were applied."""
    applied = 0
    for version, description, step in MIGRATIONS:
        if version <= schema_version(conn):
            continue
        try:
            _apply(conn, version, step)
        except sqlite3.Error as e:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(
                f"не вдалося оновити базу даних до версії {version} («{description}»): {e}. "
                "Зміни цієї версії скасовано, дані не пошкоджено. Зробіть резервну копію файлу бази "
                "та зверніться до розробника.") from e
        applied += 1
    return applied
