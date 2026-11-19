"""App settings from environment variables.

APP_ENV=development (default): HTTP, demo data enabled.
APP_ENV=production: HTTPS only, no Swagger or demo data; requires SESSION_SECRET (>= 32 chars).
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .utils import app_timezone

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DATABASE_DIR = ROOT / "database"


MIN_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    """Invalid configuration; the app cannot start safely."""


def _local_secret() -> str:
    """Dev session secret, generated once and stored in an owner-only file."""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    path = DATABASE_DIR / ".session_secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    # Create with 0o600 atomically so the file is never world-readable
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    return value


@dataclass(frozen=True)
class Settings:
    db_path: str
    session_secret: str
    production: bool
    host: str
    port: int
    seed_demo: bool = True
    session_lifetime: int = 8 * 60 * 60   # absolute session lifetime, seconds
    session_idle: int = 2 * 60 * 60       # idle timeout, seconds
    forwarded_allow_ips: str | None = None  # trusted proxies for X-Forwarded-For

    @property
    def demo(self) -> bool:
        """Whether to show demo accounts on the login page."""
        return self.seed_demo and not self.production


def _check_timezone() -> None:
    """Ensure APP_TIMEZONE is a known time zone."""
    name = app_timezone()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"невідомий часовий пояс APP_TIMEZONE={name!r}. Вкажіть назву на кшталт Europe/Kyiv; "
                          "якщо база часових поясів відсутня (зокрема на Windows) — виконайте pip install tzdata") from None


def load_settings() -> Settings:
    production = os.getenv("APP_ENV", "development") == "production"
    _check_timezone()
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        if production:
            raise ConfigError("APP_ENV=production: задайте змінну середовища SESSION_SECRET (довгий випадковий рядок)")
        secret = _local_secret()
    if production and len(secret) < MIN_SECRET_LENGTH:
        raise ConfigError(f"APP_ENV=production: SESSION_SECRET має містити щонайменше {MIN_SECRET_LENGTH} символи")
    if production and os.getenv("SEED_DEMO", "0") != "0":
        raise ConfigError("APP_ENV=production: демо-дані зі стандартними паролями заборонені (приберіть SEED_DEMO). "
                          "Адміністратора створіть командою python -m app.create_admin")
    return Settings(
        db_path=os.getenv("DB_PATH", str(DATABASE_DIR / "studenthub.db")),
        session_secret=secret,
        production=production,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        seed_demo=not production and os.getenv("SEED_DEMO", "1") != "0",
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS") or None,
    )
