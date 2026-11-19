-- StudentHub base schema (migration v1); later changes are in app/migrations.py.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('admin', 'teacher')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    token_version INTEGER NOT NULL DEFAULT 0, -- unused since v4 (sessions table)
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

-- Subjects taught to each group
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
