"""Analytics: dashboard, student card, reports. Aggregates include only active, in-scope students."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .constants import LOW_ATTENDANCE
from .db import Row, all_rows, one, scalar, uk_sort_key
from .grading import ECTS, attendance_rate, avg1, bucket, ects_letter, is_passing, percent, to_ects
from .rules import Scope, is_debt, latest_finals_sql


@dataclass(frozen=True)
class Filters:
    """Report filters: group, subject, inclusive date range."""

    group_id: int | None = None
    subject_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None

    def period(self, alias: str, p: dict) -> str:
        """`AND ...` conditions on subject and period for table `alias` (gr or a)."""
        cond = []
        if self.subject_id:
            cond.append(f"{alias}.subject_id = :f_subject")
            p["f_subject"] = self.subject_id
        if self.date_from:
            cond.append(f"{alias}.date >= :f_from")
            p["f_from"] = self.date_from
        if self.date_to:
            cond.append(f"{alias}.date <= :f_to")
            p["f_to"] = self.date_to
        return "".join(f" AND {c}" for c in cond)

    def students(self, scope: Scope, p: dict) -> str:
        """WHERE for students: active, in scope, optionally one group."""
        where = f"s.status = 'active' AND {scope.sql('s.group_id', p)}"
        if self.group_id:
            where += " AND s.group_id = :f_group"
            p["f_group"] = self.group_id
        return where


NO_FILTERS = Filters()


# ---------- Building blocks ----------
def student_averages(db: sqlite3.Connection, scope: Scope, f: Filters = NO_FILTERS) -> list[Row]:
    """Average grade per active student with grades."""
    p: dict = {}
    return all_rows(db, f"""
        SELECT s.id, s.group_id, s.last_name || ' ' || s.first_name AS name, g.name AS group_name,
               round1(AVG(gr.value)) AS avg_grade, COUNT(gr.id) AS grades_count
        FROM students s
        JOIN grades gr ON gr.student_id = s.id {f.period('gr', p)}
        LEFT JOIN groups g ON g.id = s.group_id
        WHERE {f.students(scope, p)}
        GROUP BY s.id ORDER BY s.id""", p)


def group_averages(students: list[Row]) -> dict[int, float | None]:
    """Group average = mean of student averages (student_averages rows)."""
    by_group: dict[int, list[float]] = defaultdict(list)
    for r in students:
        if r["group_id"] is not None:
            by_group[r["group_id"]].append(r["avg_grade"])
    return {gid: avg1(values) for gid, values in by_group.items()}


def group_attendance(students: list[Row]) -> dict[int, float | None]:
    """Group attendance rate over all marks (student_attendance rows)."""
    sums: dict[int, dict[str, int]] = defaultdict(lambda: {"present": 0, "late": 0, "total": 0})
    for r in students:
        if r["group_id"] is not None:
            for k in ("present", "late", "total"):
                sums[r["group_id"]][k] += r[k]
    return {gid: attendance_rate(t["present"], t["late"], t["total"]) for gid, t in sums.items()}


def subject_averages(db: sqlite3.Connection, scope: Scope = Scope()) -> dict[int, float | None]:
    """Subject average = mean of in-scope active students' averages in that subject."""
    p: dict = {}
    by_subject: dict[int, list[float]] = defaultdict(list)
    for r in all_rows(db, f"""
            SELECT gr.subject_id, round1(AVG(gr.value)) AS avg_grade
            FROM grades gr JOIN students s ON s.id = gr.student_id
            WHERE s.status = 'active' AND {scope.sql('s.group_id', p)}
            GROUP BY gr.subject_id, gr.student_id""", p):
        by_subject[r["subject_id"]].append(r["avg_grade"])
    return {sid: avg1(values) for sid, values in by_subject.items()}


def with_subject_averages(db: sqlite3.Connection, subjects: list[Row], scope: Scope = Scope()) -> list[Row]:
    averages = subject_averages(db, scope)
    for s in subjects:
        s["avg_grade"] = averages.get(s["id"])
    return subjects


