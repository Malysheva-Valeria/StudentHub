from __future__ import annotations

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Query, Response

from ..db import all_rows, one, transaction
from ..deps import (CurrentUser, Db, Limit, PageNo, PathId, QueryDate, QueryId, Search, UserScope,
                    assert_can_manage_subject, assert_group_in_scope)
from ..errors import bad_request, conflict, not_found
from ..grading import avg1, ects_letter, to_ects
from ..queries import STUDENT_GROUP
from ..rules import (Scope, check_enrolment, check_grade_type, check_group_studies, check_lesson_date,
                     check_no_foreign_records, check_unique_students)
from ..schemas import GradeBulk, GradeCreate, GradeDetail, GradePage, GradeType, GradeUpdate
from ..utils import like_pattern, pages_count

router = APIRouter(prefix="/api/grades", tags=["grades"])

DUPLICATE = "Оцінка за це заняття вже існує — відредагуйте її"

# Grade group is the gr.group_id snapshot, so grades stay with the previous group after a transfer.
SELECT = """
    SELECT gr.*, sb.name AS subject_name, g.name AS group_name,
           s.last_name || ' ' || s.first_name AS student_name, u.full_name AS teacher_name
    FROM grades gr
    JOIN students s  ON s.id = gr.student_id
    JOIN subjects sb ON sb.id = gr.subject_id
    LEFT JOIN groups g ON g.id = gr.group_id
    LEFT JOIN users u  ON u.id = gr.teacher_id"""


def get_grade(db: sqlite3.Connection, grade_id: int, scope: Scope = Scope()) -> dict:
    """Fetch a grade; 404 if outside the teacher's scope."""
    p: dict = {"id": grade_id}
    g = one(db, f"{SELECT} WHERE gr.id = :id AND {scope.sql('gr.group_id', p)}", p)
    if not g:
        raise not_found("Оцінку не знайдено")
    return {**g, "ects": to_ects(g["value"])}


@router.get("", response_model=GradePage)
def list_grades(
    scope: UserScope, db: Db,
    student_id: QueryId = None, subject_id: QueryId = None, group_id: QueryId = None,
    type: GradeType | None = None,  # noqa: A002 — API parameter name
    search: Search = None,
    date_from: Annotated[QueryDate, Query(alias="from")] = None,
    date_to: Annotated[QueryDate, Query(alias="to")] = None,
    page: PageNo = 1, limit: Limit = 25,
):
    p: dict = {}
    where = [scope.sql("gr.group_id", p)]
    for key, value, col in (("student_id", student_id, "gr.student_id"), ("subject_id", subject_id, "gr.subject_id"),
                            ("group_id", group_id, "gr.group_id"), ("type", type, "gr.type")):
        if value is not None:
            where.append(f"{col} = :{key}")
            p[key] = value
    if date_from:
        where.append("gr.date >= :date_from")
        p["date_from"] = date_from
    if date_to:
        where.append("gr.date <= :date_to")
        p["date_to"] = date_to
    if search and search.strip():
        where.append("ulower(s.last_name || ' ' || s.first_name) LIKE ulower(:search) ESCAPE '\\'")
        p["search"] = like_pattern(search)
    w = f"WHERE {' AND '.join(where)}"

    stats = one(db, f"SELECT COUNT(*) AS total, round1(AVG(gr.value)) AS avg FROM grades gr JOIN students s ON s.id = gr.student_id {w}", p)
    items = all_rows(db, f"{SELECT} {w} ORDER BY gr.date DESC, gr.id DESC LIMIT :limit OFFSET :offset",
                     {**p, "limit": limit, "offset": (page - 1) * limit})
    for g in items:
        g["ects"] = ects_letter(g["value"])
    return {"items": items, "total": stats["total"], "avg": stats["avg"], "page": page, "limit": limit,
            "pages": pages_count(stats["total"], limit)}


@router.get("/journal")
def journal(scope: UserScope, db: Db, group_id: QueryId = None, subject_id: QueryId = None):
    """Gradebook: group students x lessons (date + type) for a subject.

    Includes transferred-out students with grades in this group (former=true). Only grades saved in this group count.
    """
    if not group_id or not subject_id:
        raise bad_request("Вкажіть групу та дисципліну")
    assert_group_in_scope(db, scope, group_id)
    check_group_studies(db, group_id, subject_id)
    p = {"group": group_id, "subject": subject_id}
    students = all_rows(db, """
        SELECT s.id, s.last_name, s.first_name, s.record_book, s.enrolled_at, s.group_id IS NOT :group AS former
        FROM students s
        WHERE s.status = 'active' AND (s.group_id = :group OR EXISTS (
                  SELECT 1 FROM grades gr WHERE gr.student_id = s.id AND gr.group_id = :group AND gr.subject_id = :subject))
        ORDER BY former, s.last_name COLLATE UK, s.first_name COLLATE UK""", p)
    grades = all_rows(db, """
        SELECT gr.id, gr.student_id, gr.value, gr.type, gr.date FROM grades gr
        WHERE gr.group_id = :group AND gr.subject_id = :subject AND gr.student_id IN (
            SELECT value FROM json_each(:ids)) ORDER BY gr.date, gr.id""",
        {**p, "ids": json.dumps([s["id"] for s in students])})

    columns: dict[str, dict] = {}
    by_student: dict[int, list[dict]] = {}
    for g in grades:
        key = f"{g['date']}|{g['type']}"
        columns.setdefault(key, {"key": key, "date": g["date"], "type": g["type"]})
        by_student.setdefault(g["student_id"], []).append({**g, "key": key})

    rows = []
    for s in students:
        own = by_student.get(s["id"], [])
        cells = {g["key"]: {"id": g["id"], "value": g["value"]} for g in own}  # one grade per lesson (unique index)
        avg = avg1([g["value"] for g in own])
        rows.append({**s, "former": bool(s["former"]), "cells": cells, "avg": avg, "ects": ects_letter(avg)})
    return {"columns": list(columns.values()), "rows": rows}


