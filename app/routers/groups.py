from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Response

from ..db import all_rows, one, transaction
from ..deps import AdminUser, Db, PathId, UserScope, assert_group_in_scope
from ..errors import conflict, not_found
from ..queries import SUBJECT_SELECT, links_of, save_links
from ..rules import Scope, check_links_removable, check_refs_exist
from ..schemas import GroupDetail, GroupIn, GroupOut, SubjectOut
from ..stats import NO_FILTERS, Filters, group_averages, student_averages, with_subject_averages

router = APIRouter(prefix="/api/groups", tags=["groups"])

SELECT = """
    SELECT g.*, u.full_name AS curator_name,
           (SELECT COUNT(*) FROM students s WHERE s.group_id = g.id AND s.status = 'active') AS students_count
    FROM groups g LEFT JOIN users u ON u.id = g.curator_id"""


def _with_avg(db: sqlite3.Connection, groups: list[dict], f: Filters = NO_FILTERS) -> list[dict]:
    averages = group_averages(student_averages(db, Scope(), f))
    for g in groups:
        g["avg_grade"] = averages.get(g["id"])
    return groups


def get_group(db: sqlite3.Connection, group_id: int, scope: Scope = Scope()) -> dict:
    """Group with its subjects; 404 if outside the teacher's scope."""
    p: dict = {"id": group_id}
    group = one(db, f"{SELECT} WHERE g.id = :id AND {scope.sql('g.id', p)}", p)
    if not group:
        raise not_found("Групу не знайдено")
    group["subject_ids"] = [r["subject_id"] for r in all_rows(db, "SELECT subject_id FROM group_subjects WHERE group_id = ?", (group_id,))]
    return _with_avg(db, [group], Filters(group_id=group_id))[0]


def _name(body: GroupIn) -> str:
    # Uppercase names also give case-insensitive uniqueness for Cyrillic
    return body.name.upper()


def _check_body(db: sqlite3.Connection, body: GroupIn, group_id: int = 0) -> None:
    """Pre-write checks (inside a transaction): unique name, existing curator and subjects."""
    if one(db, "SELECT 1 AS ok FROM groups WHERE uupper(name) = ? AND id != ?", (_name(body), group_id)):
        raise conflict("Група з такою назвою вже існує", {"name": "Група з такою назвою вже існує"})
    check_refs_exist(db, {"curator_id": body.curator_id, "subject_ids": body.subject_ids})


@router.get("", response_model=list[GroupOut])
def list_groups(scope: UserScope, db: Db):
    """List groups visible to the user."""
    p: dict = {}
    return _with_avg(db, all_rows(db, f"{SELECT} WHERE {scope.sql('g.id', p)} ORDER BY g.course, g.name COLLATE UK", p))


@router.get("/{group_id}", response_model=GroupDetail)
def read_group(group_id: PathId, scope: UserScope, db: Db):
    return get_group(db, group_id, scope)


@router.get("/{group_id}/subjects", response_model=list[SubjectOut])
def group_subjects(group_id: PathId, scope: UserScope, db: Db):
    assert_group_in_scope(db, scope, group_id)
    return with_subject_averages(db, all_rows(db, f"""
        {SUBJECT_SELECT} JOIN group_subjects gs ON gs.subject_id = sb.id
        WHERE gs.group_id = ? ORDER BY sb.name COLLATE UK""", (group_id,)), scope)


@router.post("", status_code=201, response_model=GroupDetail)
def create_group(body: GroupIn, _: AdminUser, db: Db):
    with transaction(db):
        _check_body(db, body)
        cur = db.execute(
            "INSERT INTO groups (name, course, specialty, curator_id) VALUES (?, ?, ?, ?)",
            (_name(body), body.course, body.specialty, body.curator_id),
        )
        if body.subject_ids is not None:
            save_links(db, set(), {(cur.lastrowid, sid) for sid in body.subject_ids})
    return get_group(db, cur.lastrowid)


@router.put("/{group_id}", response_model=GroupDetail)
def update_group(group_id: PathId, body: GroupIn, _: AdminUser, db: Db):
    """Full update. Unlinking a subject with grades/attendance in this group -> 409."""
    with transaction(db):
        assert_group_in_scope(db, Scope(), group_id)
        _check_body(db, body, group_id)
        db.execute(
            "UPDATE groups SET name = ?, course = ?, specialty = ?, curator_id = ? WHERE id = ?",
            (_name(body), body.course, body.specialty, body.curator_id, group_id),
        )
        if body.subject_ids is not None:
            old, new = links_of(db, group_id=group_id), {(group_id, sid) for sid in body.subject_ids}
            check_links_removable(db, old - new, "subject_ids")
            save_links(db, old, new)
    return get_group(db, group_id)


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: PathId, _: AdminUser, db: Db):
    with transaction(db):
        assert_group_in_scope(db, Scope(), group_id)
        if one(db, "SELECT 1 AS ok FROM students WHERE group_id = ? LIMIT 1", (group_id,)):
            raise conflict("У групі є студенти — спершу переведіть їх до іншої групи")
        if one(db, """SELECT EXISTS(SELECT 1 FROM grades WHERE group_id = :id)
                             OR EXISTS(SELECT 1 FROM attendance WHERE group_id = :id) AS used""", {"id": group_id})["used"]:
            raise conflict("У групі вже виставлялися оцінки або відмічалася відвідуваність — її не можна видалити, "
                           "щоб не втратити історію журналу")
        db.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    return Response(status_code=204)