def student_attendance(db: sqlite3.Connection, scope: Scope, f: Filters = NO_FILTERS) -> list[Row]:
    """Attendance totals per active student, including those with no marks."""
    p: dict = {}
    rows = all_rows(db, f"""
        SELECT s.id AS student_id, s.record_book, s.last_name || ' ' || s.first_name AS student_name,
               s.group_id, g.name AS group_name, COUNT(a.id) AS total,
               IFNULL(SUM(a.status = 'present'), 0) AS present, IFNULL(SUM(a.status = 'late'), 0) AS late,
               IFNULL(SUM(a.status = 'absent'), 0) AS absent, IFNULL(SUM(a.status = 'excused'), 0) AS excused
        FROM students s
        LEFT JOIN groups g ON g.id = s.group_id
        LEFT JOIN attendance a ON a.student_id = s.id {f.period('a', p)}
        WHERE {f.students(scope, p)}
        GROUP BY s.id ORDER BY g.name COLLATE UK, s.last_name COLLATE UK, s.first_name COLLATE UK""", p)
    for r in rows:
        r["rate"] = attendance_rate(r["present"], r["late"], r["total"])
    return rows


def scoped_groups(db: sqlite3.Connection, scope: Scope) -> list[Row]:
    p: dict = {}
    where = scope.sql("g.id", p)
    return all_rows(db, f"""
        SELECT g.id, g.name, g.course, g.specialty,
               (SELECT COUNT(*) FROM students s WHERE s.group_id = g.id AND s.status = 'active') AS students
        FROM groups g WHERE {where} ORDER BY g.course, g.name COLLATE UK""", p)


def academic_year_start(d: date) -> date:
    """Academic year starts on September 1."""
    return date(d.year if d.month >= 9 else d.year - 1, 9, 1)


def _shift_month(d: date, months: int) -> str:
    idx = d.year * 12 + d.month - 1 + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


