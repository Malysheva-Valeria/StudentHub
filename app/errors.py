"""API error format: {"error": "...", "details": {...}}."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

HTTP_MESSAGES = {404: "Маршрут не знайдено", 405: "Метод не дозволено", 413: "Запит завеликий (максимум 1 МБ)"}


class ApiError(Exception):
    def __init__(self, status: int, message: str, details: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def bad_request(msg: str, details: dict[str, str] | None = None) -> ApiError:
    return ApiError(400, msg, details)


def not_found(msg: str = "Запис не знайдено") -> ApiError:
    return ApiError(404, msg)


def forbidden(msg: str = "Недостатньо прав") -> ApiError:
    return ApiError(403, msg)


def conflict(msg: str, details: dict[str, str] | None = None) -> ApiError:
    return ApiError(409, msg, details)


def _translate(err: dict[str, Any]) -> str:
    """Translate a Pydantic error to a Ukrainian message."""
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    if t == "missing":
        return "Обовʼязкове поле"
    if t == "string_too_short":
        return "Обовʼязкове поле" if ctx.get("min_length") == 1 else f"Мінімум {ctx.get('min_length')} символів"
    if t == "string_too_long":
        return f"Максимум {ctx.get('max_length')} символів"
    if t in ("int_parsing", "int_from_float", "int_type"):
        return "Має бути цілим числом"
    if t in ("float_parsing", "float_type"):
        return "Має бути числом"
    if t in ("greater_than_equal", "greater_than"):
        return f"Мінімум {ctx.get('ge', ctx.get('gt'))}"
    if t in ("less_than_equal", "less_than"):
        return f"Максимум {ctx.get('le', ctx.get('lt'))}"
    if t in ("literal_error", "enum"):
        return f"Допустимі значення: {ctx.get('expected', '')}".replace("'", "")
    if t in ("string_type",):
        return "Має бути рядком"
    if t in ("list_type",):
        return "Має бути списком"
    if t in ("bool_parsing", "bool_type"):
        return "Має бути так/ні"
    if t == "value_error":
        return str(ctx.get("error") or err.get("msg", "Некоректне значення"))
    if t == "extra_forbidden":
        return "Невідоме поле"
    if t == "string_pattern_mismatch":
        return "Некоректний формат"
    if t == "too_long":
        return f"Максимум {ctx.get('max_length')} елементів"
    if t == "too_short":
        return f"Мінімум {ctx.get('min_length')} елементів"
    return err.get("msg", "Некоректне значення")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        body: dict[str, Any] = {"error": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details: dict[str, str] = {}
        for err in exc.errors():
            if err.get("type") == "json_invalid":
                return JSONResponse({"error": "Некоректний JSON"}, status_code=400)
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            key = ".".join(loc) or "body"
            details.setdefault(key, _translate(err))
        return JSONResponse({"error": "Помилка валідації", "details": details}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def _integrity(_: Request, exc: sqlite3.IntegrityError):
        msg = str(exc)
        if "UNIQUE" in msg or "PRIMARY KEY" in msg:
            return JSONResponse({"error": "Такий запис уже існує"}, status_code=409)
        if "FOREIGN KEY" in msg:
            return JSONResponse({"error": "Посилання на неіснуючий запис"}, status_code=400)
        return JSONResponse({"error": "Порушено обмеження даних"}, status_code=400)

    @app.exception_handler(OverflowError)
    async def _overflow(_: Request, exc: OverflowError):
        # Integer too large for SQLite; fallback if validation missed it
        return JSONResponse({"error": "Занадто велике число"}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": HTTP_MESSAGES.get(exc.status_code, str(exc.detail))}, status_code=exc.status_code)

    # Unhandled exceptions (500) are handled in SecurityHeadersMiddleware so they get security headers.
