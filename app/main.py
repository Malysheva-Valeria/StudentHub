"""StudentHub FastAPI app factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import ConfigError, STATIC_DIR, Settings, load_settings
from .constants import LOGIN_LIMITS, PASSWORD_CHANGE_LIMITS
from .db import connect, init_db
from .errors import install_error_handlers
from .middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from .routers import attendance, auth, dashboard, grades, groups, reports, students, subjects, users
from .security import RateLimiter, users_with_demo_passwords
from .seed import seed_if_empty

log = logging.getLogger("studenthub")

# Pages served without extension: /students -> static/students.html
PAGES = ["login", "students", "student", "groups", "subjects", "grades", "attendance", "reports", "users"]


def _warn_demo_passwords(settings: Settings) -> None:
    conn = connect(settings.db_path)
    try:
        if names := users_with_demo_passwords(conn):
            log.warning("УВАГА: користувачі зі стандартними демо-паролями: %s — змініть паролі!", ", ".join(names))
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    if settings.production and settings.seed_demo:
        raise ConfigError("Демо-дані заборонені в production (SEED_DEMO). Створіть адміністратора: python -m app.create_admin")
    init_db(settings.db_path)
    if settings.seed_demo and seed_if_empty(settings.db_path):
        log.warning("Базу наповнено демо-даними (admin / admin123, teacher / teacher123)")
    if settings.production:
        _warn_demo_passwords(settings)

    app = FastAPI(
        title="StudentHub API",
        description="Автоматизована інформаційна система обліку успішності та відвідуваності студентів",
        version="2.1.0",
        docs_url=None if settings.production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.production else "/api/openapi.json",
    )
    app.state.settings = settings
    app.state.login_limiter = RateLimiter(LOGIN_LIMITS)
    app.state.password_limiter = RateLimiter(PASSWORD_CHANGE_LIMITS)

    # Last added is outermost; security headers go outermost so 413/500 responses get them too
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="sh_session",
        max_age=settings.session_lifetime,
        same_site="lax",
        https_only=settings.production,
    )
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, production=settings.production)

    install_error_handlers(app)
    for module in (auth, users, groups, students, subjects, grades, attendance, dashboard, reports):
        app.include_router(module.router)

    # JSON 404 for unknown API GETs instead of the static fallback; other methods still get 405
    @app.api_route("/api/{rest:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def api_not_found(rest: str):
        return JSONResponse({"error": "Маршрут не знайдено"}, status_code=404)

    def page(name: str):
        path = STATIC_DIR / f"{name}.html"
        return lambda: FileResponse(path, headers={"Cache-Control": "no-cache"})

    app.add_api_route("/", page("index"), include_in_schema=False)
    for name in PAGES:
        app.add_api_route(f"/{name}", page(name), include_in_schema=False)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