# ---------- Dashboard ----------
def dashboard(db: sqlite3.Connection, scope: Scope, today: date) -> dict:
    """Dashboard metrics. `avg_grade_month` is the mean of grades in the month, not of student averages."""
    p: dict = {}
    in_scope = scope.sql("s.group_id", p)
    year_start = academic_year_start(today)
    prev_year_start = date(year_start.year - 1, 9, 1)

    totals = one(db, f"""
        SELECT COUNT(*) AS total,
               IFNULL(SUM(status = 'active'), 0) AS active,
               IFNULL(SUM(enrolled_at >= :y), 0) AS new_this_year,
               IFNULL(SUM(enrolled_at >= :py AND enrolled_at < :y), 0) AS new_prev_year,
               IFNULL(SUM(status = 'active' AND gender = 'M'), 0) AS male,
               IFNULL(SUM(status = 'active' AND gender = 'F'), 0) AS female
        FROM students s WHERE {in_scope}""", {**p, "y": year_start.isoformat(), "py": prev_year_start.isoformat()})

    averages = student_averages(db, scope)
    attendance = student_attendance(db, scope)

    # Monthly trend: one grouped query per table
    month_att = all_rows(db, f"""
        SELECT substr(a.date, 1, 7) AS month,
               SUM(a.status = 'present') AS present, SUM(a.status = 'late') AS late,
               SUM(a.status = 'absent') AS absent, SUM(a.status = 'excused') AS excused, COUNT(*) AS total
        FROM attendance a JOIN students s ON s.id = a.student_id
        WHERE s.status = 'active' AND {in_scope} GROUP BY month ORDER BY month""", p)
    month_avg = {r["month"]: r["avg"] for r in all_rows(db, f"""
        SELECT substr(gr.date, 1, 7) AS month, round1(AVG(gr.value)) AS avg
        FROM grades gr JOIN students s ON s.id = gr.student_id
        WHERE s.status = 'active' AND {in_scope} GROUP BY month""", p)}
    month_rate = {r["month"]: attendance_rate(r["present"], r["late"], r["total"]) for r in month_att}
    # last 6 months that had lessons (holidays skipped)
    trend = [{"month": r["month"], "present": r["present"], "late": r["late"], "absent": r["absent"],
              "excused": r["excused"], "rate": month_rate[r["month"]], "avg_grade": month_avg.get(r["month"])}
             for r in month_att[-6:]]
    cur_month, prev_month = _shift_month(today, 0), _shift_month(today, -1)
    att_sum = {k: sum(r[k] for r in month_att) for k in ("present", "late", "total")}

    distribution = {e["ects"]: 0 for e in ECTS}
    for r in averages:
        distribution[ects_letter(r["avg_grade"])] += 1

    # group aggregates reuse the per-student rows
    group_avg, group_att = group_averages(averages), group_attendance(attendance)
    groups = sorted(scoped_groups(db, scope), key=lambda g: uk_sort_key(g["name"]))
    by_group = [{"id": g["id"], "name": g["name"], "avg_grade": group_avg.get(g["id"]),
                 "attendance_rate": group_att.get(g["id"])} for g in groups]

    low = [r for r in attendance if r["rate"] is not None and r["rate"] < LOW_ATTENDANCE]
    top = sorted((r for r in averages if r["grades_count"] >= 3), key=lambda r: (-r["avg_grade"], uk_sort_key(r["name"])))[:5]

    p_recent: dict = {}
    recent_grades = all_rows(db, f"""
        SELECT gr.id, gr.value, gr.type, gr.date, sb.name AS subject_name,
               s.last_name || ' ' || s.first_name AS student_name
        FROM grades gr JOIN students s ON s.id = gr.student_id JOIN subjects sb ON sb.id = gr.subject_id
        WHERE {scope.sql('gr.group_id', p_recent)}
        ORDER BY gr.created_at DESC, gr.id DESC LIMIT 6""", p_recent)

    subjects_count = (scalar(db, "SELECT COUNT(*) FROM subjects") if not scope.is_limited
                      else scalar(db, "SELECT COUNT(*) FROM subjects WHERE teacher_id = ?", (scope.user_id,)))
    # Active teachers; for a teacher, only those teaching subjects in their scope
    p_teachers: dict = {}
    teachers_count = scalar(db, f"""
        SELECT COUNT(*) FROM users u WHERE u.role = 'teacher' AND u.is_active = 1
          AND ({'1' if not scope.is_limited else
                f"u.id IN (SELECT sb.teacher_id FROM subjects sb WHERE {scope.subject_sql('sb.id', p_teachers)})"})""",
        p_teachers)
    return {
        "kpi": {
            "total_students": totals["total"],
            "active_students": totals["active"],
            "avg_grade": avg1([r["avg_grade"] for r in averages]),
            "avg_grade_month": month_avg.get(cur_month),
            "avg_grade_prev_month": month_avg.get(prev_month),
            "attendance_rate": attendance_rate(att_sum["present"], att_sum["late"], att_sum["total"]),
            "attendance_month": month_rate.get(cur_month),
            "attendance_prev_month": month_rate.get(prev_month),
            "success_rate": percent(sum(1 for r in averages if is_passing(r["avg_grade"])), len(averages)),
            "low_attendance": len(low),
            "teachers": teachers_count,
            "groups": len(groups),
            "subjects": subjects_count,
            "new_this_year": totals["new_this_year"],
            "new_prev_year": totals["new_prev_year"],
            "academic_year_start": year_start.isoformat(),
        },
        "gender": {"male": totals["male"], "female": totals["female"]},
        "trend": trend,
        "distribution": distribution,
        "by_group": by_group,
        "top_students": [{"id": r["id"], "name": r["name"], "group_name": r["group_name"], "avg_grade": r["avg_grade"]}
                         for r in top],
        "at_risk": [{"id": r["student_id"], "name": r["student_name"], "group_name": r["group_name"], "rate": r["rate"]}
                    for r in sorted(low, key=lambda r: r["rate"])[:5]],
        "recent_grades": recent_grades,
    }



