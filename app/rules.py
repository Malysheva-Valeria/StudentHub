"""Domain rules: data visibility, grading/attendance checks, academic debt."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .constants import CONTROL_UA, FINAL_TYPES, MIN_BIRTH_DATE, MIN_DATE, PASS_SCORE, STATUS_UA
from .db import Row, all_rows, one, scalar
from .errors import bad_request, conflict
from .utils import today


# ---------- Data scope ----------
# A teacher's groups: those studying their subjects plus those they curate.
TEACHER_GROUPS_SQL = """
    SELECT gs.group_id FROM group_subjects gs JOIN subjects sb ON sb.id = gs.subject_id WHERE sb.teacher_id = :scope_user
    UNION
    SELECT g.id FROM groups g WHERE g.curator_id = :scope_user"""


@dataclass(frozen=True)
class Scope:
    """Visibility scope of the current user; user_id=None means unrestricted (admin)."""

    user_id: int | None = None

    @classmethod
    def of(cls, user: Row) -> "Scope":
        """Scope for a user: unrestricted for admin, own groups for a teacher."""
        return cls(None if user["role"] == "admin" else user["id"])

    @property
    def is_limited(self) -> bool:
        return self.user_id is not None

    def sql(self, group_column: str, params: dict) -> str:
        """SQL condition: `group_column` is in scope (always true for admin)."""
        if self.user_id is None:
            return "1"
        params["scope_user"] = self.user_id
        return f"{group_column} IN ({TEACHER_GROUPS_SQL})"

    def subject_sql(self, subject_column: str, params: dict) -> str:
        """SQL condition: subject is studied by the teacher's groups or taught by the teacher."""
        if self.user_id is None:
            return "1"
        params["scope_user"] = self.user_id
        return (f"{subject_column} IN (SELECT gs.subject_id FROM group_subjects gs WHERE gs.group_id IN ({TEACHER_GROUPS_SQL})"
                " UNION SELECT sb2.id FROM subjects sb2 WHERE sb2.teacher_id = :scope_user)")

    def group_ids(self, db: sqlite3.Connection) -> set[int] | None:
        if self.user_id is None:
            return None
        return {r["group_id"] for r in all_rows(db, TEACHER_GROUPS_SQL, {"scope_user": self.user_id})}

    def hide_private(self, student: Row) -> Row:
        """Hide birth date and phone from teachers."""
        if self.user_id is not None:
            student["birth_date"] = None
            student["phone"] = None
        return student


# ---------- Subject result and academic debt ----------
LATEST_FINAL_SQL = """
    SELECT student_id, subject_id, value FROM (
        SELECT gr.student_id, gr.subject_id, gr.value,
               ROW_NUMBER() OVER (PARTITION BY gr.student_id, gr.subject_id ORDER BY gr.date DESC, gr.id DESC) AS rn
        FROM grades gr WHERE gr.type IN ('exam', 'credit') {extra}
    ) WHERE rn = 1"""


def latest_finals_sql(extra: str = "") -> str:
    """Latest final grade (exam/credit) per student and subject, by date then id.

    A result below PASS_SCORE is a debt, so a passing retake clears it.
    `extra`: additional conditions on `gr`, starting with AND.
    """
    return LATEST_FINAL_SQL.format(extra=extra)


def is_debt(final_value: int | None) -> bool:
    return final_value is not None and final_value < PASS_SCORE


# ---------- Grade and attendance checks ----------
def check_lesson_date(value: str, field: str = "date") -> None:
    """Lesson date must be between MIN_DATE and today."""
    if value > today():
        raise bad_request("Дата не може бути в майбутньому", {field: "Дата не може бути в майбутньому"})
    if value < MIN_DATE:
        raise bad_request(f"Дата не може бути раніше {MIN_DATE}", {field: f"Не раніше {MIN_DATE}"})


def check_grade_type(subject: Row, grade_type: str) -> None:
    """A final grade type must match the subject's control form."""
    if grade_type in FINAL_TYPES and grade_type != subject["control"]:
        msg = f"Форма контролю з цієї дисципліни — {CONTROL_UA[subject['control']]}"
        raise bad_request(msg, {"type": msg})


def check_unique_students(student_ids: Sequence[int]) -> None:
    """Each student may appear only once in a bulk request."""
    seen: set[int] = set()
    for i, sid in enumerate(student_ids):
        if sid in seen:
            raise bad_request("Студента вказано двічі", {f"records.{i}.student_id": "Студента вказано двічі"})
        seen.add(sid)


def _ua_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def check_enrolment(db: sqlite3.Connection, subject_id: int, lesson_date: str, students: dict[str, int],
                    scope: Scope, date_key: str | None = None) -> None:
    """Ensure each student exists, is active, in a group studying the subject, and enrolled by the lesson date.

    students: {details key: student id}, e.g. {"records.3.student_id": 7}.
    date_key: details key for the "enrolled after lesson" error; defaults to the student's key.
    Out-of-scope students are reported as not found so their data isn't leaked.
    """
    rows = all_rows(db, """
        SELECT s.id, s.group_id, s.last_name || ' ' || s.first_name AS name, s.status, s.enrolled_at,
               gs.group_id IS NOT NULL AS linked
        FROM students s
        LEFT JOIN group_subjects gs ON gs.group_id = s.group_id AND gs.subject_id = :subject
        WHERE s.id IN (SELECT value FROM json_each(:ids))""",
        {"subject": subject_id, "ids": json.dumps(list(students.values()))})
    found = {r["id"]: r for r in rows}
    visible = scope.group_ids(db)  # None = admin
    for key, sid in students.items():
        s = found.get(sid)
        if s is None or (visible is not None and s["group_id"] not in visible):
            problem = "Студента не знайдено"
        elif s["status"] != "active":
            problem = f"Студент {s['name']} не навчається (статус: {STATUS_UA[s['status']].lower()})"
        elif not s["linked"]:
            problem = f"Група студента {s['name']} не вивчає цю дисципліну"
        elif lesson_date < s["enrolled_at"]:
            problem = f"Студент {s['name']} зарахований {_ua_date(s['enrolled_at'])} — пізніше дати заняття"
            key = date_key or key
        else:
            continue
        raise bad_request(problem, {key: problem})


