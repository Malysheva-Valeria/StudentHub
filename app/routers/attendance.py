from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..db import all_rows, one, transaction
from ..deps import CurrentUser, Db, QueryDate, QueryId, UserScope, assert_can_manage_subject, assert_group_in_scope
from ..errors import bad_request
from ..rules import Scope, check_enrolment, check_no_foreign_records, check_group_studies, check_lesson_date, check_unique_students
from ..queries import STUDENT_GROUP
from ..schemas import AttendanceBulk
from ..stats import Filters, student_attendance

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


@router.get("/sheet")
def sheet(scope: UserScope, db: Db, group_id: QueryId = None, subject_id: QueryId = None, date: QueryDate = None):
    """Lesson sheet: active group students enrolled by the date, with their status. `marked` = records exist for this group."""
    if not group_id or not subject_id or not date:
        raise bad_request("Вкажіть групу, дисципліну та дату")
    check_lesson_date(date)
    assert_group_in_scope(db, scope, group_id)
    check_group_studies(db, group_id, subject_id)
    p = {"group": group_id, "subject": subject_id, "date": date}
    rows = all_rows(db, """
        SELECT s.id AS student_id, s.last_name, s.first_name, s.record_book, a.status
        FROM students s
        LEFT JOIN attendance a ON a.student_id = s.id AND a.subject_id = :subject AND a.date = :date
                               AND a.group_id = :group
        WHERE s.group_id = :group AND s.status = 'active' AND s.enrolled_at <= :date
          -- skip transferred students already marked for this date in their previous group
          AND NOT EXISTS (SELECT 1 FROM attendance o WHERE o.student_id = s.id AND o.subject_id = :subject
                          AND o.date = :date AND o.group_id IS NOT :group)
        ORDER BY s.last_name COLLATE UK, s.first_name COLLATE UK""", p)
    marked = one(db, """SELECT EXISTS(SELECT 1 FROM attendance
                        WHERE group_id = :group AND subject_id = :subject AND date = :date) AS marked""", p)["marked"]
    return {"date": date, "group_id": group_id, "subject_id": subject_id, "marked": bool(marked), "rows": rows}


@router.post("/bulk")
def save_bulk(body: AttendanceBulk, user: CurrentUser, db: Db):
    """Save lesson attendance (atomic upsert); same checks as grades."""
    check_unique_students([r.student_id for r in body.records])
    with transaction(db):
        assert_can_manage_subject(db, user, body.subject_id)
        check_lesson_date(body.date)
        students = {f"records.{i}.student_id": r.student_id for i, r in enumerate(body.records)}
        check_enrolment(db, body.subject_id, body.date, students, Scope.of(user))
        check_no_foreign_records(db, "attendance", body.subject_id, body.date, students)
        db.executemany(f"""
            INSERT INTO attendance (student_id, subject_id, date, status, teacher_id, group_id)
            VALUES (?, ?, ?, ?, ?, {STUDENT_GROUP})
            ON CONFLICT (student_id, subject_id, date)
            DO UPDATE SET status = excluded.status, teacher_id = excluded.teacher_id""",
            [(r.student_id, body.subject_id, body.date, r.status, user["id"], r.student_id) for r in body.records])
    return {"saved": len(body.records)}


@router.get("/summary")
def summary(
    scope: UserScope, db: Db, group_id: QueryId = None, subject_id: QueryId = None,
    date_from: Annotated[QueryDate, Query(alias="from")] = None, date_to: Annotated[QueryDate, Query(alias="to")] = None,
):
    """Per-student attendance summary for a period (same as the attendance report)."""
    return student_attendance(db, scope, Filters(group_id, subject_id, date_from, date_to))
