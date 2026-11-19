from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Response

from ..constants import STATUS_UA
from ..csv_export import csv_response
from ..db import all_rows, one, scalar, transaction
from ..deps import AdminUser, Db, Limit, PageNo, PathId, QueryId, Search, UserScope
from ..errors import conflict, not_found
from ..rules import Scope, check_refs_exist, check_student_dates
from ..schemas import Gender, Page, StudentCreate, StudentOut, StudentStatus, StudentUpdate
from ..stats import student_card
from ..utils import like_pattern, pages_count, today

router = APIRouter(prefix="/api/students", tags=["students"])

BASE = """
    FROM students s
    LEFT JOIN groups g ON g.id = s.group_id
    LEFT JOIN (SELECT student_id, round1(AVG(value)) AS avg_grade FROM grades GROUP BY student_id) gr
           ON gr.student_id = s.id
    LEFT JOIN (SELECT student_id,
                      attendance_rate(SUM(status = 'present'), SUM(status = 'late'), COUNT(*)) AS attendance_rate
               FROM attendance GROUP BY student_id) at ON at.student_id = s.id"""
FIELDS = "s.*, g.name AS group_name, gr.avg_grade, at.attendance_rate"

# Sort whitelist: user input is never put into SQL directly
SORTS = {
    "name": "s.last_name COLLATE UK, s.first_name COLLATE UK",
    "group": "g.name COLLATE UK, s.last_name COLLATE UK, s.first_name COLLATE UK",
    "avg": "gr.avg_grade DESC NULLS LAST, s.last_name COLLATE UK",
    "attendance": "at.attendance_rate DESC NULLS LAST, s.last_name COLLATE UK",
    "created": "s.id DESC",
}
Sort = Literal["name", "group", "avg", "attendance", "created"]


def build_filter(scope: Scope, search: str | None, group_id: int | None, status: str | None,
                 gender: str | None) -> tuple[str, dict]:
    params: dict = {}
    where = [scope.sql("s.group_id", params)]
    if search and search.strip():
        where.append(
            "ulower(s.last_name || ' ' || s.first_name || ' ' || IFNULL(s.middle_name,'') || ' ' || s.record_book "
            "|| ' ' || IFNULL(s.email,'')) LIKE ulower(:search) ESCAPE '\\'"
        )
        params["search"] = like_pattern(search)
    if group_id:
        where.append("s.group_id = :group_id")
        params["group_id"] = group_id
    if status:
        where.append("s.status = :status")
        params["status"] = status
    if gender:
        where.append("s.gender = :gender")
        params["gender"] = gender
    return f"WHERE {' AND '.join(where)}", params


def get_student(db: sqlite3.Connection, student_id: int, scope: Scope = Scope()) -> dict:
    """Student with group, average and attendance; 404 if outside the teacher's scope."""
    p: dict = {"id": student_id}
    s = one(db, f"SELECT {FIELDS} {BASE} WHERE s.id = :id AND {scope.sql('s.group_id', p)}", p)
    if not s:
        raise not_found("Студента не знайдено")
    return scope.hide_private(s)


@router.get("", response_model=Page[StudentOut])
def list_students(
    scope: UserScope, db: Db,
    search: Search = None, group_id: QueryId = None, status: StudentStatus | None = None, gender: Gender | None = None,
    sort: Sort = "name", page: PageNo = 1, limit: Limit = 20,
):
    where, params = build_filter(scope, search, group_id, status, gender)
    # count query skips the aggregate subqueries
    total = scalar(db, f"SELECT COUNT(*) FROM students s {where}", params)
    items = all_rows(db, f"SELECT {FIELDS} {BASE} {where} ORDER BY {SORTS[sort]} LIMIT :limit OFFSET :offset",
                     {**params, "limit": limit, "offset": (page - 1) * limit})
    return {"items": [scope.hide_private(s) for s in items], "total": total, "page": page, "limit": limit,
            "pages": pages_count(total, limit)}