# ---------- Student card ----------
def student_card(db: sqlite3.Connection, student: Row) -> dict:
    """Per-subject results, attendance, recent grades. Subject ECTS uses the final grade, else the average."""
    sid = student["id"]
    subjects = all_rows(db, f"""
        SELECT sb.id, sb.name, sb.control, round1(AVG(gr.value)) AS avg_grade, COUNT(gr.id) AS grades_count,
               lf.value AS final_grade
        FROM grades gr JOIN subjects sb ON sb.id = gr.subject_id
        LEFT JOIN ({latest_finals_sql("AND gr.student_id = :sid")}) lf ON lf.subject_id = sb.id
        WHERE gr.student_id = :sid
        GROUP BY sb.id ORDER BY sb.name COLLATE UK""", {"sid": sid})
    for s in subjects:
        s["ects"] = to_ects(s["final_grade"] if s["final_grade"] is not None else s["avg_grade"])
        s["debt"] = is_debt(s["final_grade"])

    att = one(db, """
        SELECT COUNT(*) AS total,
               IFNULL(SUM(status = 'present'), 0) AS present, IFNULL(SUM(status = 'absent'), 0) AS absent,
               IFNULL(SUM(status = 'late'), 0) AS late, IFNULL(SUM(status = 'excused'), 0) AS excused
        FROM attendance WHERE student_id = ?""", (sid,))
    att["rate"] = attendance_rate(att["present"], att["late"], att["total"])

    recent = all_rows(db, """
        SELECT gr.*, sb.name AS subject_name FROM grades gr JOIN subjects sb ON sb.id = gr.subject_id
        WHERE gr.student_id = ? ORDER BY gr.date DESC, gr.id DESC LIMIT 15""", (sid,))
    return {**student, "ects": to_ects(student["avg_grade"]), "subjects": subjects, "attendance": att, "recent_grades": recent}


# ---------- Reports ----------
def performance(db: sqlite3.Connection, scope: Scope, f: Filters) -> dict:
    """Performance report: average, ECTS, bucket and debt count per active student."""
    p: dict = {}
    rows = all_rows(db, f"""
        SELECT s.id AS student_id, s.record_book, s.last_name || ' ' || s.first_name AS student_name,
               g.name AS group_name, COUNT(gr.id) AS grades_count,
               round1(AVG(gr.value)) AS avg_grade, MIN(gr.value) AS min_grade, MAX(gr.value) AS max_grade
        FROM students s
        LEFT JOIN groups g ON g.id = s.group_id
        LEFT JOIN grades gr ON gr.student_id = s.id {f.period('gr', p)}
        WHERE {f.students(scope, p)}
        GROUP BY s.id ORDER BY g.name COLLATE UK, s.last_name COLLATE UK, s.first_name COLLATE UK""", p)

    pd: dict = {}
    finals = all_rows(db, latest_finals_sql(f.period("gr", pd)), pd)
    debts: dict[int, int] = defaultdict(int)
    for r in finals:
        if is_debt(r["value"]):
            debts[r["student_id"]] += 1

    counts = {"excellent": 0, "good": 0, "satisfactory": 0, "failing": 0}
    items = []
    for r in rows:
        e = to_ects(r["avg_grade"])
        if (b := bucket(r["avg_grade"])) is not None:
            counts[b] += 1
        items.append({**r, "ects": e["ects"] if e else None, "national": e["national"] if e else None,
                      "debts": debts.get(r["student_id"], 0)})

    graded = [r["avg_grade"] for r in items if r["avg_grade"] is not None]
    summary = {
        "students": len(items),
        "avg_grade": avg1(graded),
        **counts,
        "with_debts": sum(1 for r in items if r["debts"] > 0),
        "quality": percent(counts["excellent"] + counts["good"], len(graded)),  # quality: excellent + good
        "success": percent(len(graded) - counts["failing"], len(graded)),       # success: not failing
    }
    return {"items": items, "summary": summary}


def attendance(db: sqlite3.Connection, scope: Scope, f: Filters) -> dict:
    items = student_attendance(db, scope, f)
    t = {k: sum(r[k] for r in items) for k in ("total", "present", "late", "absent", "excused")}
    return {"items": items, "summary": {
        **t, "students": len(items),
        "rate": attendance_rate(t["present"], t["late"], t["total"]),
        "low": sum(1 for r in items if r["rate"] is not None and r["rate"] < LOW_ATTENDANCE),
    }}


def groups_report(db: sqlite3.Connection, scope: Scope, f: Filters) -> list[Row]:
    """Compare in-scope groups by average and attendance; the group filter is ignored."""
    period = Filters(subject_id=f.subject_id, date_from=f.date_from, date_to=f.date_to)
    group_avg = group_averages(student_averages(db, scope, period))
    group_att = group_attendance(student_attendance(db, scope, period))
    return [{**g, "avg_grade": group_avg.get(g["id"]), "attendance_rate": group_att.get(g["id"])}
            for g in scoped_groups(db, scope)]
