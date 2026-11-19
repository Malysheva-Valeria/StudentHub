from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..db import one, transaction
from ..deps import CurrentUser, Db, public_user
from ..errors import ApiError, bad_request
from ..schemas import ChangePasswordIn, LoginIn
from ..grading import ECTS
from ..security import (DEVICE_COOKIE, DEVICE_MAX_AGE, create_session, delete_session, delete_user_sessions,
                        hash_password, make_device_cookie, normalize_username, purge_expired_sessions,
                        read_known_users, verify_password)
from ..utils import today

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOO_MANY_LOGINS = "Забагато спроб входу. Спробуйте за 15 хвилин"


@router.get("/config")
def config(request: Request):
    """Public login-page settings (whether to show demo accounts)."""
    return {"demo": request.app.state.settings.demo}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Db):
    """Log in, rate-limited per LOGIN_LIMITS; attempts are counted before the password check.

    Per-user and per-IP limits are skipped for a browser known to this user (DEVICE_COOKIE),
    so they can't be used to lock someone else out.
    """
    limiter = request.app.state.login_limiter
    settings = request.app.state.settings
    username = normalize_username(body.username)
    ip = request.client.host if request.client else "unknown"
    known = read_known_users(settings.session_secret, request.cookies.get(DEVICE_COOKIE))
    shared = {} if username in known else {"user": username, "ip": ip}
    if not limiter.hit(user_ip=f"{username}|{ip}") or (shared and not limiter.hit(**shared)):
        raise ApiError(429, TOO_MANY_LOGINS)

    user = one(db, "SELECT * FROM users WHERE username = ?", (username,))
    ok = verify_password(body.password, user["password_hash"] if user else None)
    if not user or not ok or not user["is_active"]:
        raise ApiError(401, "Невірний логін або пароль")

    # Reset only the login+IP counter; shared counters just get this attempt back.
    limiter.reset(user_ip=f"{username}|{ip}")
    if shared:
        limiter.refund(**shared)
    with transaction(db):
        purge_expired_sessions(db, settings.session_idle)
        if isinstance(old := request.session.get("sid"), str):
            delete_session(db, old)
        sid = create_session(db, user["id"], settings.session_lifetime)
    request.session.clear()
    request.session["sid"] = sid
    response.set_cookie(DEVICE_COOKIE, make_device_cookie(settings.session_secret, known, username),
                        max_age=DEVICE_MAX_AGE, httponly=True, samesite="lax", secure=settings.production)
    return {"user": public_user(user)}


@router.post("/logout")
def logout(request: Request, db: Db):
    if isinstance(sid := request.session.get("sid"), str):
        delete_session(db, sid)
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser):
    """Current user, plus server-timezone "today" and the ECTS scale for the frontend."""
    return {"user": public_user(user), "today": today(), "ects": ECTS}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: CurrentUser, db: Db):
    """Change own password. Too many failures -> 429 and all sessions ended."""
    if not request.app.state.password_limiter.hit(user=str(user["id"])):
        delete_user_sessions(db, user["id"])
        request.session.clear()
        raise ApiError(429, "Забагато невдалих спроб. Увійдіть знову через 15 хвилин")
    if not verify_password(body.current_password, user["password_hash"]):
        raise bad_request("Поточний пароль невірний", {"current_password": "Поточний пароль невірний"})
    request.app.state.password_limiter.reset(user=str(user["id"]))
    with transaction(db):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), user["id"]))
        # End all other sessions, keep the current one
        delete_user_sessions(db, user["id"], except_sid=request.session["sid"])
    return {"ok": True}
