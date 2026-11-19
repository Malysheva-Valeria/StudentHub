from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Response

from ..constants import CONTROL_UA
from ..db import all_rows, one, transaction
from ..deps import AdminUser, Db, PathId, UserScope
from ..errors import conflict, not_found
from ..queries import SUBJECT_SELECT, links_of, save_links
from ..rules import Scope, check_links_removable, check_refs_exist
from ..schemas import SubjectDetail, SubjectIn, SubjectOut
from ..stats import with_subject_averages

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def get_subject(db: sqlite3.Connection, subject_id: int, scope: Scope = Scope()) -> dict:
    """Subject with its groups; 404 if out of scope. For teachers, groups and average are scope-limited."""
    p: dict = {"id": subject_id}
    s = one(db, f"{SUBJECT_SELECT} WHERE sb.id = :id AND {scope.subject_sql('sb.id', p)}", p)
    if not s:
        raise not_found("Дисципліну не знайдено")
    group_ids = [r["group_id"] for r in all_rows(db, "SELECT group_id FROM group_subjects WHERE subject_id = ?", (subject_id,))]
    visible = scope.group_ids(db)
    s["group_ids"] = group_ids if visible is None else [g for g in group_ids if g in visible]
    return with_subject_averages(db, [s], scope)[0]


def _check_body(db: sqlite3.Connection, body: SubjectIn, subject_id: int = 0) -> None:
    """Pre-write checks (inside a transaction): name unique ignoring case/apostrophes, existing teacher and groups."""
    if one(db, "SELECT 1 AS ok FROM subjects WHERE ulower(name) = ulower(?) AND id != ?", (body.name, subject_id)):
        raise conflict("Дисципліна з такою назвою вже існує", {"name": "Дисципліна з такою назвою вже існує"})
    check_refs_exist(db, {"teacher_id": body.teacher_id, "group_ids": body.group_ids})


def _check_control_change(db: sqlite3.Connection, subject_id: int, control: str) -> None:
    """Forbid changing the control form once final grades exist."""
    current = one(db, "SELECT control FROM subjects WHERE id = ?", (subject_id,))["control"]
    if current != control and one(db, "SELECT 1 AS ok FROM grades WHERE subject_id = ? AND type IN ('exam', 'credit') LIMIT 1",
                                  (subject_id,)):
        msg = f"Неможливо змінити форму контролю: з дисципліни вже є підсумкові оцінки ({CONTROL_UA[current]})"
        raise conflict(msg, {"control": msg})


@router.get("", response_model=list[SubjectOut])
def list_subjects(scope: UserScope, db: Db, mine: bool = False):
    """List subjects in scope; ?mine=1 returns only those the user teaches."""
    if mine and scope.is_limited:
        rows = all_rows(db, f"{SUBJECT_SELECT} WHERE sb.teacher_id = ? ORDER BY sb.name COLLATE UK", (scope.user_id,))
    else:
        p: dict = {}
        rows = all_rows(db, f"{SUBJECT_SELECT} WHERE {scope.subject_sql('sb.id', p)} ORDER BY sb.semester, sb.name COLLATE UK", p)
    return with_subject_averages(db, rows, scope)


@router.get("/{subject_id}", response_model=SubjectDetail)
def read_subject(subject_id: PathId, scope: UserScope, db: Db):
    return get_subject(db, subject_id, scope)


def _values(b: SubjectIn) -> tuple:
    return (b.name, b.code, b.credits, b.hours, b.semester, b.control, b.teacher_id)


@router.post("", status_code=201, response_model=SubjectDetail)
def create_subject(body: SubjectIn, _: AdminUser, db: Db):
    with transaction(db):
        _check_body(db, body)
        cur = db.execute(
            "INSERT INTO subjects (name, code, credits, hours, semester, control, teacher_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            _values(body),
        )
        if body.group_ids is not None:
            save_links(db, set(), {(gid, cur.lastrowid) for gid in body.group_ids})
    return get_subject(db, cur.lastrowid)


@router.put("/{subject_id}", response_model=SubjectDetail)
def update_subject(subject_id: PathId, body: SubjectIn, _: AdminUser, db: Db):
    """Full update. 409 on control-form change with finals, or unlinking a group with grades/attendance."""
    with transaction(db):
        if not one(db, "SELECT 1 AS ok FROM subjects WHERE id = ?", (subject_id,)):
            raise not_found("Дисципліну не знайдено")
        _check_body(db, body, subject_id)
        _check_control_change(db, subject_id, body.control)
        db.execute(
            "UPDATE subjects SET name=?, code=?, credits=?, hours=?, semester=?, control=?, teacher_id=? WHERE id=?",
            (*_values(body), subject_id),
        )
        if body.group_ids is not None:
            old, new = links_of(db, subject_id=subject_id), {(gid, subject_id) for gid in body.group_ids}
            check_links_removable(db, old - new, "group_ids")
            save_links(db, old, new)
    return get_subject(db, subject_id)


@router.delete("/{subject_id}", status_code=204)
def delete_subject(subject_id: PathId, _: AdminUser, db: Db):
    with transaction(db):
        if not one(db, "SELECT 1 AS ok FROM subjects WHERE id = ?", (subject_id,)):
            raise not_found("Дисципліну не знайдено")
        if one(db, """SELECT EXISTS(SELECT 1 FROM grades WHERE subject_id = :id)
                             OR EXISTS(SELECT 1 FROM attendance WHERE subject_id = :id) AS used""", {"id": subject_id})["used"]:
            raise conflict("З дисципліни вже є оцінки або відвідуваність — її не можна видалити, щоб не втратити історію")
        db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
    return Response(status_code=204)
