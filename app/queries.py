"""SQL shared by several routers."""
from __future__ import annotations

import sqlite3

from .db import all_rows

# Subject with teacher name and group count
SUBJECT_SELECT = """
    SELECT sb.*, u.full_name AS teacher_name,
           (SELECT COUNT(*) FROM group_subjects WHERE subject_id = sb.id) AS groups_count
    FROM subjects sb LEFT JOIN users u ON u.id = sb.teacher_id"""

# Student's current group (param: student id); stored as a snapshot in grades/attendance.group_id
STUDENT_GROUP = "(SELECT group_id FROM students WHERE id = ?)"

Link = tuple[int, int]  # (group_id, subject_id)


def links_of(db: sqlite3.Connection, *, group_id: int | None = None, subject_id: int | None = None) -> set[Link]:
    """Group-subject links for one group or one subject."""
    column, value = ("group_id", group_id) if group_id is not None else ("subject_id", subject_id)
    rows = all_rows(db, f"SELECT group_id, subject_id FROM group_subjects WHERE {column} = ?", (value,))
    return {(r["group_id"], r["subject_id"]) for r in rows}


def save_links(db: sqlite3.Connection, old: set[Link], new: set[Link]) -> None:
    """Sync links from old to new: delete removed, insert added."""
    db.executemany("DELETE FROM group_subjects WHERE group_id = ? AND subject_id = ?", sorted(old - new))
    db.executemany("INSERT INTO group_subjects (group_id, subject_id) VALUES (?, ?)", sorted(new - old))