@router.get("/{grade_id}", response_model=GradeDetail)
def read_grade(grade_id: PathId, scope: UserScope, db: Db):
    return get_grade(db, grade_id, scope)


@router.post("", status_code=201, response_model=GradeDetail)
def create_grade(body: GradeCreate, user: CurrentUser, db: Db):
    with transaction(db):
        subject = assert_can_manage_subject(db, user, body.subject_id)
        check_lesson_date(body.date)
        check_grade_type(subject, body.type)
        check_enrolment(db, body.subject_id, body.date, {"student_id": body.student_id}, Scope.of(user), date_key="date")
        try:
            cur = db.execute(f"""
                INSERT INTO grades (student_id, subject_id, value, type, date, comment, teacher_id, group_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, {STUDENT_GROUP})""",
                (body.student_id, body.subject_id, body.value, body.type, body.date, body.comment, user["id"],
                 body.student_id))
        except sqlite3.IntegrityError:
            raise conflict(DUPLICATE) from None
    return get_grade(db, cur.lastrowid)


@router.post("/bulk", status_code=201)
def create_bulk(body: GradeBulk, user: CurrentUser, db: Db):
    """Bulk-grade a group for one lesson (atomic upsert); empty values are skipped."""
    check_unique_students([r.student_id for r in body.records])
    indexed = [(i, r) for i, r in enumerate(body.records) if r.value is not None]
    if not indexed:
        raise bad_request("Немає оцінок для збереження")
    with transaction(db):
        subject = assert_can_manage_subject(db, user, body.subject_id)
        check_lesson_date(body.date)
        check_grade_type(subject, body.type)
        # details keys point to the index in the original records list
        students = {f"records.{i}.student_id": r.student_id for i, r in indexed}
        check_enrolment(db, body.subject_id, body.date, students, Scope.of(user))
        check_no_foreign_records(db, "grades", body.subject_id, body.date, students, body.type)
        db.executemany(f"""
            INSERT INTO grades (student_id, subject_id, value, type, date, teacher_id, group_id)
            VALUES (?, ?, ?, ?, ?, ?, {STUDENT_GROUP})
            ON CONFLICT (student_id, subject_id, date, type)
            DO UPDATE SET value = excluded.value, teacher_id = excluded.teacher_id""",
            [(r.student_id, body.subject_id, r.value, body.type, body.date, user["id"], r.student_id) for _, r in indexed])
    return {"saved": len(indexed)}


@router.patch("/{grade_id}", response_model=GradeDetail)
def update_grade(grade_id: PathId, body: GradeUpdate, user: CurrentUser, scope: UserScope, db: Db):
    """Partially update a grade; a date/type change is validated like a new grade.

    Value/comment edits are allowed on historical grades (transferred or expelled students). Group snapshot is kept.
    """
    data = body.model_dump(exclude_unset=True)
    with transaction(db):
        existing = get_grade(db, grade_id, scope)
        subject = assert_can_manage_subject(db, user, existing["subject_id"])
        m = {**existing, **data}
        if "date" in data or "type" in data:
            check_lesson_date(m["date"])
            check_grade_type(subject, m["type"])
            check_enrolment(db, existing["subject_id"], m["date"], {"student_id": existing["student_id"]}, Scope.of(user),
                            date_key="date")
        try:
            db.execute("UPDATE grades SET value = ?, type = ?, date = ?, comment = ? WHERE id = ?",
                       (m["value"], m["type"], m["date"], m["comment"], grade_id))
        except sqlite3.IntegrityError:
            raise conflict(DUPLICATE) from None
    return get_grade(db, grade_id)


@router.delete("/{grade_id}", status_code=204)
def delete_grade(grade_id: PathId, user: CurrentUser, scope: UserScope, db: Db):
    with transaction(db):
        existing = get_grade(db, grade_id, scope)
        assert_can_manage_subject(db, user, existing["subject_id"])
        db.execute("DELETE FROM grades WHERE id = ?", (grade_id,))
    return Response(status_code=204)