def check_no_foreign_records(db: sqlite3.Connection, table: str, subject_id: int, lesson_date: str,
                             students: dict[str, int], grade_type: str | None = None) -> None:
    """Reject overwriting a transferred student's record for this lesson saved under their previous group.

    table: "grades" or "attendance" only; students: as in check_enrolment.
    """
    if table not in ("grades", "attendance"):
        raise ValueError(table)
    type_cond = "AND r.type = :type" if table == "grades" else ""
    rows = all_rows(db, f"""
        SELECT r.student_id, g.name AS group_name FROM {table} r
        JOIN students s ON s.id = r.student_id
        LEFT JOIN groups g ON g.id = r.group_id
        WHERE r.subject_id = :subject AND r.date = :date {type_cond}
          AND r.student_id IN (SELECT value FROM json_each(:ids)) AND r.group_id IS NOT s.group_id""",
        {"subject": subject_id, "date": lesson_date, "type": grade_type, "ids": json.dumps(list(students.values()))})
    if rows:
        key = next(k for k, sid in students.items() if sid == rows[0]["student_id"])
        msg = f"Запис за це заняття вже збережено в іншій групі ({rows[0]['group_name'] or 'видалена група'})"
        raise conflict(msg, {key: msg})


def check_group_studies(db: sqlite3.Connection, group_id: int, subject_id: int) -> None:
    """Require the group to study the subject."""
    if not one(db, "SELECT 1 AS ok FROM group_subjects WHERE group_id = ? AND subject_id = ?", (group_id, subject_id)):
        raise bad_request("Група не вивчає цю дисципліну", {"subject_id": "Група не вивчає цю дисципліну"})


def check_links_removable(db: sqlite3.Connection, pairs: Iterable[tuple[int, int]], field: str) -> None:
    """Reject unlinking (group_id, subject_id) pairs that already have grades or attendance in that group.

    field: form field the error is reported under ("subject_ids" or "group_ids").
    """
    pairs = list(pairs)
    if not pairs:
        return
    used = all_rows(db, """
        SELECT g.name AS group_name, sb.name AS subject_name
        FROM json_each(:pairs) p
        JOIN groups g    ON g.id  = json_extract(p.value, '$[0]')
        JOIN subjects sb ON sb.id = json_extract(p.value, '$[1]')
        WHERE EXISTS (SELECT 1 FROM grades     WHERE group_id = g.id AND subject_id = sb.id)
           OR EXISTS (SELECT 1 FROM attendance WHERE group_id = g.id AND subject_id = sb.id)
        ORDER BY g.name COLLATE UK, sb.name COLLATE UK""", {"pairs": json.dumps(pairs)})
    if used:
        names = ", ".join(f"{r['group_name']} — {r['subject_name']}" for r in used)
        msg = f"Неможливо відвʼязати: є оцінки/відвідуваність ({names})"
        raise conflict(msg, {field: msg})


# Form field -> referenced table (table names never come from the request)
REF_TABLES = {"group_id": "groups", "curator_id": "users", "teacher_id": "users",
              "subject_ids": "subjects", "group_ids": "groups"}


def check_refs_exist(db: sqlite3.Connection, refs: dict[str, int | list[int] | None]) -> None:
    """Raise 400 on the field that references a missing group/user/subject."""
    for field, value in refs.items():
        if value is None:
            continue
        ids = set(value) if isinstance(value, list) else {value}
        found = scalar(db, f"SELECT COUNT(*) FROM {REF_TABLES[field]} WHERE id IN (SELECT value FROM json_each(?))",
                       (json.dumps(sorted(ids)),))
        if found != len(ids):
            raise bad_request("Посилання на неіснуючий запис", {field: "Запис не знайдено"})


# ---------- Students ----------
def check_student_dates(birth_date: str | None, enrolled_at: str) -> None:
    """Birth date: MIN_BIRTH_DATE..today and before enrolment; enrolment: MIN_DATE..today + 1 year."""
    t = date.fromisoformat(today())
    if not MIN_DATE <= enrolled_at <= (t + timedelta(days=365)).isoformat():
        raise bad_request("Некоректна дата зарахування", {"enrolled_at": f"Від {MIN_DATE} до сьогодні + 1 рік"})
    if birth_date is not None:
        if not MIN_BIRTH_DATE <= birth_date <= t.isoformat():
            raise bad_request("Некоректна дата народження", {"birth_date": f"Від {MIN_BIRTH_DATE} до сьогодні"})
        if birth_date >= enrolled_at:
            raise bad_request("Дата народження має бути раніше дати зарахування",
                              {"birth_date": "Має бути раніше дати зарахування"})
