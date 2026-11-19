"""Small helpers."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def app_timezone() -> str:
    """App time zone name from APP_TIMEZONE (default Europe/Kyiv)."""
    return os.getenv("APP_TIMEZONE", "Europe/Kyiv")


def local_today() -> date:
    """Today's date in the app time zone."""
    return datetime.now(ZoneInfo(app_timezone())).date()


def today() -> str:
    """Today's date as YYYY-MM-DD."""
    return local_today().isoformat()


def pages_count(total: int, limit: int) -> int:
    return max((total + limit - 1) // limit, 1)


def like_pattern(text: str) -> str:
    """Substring LIKE pattern with % and _ escaped; use with ESCAPE '\\'."""
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
