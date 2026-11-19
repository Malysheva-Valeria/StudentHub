from __future__ import annotations

from fastapi import APIRouter, Response

from ..db import all_rows, one, scalar, transaction
from ..deps import AdminUser, CurrentUser, Db, PathId
from ..errors import bad_request, conflict, not_found
from ..schemas import UserBrief, UserCreate, UserOut, UserUpdate
from ..security import delete_user_sessions, hash_password, normalize_username

router = APIRouter(prefix="/api/users", tags=["users"])

COLUMNS = "id, username, full_name, role, is_active, created_at"


def get_user(db, user_id: int) -> dict:
    user = one(db, f"SELECT {COLUMNS} FROM users WHERE id = ?", (user_id,))
    if not user:
        raise not_found("Користувача не знайдено")
    return user


@router.get("/teachers", response_model=list[UserBrief], response_model_exclude_none=True)
def teachers(user: CurrentUser, db: Db):
    """Users for teacher/curator dropdowns: all users for admin, id and name of active users for teachers."""
    if user["role"] == "admin":
        return all_rows(db, "SELECT id, full_name, is_active FROM users ORDER BY full_name COLLATE UK")
    return all_rows(db, "SELECT id, full_name FROM users WHERE is_active = 1 ORDER BY full_name COLLATE UK")


@router.get("", response_model=list[UserOut])
def list_users(_: AdminUser, db: Db):
    return all_rows(db, f"SELECT {COLUMNS} FROM users ORDER BY role, full_name COLLATE UK")


@router.post("", status_code=201, response_model=UserOut)
def create_user(body: UserCreate, _: AdminUser, db: Db):
    username = normalize_username(body.username)
    password_hash = hash_password(body.password)  # bcrypt outside the transaction
    with transaction(db):
        if one(db, "SELECT 1 AS ok FROM users WHERE username = ?", (username,)):
            raise conflict("Користувач з таким логіном уже існує", {"username": "Такий логін уже зайнятий"})
        cur = db.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, body.full_name, body.role),
        )
    return get_user(db, cur.lastrowid)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: PathId, body: UserUpdate, admin: AdminUser, db: Db):
    """Partial update. Blocking or a password change ends all the user's sessions."""
    data = body.model_dump(exclude_unset=True)
    password_hash = hash_password(data["password"]) if data.get("password") else None  # bcrypt outside the transaction
    with transaction(db):
        existing = get_user(db, user_id)
        merged = {**existing, **{k: v for k, v in data.items() if k != "password"}}
        is_active = int(bool(merged["is_active"]))
        loses_admin = existing["role"] == "admin" and existing["is_active"] and (merged["role"] != "admin" or not is_active)
        if loses_admin:
            if user_id == admin["id"]:
                raise bad_request("Не можна понизити роль або заблокувати власний обліковий запис")
            others = scalar(db, "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?", (user_id,))
            if others == 0:
                raise conflict("Це останній активний адміністратор — його не можна заблокувати чи понизити")
        db.execute("""
            UPDATE users SET full_name = ?, role = ?, is_active = ?, password_hash = COALESCE(?, password_hash)
            WHERE id = ?""", (merged["full_name"], merged["role"], is_active, password_hash, user_id))
        if password_hash or (existing["is_active"] and not is_active):
            delete_user_sessions(db, user_id)
    return get_user(db, user_id)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: PathId, admin: AdminUser, db: Db):
    """Delete a user with no history; otherwise 409 suggesting to block."""
    if user_id == admin["id"]:
        raise bad_request("Не можна видалити власний обліковий запис")
    with transaction(db):
        get_user(db, user_id)
        usage = one(db, """
            SELECT EXISTS(SELECT 1 FROM grades WHERE teacher_id = :id) OR EXISTS(SELECT 1 FROM attendance WHERE teacher_id = :id)
                       AS has_history,
                   EXISTS(SELECT 1 FROM subjects WHERE teacher_id = :id) OR EXISTS(SELECT 1 FROM groups WHERE curator_id = :id)
                       AS has_assignments""", {"id": user_id})
        if usage["has_history"]:
            raise conflict("Користувач виставляв оцінки або відмічав відвідуваність — заблокуйте його замість видалення")
        if usage["has_assignments"]:
            raise conflict("Користувач веде дисципліни або кураторує групи — переназначте їх або заблокуйте користувача")
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))  # sessions are deleted by cascade
    return Response(status_code=204)
