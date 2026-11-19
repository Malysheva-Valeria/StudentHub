"""Schema migrations, including upgrading a pre-migration database (no PRAGMA user_version)."""
import sqlite3

import pytest

from app.db import connect, init_db
from app.migrations import LATEST_VERSION, migrate, schema_version

# Schema before migrations were introduced (user_version = 0)
OLD_SCHEMA = """
-- StudentHub schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('admin', 'teacher')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    token_version INTEGER NOT NULL DEFAULT 0, -- bumped on password change/block to invalidate sessions
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    course     INTEGER NOT NULL CHECK (course BETWEEN 1 AND 6),
    specialty  TEXT    NOT NULL,
    curator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    last_name    TEXT    NOT NULL,
    first_name   TEXT    NOT NULL,
    middle_name  TEXT,
    gender       TEXT    NOT NULL CHECK (gender IN ('M', 'F')),
    birth_date   TEXT,
    email        TEXT,
    phone        TEXT,
    record_book  TEXT    NOT NULL UNIQUE,
    group_id     INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    status       TEXT    NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'academic_leave', 'expelled', 'graduated')),
    enrolled_at  TEXT    NOT NULL DEFAULT (date('now')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_id);
CREATE INDEX IF NOT EXISTS idx_students_name  ON students(last_name, first_name);

CREATE TABLE IF NOT EXISTS subjects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    code       TEXT,
    credits    REAL    NOT NULL DEFAULT 3 CHECK (credits > 0),
    hours      INTEGER NOT NULL DEFAULT 90 CHECK (hours > 0),
    semester   INTEGER NOT NULL DEFAULT 1 CHECK (semester BETWEEN 1 AND 12),
    control    TEXT    NOT NULL DEFAULT 'exam' CHECK (control IN ('exam', 'credit')),
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Subjects studied by each group
CREATE TABLE IF NOT EXISTS group_subjects (
    group_id   INTEGER NOT NULL REFERENCES groups(id)   ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, subject_id)
);

CREATE TABLE IF NOT EXISTS grades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    value      INTEGER NOT NULL CHECK (value BETWEEN 0 AND 100),
    type       TEXT    NOT NULL DEFAULT 'current'
               CHECK (type IN ('current', 'module', 'exam', 'credit')),
    date       TEXT    NOT NULL,
    comment    TEXT,
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);
CREATE INDEX IF NOT EXISTS idx_grades_subject ON grades(subject_id, date);

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, subject_id, date)
);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);
CREATE INDEX IF NOT EXISTS idx_attendance_subject ON attendance(subject_id, date);
"""


@pytest.fixture
def old_db(tmp_path):
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.executescript("""
        INSERT INTO users (username, password_hash, full_name, role) VALUES ('t', 'x', 'T', 'teacher');
        INSERT INTO groups (name, course, specialty) VALUES ('G', 1, 's');
        INSERT INTO subjects (name) VALUES ('S');
        INSERT INTO students (last_name, first_name, gender, record_book, group_id) VALUES ('A', 'B', 'M', 'кн-1', 1);
        INSERT INTO grades (student_id, subject_id, value, type, date) VALUES (1, 1, 50, 'current', '2026-01-10');
        INSERT INTO grades (student_id, subject_id, value, type, date) VALUES (1, 1, 90, 'current', '2026-01-10');
        INSERT INTO grades (student_id, subject_id, value, type, date) VALUES (1, 1, 70, 'module', '2026-01-10');
    """)
    raw.close()
    return path


def test_migrate_from_v0(old_db):
    conn = connect(old_db)
    assert schema_version(conn) == 0
    conn.close()
    init_db(old_db)
    conn = connect(old_db)
    assert schema_version(conn) == LATEST_VERSION
    grades = conn.execute("SELECT value, type FROM grades ORDER BY id").fetchall()
    assert grades == [{"value": 90, "type": "current"}, {"value": 70, "type": "module"}], "дублікат прибрано, лишився новіший"
    assert conn.execute("SELECT record_book FROM students").fetchone()["record_book"] == "КН-1"
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"ux_grades_lesson", "idx_group_subjects_subject"} <= indexes
    assert conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO grades (student_id, subject_id, value, type, date) VALUES (1, 1, 1, 'module', '2026-01-10')")
    conn.close()


def test_migrations_idempotent(tmp_path):
    path = str(tmp_path / "new.db")
    init_db(path)
    conn = connect(path)
    assert schema_version(conn) == LATEST_VERSION
    assert migrate(conn) == 0, "повторний запуск нічого не змінює"
    conn.close()


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    from app import migrations
    path = str(tmp_path / "broken.db")
    init_db(path)
    monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS,
                        (LATEST_VERSION + 1, "broken", "CREATE TABLE extra (id INTEGER); SELECT * FROM no_such_table;")])
    conn = connect(path)
    with pytest.raises(migrations.MigrationError, match=f"версії {LATEST_VERSION + 1}"):
        migrations.migrate(conn)
    assert schema_version(conn) == LATEST_VERSION
    assert conn.execute("SELECT COUNT(*) AS c FROM sqlite_master WHERE name = 'extra'").fetchone()["c"] == 0
    conn.close()


def test_v5_resolves_case_collisions(tmp_path, caplog):
    """Case-only duplicate record books: lowest id keeps it, others get a "-<id>" suffix."""
    path = str(tmp_path / "collide.db")
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.executescript("""
        INSERT INTO students (last_name, first_name, gender, record_book) VALUES ('A', 'A', 'M', 'КН-1');
        INSERT INTO students (last_name, first_name, gender, record_book) VALUES ('B', 'B', 'M', 'кн-1');
        INSERT INTO students (last_name, first_name, gender, record_book) VALUES ('C', 'C', 'M', 'Кн-1');
        INSERT INTO students (last_name, first_name, gender, record_book) VALUES ('D', 'D', 'M', 'кн-2');
    """)
    raw.close()
    with caplog.at_level("WARNING", logger="studenthub"):
        init_db(path)
    conn = connect(path)
    books = [r["record_book"] for r in conn.execute("SELECT record_book FROM students ORDER BY id")]
    assert books == ["КН-1", "КН-1-2", "КН-1-3", "КН-2"]
    assert schema_version(conn) == LATEST_VERSION
    conn.close()
    assert "id 2: «кн-1» → «КН-1-2»" in caplog.text and "id 3" in caplog.text


def test_v6_backfills_group_snapshot(old_db):
    init_db(old_db)
    conn = connect(old_db)
    assert {r["group_id"] for r in conn.execute("SELECT group_id FROM grades")} == {1}
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_grades_group", "idx_attendance_group"} <= indexes
    conn.close()


def test_startup_reports_migration_error_without_traceback(tmp_path):
    """run.py exits with a readable migration error and no traceback on a broken database."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / "broken.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 1")  # version 1 with no tables, so migration 2 fails
    raw.close()
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "DB_PATH": str(path), "APP_ENV": "development", "PORT": "0"}
    proc = subprocess.run([sys.executable, "run.py"], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "Помилка бази даних: не вдалося оновити базу даних до версії 2" in proc.stderr
    assert "Traceback" not in proc.stderr