@router.get("/export")
def export_students(
    _: AdminUser, db: Db,
    search: Search = None, group_id: QueryId = None, status: StudentStatus | None = None, gender: Gender | None = None,
):
    """CSV export with personal data (admin only)."""
    where, params = build_filter(Scope(), search, group_id, status, gender)
    rows = all_rows(db, f"SELECT {FIELDS} {BASE} {where} ORDER BY {SORTS['group']}", params)
    for r in rows:
        r["full_name"] = " ".join(p for p in (r["last_name"], r["first_name"], r["middle_name"]) if p)
        r["gender"] = "Ч" if r["gender"] == "M" else "Ж"
        r["status"] = STATUS_UA[r["status"]]
    return csv_response("students.csv", rows, [
        ("record_book", "Залікова книжка"), ("full_name", "ПІБ"), ("group_name", "Група"), ("gender", "Стать"),
        ("birth_date", "Дата народження"), ("email", "Email"), ("phone", "Телефон"), ("status", "Статус"),
        ("avg_grade", "Середній бал"), ("attendance_rate", "Відвідуваність, %"),
    ], phone_columns={"phone"})


@router.get("/{student_id}")
def read_student_card(student_id: PathId, scope: UserScope, db: Db):
    """Student card: per-subject results, attendance, recent grades."""
    return student_card(db, get_student(db, student_id, scope))


def _check_unique_and_refs(db: sqlite3.Connection, data: dict, student_id: int = 0) -> None:
    """Pre-write checks (inside a transaction): unique record book, existing group."""
    if one(db, "SELECT 1 AS ok FROM students WHERE record_book = ? AND id != ?", (data["record_book"], student_id)):
        raise conflict("Студент з таким номером залікової книжки вже існує",
                       {"record_book": "Такий номер залікової книжки вже існує"})
    check_refs_exist(db, {"group_id": data["group_id"]})


@router.post("", status_code=201, response_model=StudentOut)
def create_student(body: StudentCreate, _: AdminUser, db: Db):
    data = body.model_dump()
    data["enrolled_at"] = data["enrolled_at"] or today()
    check_student_dates(data["birth_date"], data["enrolled_at"])
    with transaction(db):
        _check_unique_and_refs(db, data)
        cur = db.execute("""
            INSERT INTO students (last_name, first_name, middle_name, gender, birth_date, email, phone,
                                  record_book, group_id, status, enrolled_at)
            VALUES (:last_name, :first_name, :middle_name, :gender, :birth_date, :email, :phone,
                    :record_book, :group_id, :status, :enrolled_at)""", data)
    return get_student(db, cur.lastrowid)


@router.patch("/{student_id}", response_model=StudentOut)
def update_student(student_id: PathId, body: StudentUpdate, _: AdminUser, db: Db):
    """Partial update. On transfer, existing grades stay with the previous group."""
    data = body.model_dump(exclude_unset=True)
    with transaction(db):
        existing = get_student(db, student_id)
        m = {**existing, **data}
        if {"birth_date", "enrolled_at"} & data.keys():
            check_student_dates(m["birth_date"], m["enrolled_at"])
        _check_unique_and_refs(db, m, student_id)
        db.execute("""
            UPDATE students SET last_name=:last_name, first_name=:first_name, middle_name=:middle_name,
                   gender=:gender, birth_date=:birth_date, email=:email, phone=:phone, record_book=:record_book,
                   group_id=:group_id, status=:status, enrolled_at=:enrolled_at
            WHERE id=:id""", {**m, "id": student_id})
    return get_student(db, student_id)


@router.delete("/{student_id}", status_code=204)
def delete_student(student_id: PathId, _: AdminUser, db: Db):
    with transaction(db):
        if not one(db, "SELECT 1 AS ok FROM students WHERE id = ?", (student_id,)):
            raise not_found("Студента не знайдено")
        if one(db, """SELECT EXISTS(SELECT 1 FROM grades WHERE student_id = :id)
                             OR EXISTS(SELECT 1 FROM attendance WHERE student_id = :id) AS used""", {"id": student_id})["used"]:
            raise conflict("Студент має оцінки або відвідуваність — змініть його статус (наприклад, «Відрахований») "
                           "замість видалення")
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    return Response(status_code=204)
