"""FastAPI dependencies: DB connection, current user, permissions, scope, typed params."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Path, Query, Request
from pydantic import AfterValidator

from .constants import INT_MAX
from .db import Row, connect, one
from .errors import ApiError, forbidden, not_found
from .rules import Scope
from .schemas import check_date
from .security import session_user


# ---------- Database ----------
def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


# ---------- Auth and permissions ----------
def public_user(user: Row) -> dict[str, Any]:
    return {"id": user["id"], "username": user["username"], "full_name": user["full_name"], "role": user["role"]}


def get_current_user(request: Request, db: Db) -> Row:
    sid = request.session.get("sid")
    if not isinstance(sid, str):
        raise ApiError(401, "Потрібна авторизація")
    user = session_user(db, sid, request.app.state.settings.session_idle)
    if user is None:
        request.session.clear()
        raise ApiError(401, "Сесія завершилась. Увійдіть знову")
    return user


CurrentUser = Annotated[Row, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> Row:
    if user["role"] != "admin":
        raise forbidden()
    return user


AdminUser = Annotated[Row, Depends(require_admin)]


def get_scope(user: CurrentUser) -> Scope:
    return Scope.of(user)


UserScope = Annotated[Scope, Depends(get_scope)]


def assert_can_manage_subject(db: sqlite3.Connection, user: Row, subject_id: int) -> Row:
    """Return the subject if the user may manage it (admin, or its teacher)."""
    subject = one(db, "SELECT id, teacher_id, control FROM subjects WHERE id = ?", (subject_id,))
    if not subject:
        raise not_found("Дисципліну не знайдено")
    if user["role"] != "admin" and subject["teacher_id"] != user["id"]:
        raise forbidden("Ви можете працювати лише зі своїми дисциплінами")
    return subject


def assert_group_in_scope(db: sqlite3.Connection, scope: Scope, group_id: int) -> None:
    """Raise 404 if the group doesn't exist or is outside the user's scope."""
    allowed = scope.group_ids(db)
    exists = one(db, "SELECT 1 AS ok FROM groups WHERE id = ?", (group_id,))
    if not exists or (allowed is not None and group_id not in allowed):
        raise not_found("Групу не знайдено")


# ---------- Typed path/query params (invalid values -> 400) ----------
PathId = Annotated[int, Path(ge=1, le=INT_MAX)]
QueryId = Annotated[int | None, Query(ge=1, le=INT_MAX)]
QueryDate = Annotated[str | None, AfterValidator(lambda v: v if v is None else check_date(v))]
PageNo = Annotated[int, Query(ge=1, le=1_000_000)]
Limit = Annotated[int, Query(ge=1, le=500)]
Search = Annotated[str | None, Query(max_length=100)]
