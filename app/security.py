"""Passwords, server-side sessions and rate limiting (FastAPI-independent)."""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time

import bcrypt

from .constants import MAX_PASSWORD_BYTES
from .db import Row, one

BCRYPT_ROUNDS = 10
DEMO_PASSWORDS = ("admin123", "teacher123")

# Checked against for unknown users so response time doesn't reveal whether a login exists
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


# ---------- Passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, (password_hash or _DUMMY_HASH).encode()) and password_hash is not None
    except ValueError:
        return False


def normalize_username(username: str) -> str:
    # COLLATE NOCASE is ASCII-only, so normalize here
    return username.strip().lower()


def users_with_demo_passwords(db: sqlite3.Connection) -> list[str]:
    """Usernames of active users still using a demo password."""
    rows = db.execute("SELECT username, password_hash FROM users WHERE is_active = 1").fetchall()
    return [r["username"] for r in rows if any(verify_password(p, r["password_hash"]) for p in DEMO_PASSWORDS)]


# ---------- Server-side sessions ----------
# The signed cookie holds only a session id; deleting the row revokes the session immediately.
TOUCH_INTERVAL = 60  # min seconds between last_seen_at updates


def now() -> int:
    """Current Unix time; patchable in tests."""
    return int(time.time())


def create_session(db: sqlite3.Connection, user_id: int, lifetime: int) -> str:
    sid = secrets.token_urlsafe(32)
    t = now()
    db.execute("INSERT INTO sessions (id, user_id, created_at, last_seen_at, expires_at) VALUES (?, ?, ?, ?, ?)",
               (sid, user_id, t, t, t + lifetime))
    return sid


def session_user(db: sqlite3.Connection, sid: str, idle: int) -> Row | None:
    """Return the session's user, or None if missing, expired or the user is inactive."""
    t = now()
    row = one(db, """
        SELECT u.*, s.last_seen_at AS session_last_seen, s.expires_at AS session_expires
        FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?""", (sid,))
    if not row:
        return None
    if row["session_expires"] <= t or row["session_last_seen"] + idle <= t or not row["is_active"]:
        delete_session(db, sid)
        return None
    if t - row["session_last_seen"] >= TOUCH_INTERVAL:  # sliding idle timeout
        db.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (t, sid))
    return row


def delete_session(db: sqlite3.Connection, sid: str) -> None:
    db.execute("DELETE FROM sessions WHERE id = ?", (sid,))


def delete_user_sessions(db: sqlite3.Connection, user_id: int, except_sid: str | None = None) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = ? AND id IS NOT ?", (user_id, except_sid))


def purge_expired_sessions(db: sqlite3.Connection, idle: int) -> None:
    t = now()
    db.execute("DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at + ? <= ?", (t, idle, t))


# ---------- Rate limiting ----------
class RateLimiter:
    """Per-key-kind attempt limits within a time window.

    Example: RateLimiter({"user_ip": 10, "user": 100, "ip": 50}).hit(user_ip="admin|1.2.3.4", user="admin", ip="1.2.3.4")
    """

    def __init__(self, limits: dict[str, int], window_seconds: int = 15 * 60):
        self.limits = limits
        self.window = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, tuple[int, float]] = {}

    def _count(self, key: str, t: float) -> int:
        entry = self._attempts.get(key)
        if entry is None or t - entry[1] > self.window:
            self._attempts.pop(key, None)
            return 0
        return entry[0]

    def hit(self, **keys: str) -> bool:
        """Atomically check all limits and count the attempt; False if any key is over its limit."""
        with self._lock:
            t = time.monotonic()
            if any(self._count(f"{kind}:{value}", t) >= self.limits[kind] for kind, value in keys.items()):
                return False
            for kind, value in keys.items():
                key = f"{kind}:{value}"
                count, first = self._attempts.get(key, (0, t))
                self._attempts[key] = (count + 1, first)
            if len(self._attempts) > 10_000:  # bound memory: drop expired entries
                for k in [k for k, (_, first) in self._attempts.items() if t - first > self.window]:
                    del self._attempts[k]
            return True

    def refund(self, **keys: str) -> None:
        """Undo one counted attempt (e.g. after a successful login)."""
        with self._lock:
            for kind, value in keys.items():
                key = f"{kind}:{value}"
                if key in self._attempts:
                    count, first = self._attempts[key]
                    self._attempts[key] = (max(count - 1, 0), first)

    def reset(self, **keys: str) -> None:
        with self._lock:
            for kind, value in keys.items():
                self._attempts.pop(f"{kind}:{value}", None)


# ---------- Known device cookie (OWASP) ----------
# Signed cookie listing usernames that logged in from this browser; lets them bypass the shared
# "user" and "ip" limits to prevent lockout attacks. The "user_ip" limit always applies.
DEVICE_COOKIE = "sh_device"
DEVICE_MAX_AGE = 90 * 24 * 60 * 60
_DEVICE_MAX_USERS = 5


def _device_serializer(secret: str):
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(secret, salt="studenthub-known-device")


def read_known_users(secret: str, cookie: str | None) -> list[str]:
    if not cookie:
        return []
    from itsdangerous import BadSignature
    try:
        data = _device_serializer(secret).loads(cookie, max_age=DEVICE_MAX_AGE)
    except (BadSignature, ValueError):
        return []
    return [u for u in data if isinstance(u, str)][: _DEVICE_MAX_USERS] if isinstance(data, list) else []


def make_device_cookie(secret: str, known: list[str], username: str) -> str:
    users = [username] + [u for u in known if u != username]
    return _device_serializer(secret).dumps(users[:_DEVICE_MAX_USERS])
