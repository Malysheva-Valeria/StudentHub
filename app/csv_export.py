"""Excel-compatible CSV export (UTF-8 BOM, ";" delimiter)."""
from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

from fastapi.responses import Response

Column = tuple[str, str]  # (key, title)


# Phone numbers like +380 (67) 111-22-33 skip formula escaping, only in phone_columns
PHONE_LIKE = re.compile(r"^\+?[\d\s()\-]+$")


def _escape(value: Any, phone: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(value).replace(".", ",")  # decimal comma for Ukrainian-locale Excel
    if isinstance(value, int):
        return str(value)  # numbers (incl. negative) are not formulas
    s = str(value)
    # Prevent CSV formula injection
    if s and s[0] in "=+-@\t\r" and not (phone and PHONE_LIKE.match(s)):
        s = "'" + s
    if any(ch in s for ch in ';"\n\r'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def to_csv(rows: Iterable[Mapping[str, Any]], columns: Sequence[Column], phone_columns: Collection[str] = ()) -> str:
    head = ";".join(_escape(title) for _, title in columns)
    body = [";".join(_escape(r.get(key), key in phone_columns) for key, _ in columns) for r in rows]
    return "﻿" + "\r\n".join([head, *body])


def csv_response(filename: str, rows: Iterable[Mapping[str, Any]], columns: Sequence[Column],
                 phone_columns: Collection[str] = ()) -> Response:
    return Response(
        content=to_csv(rows, columns, phone_columns),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
    )
