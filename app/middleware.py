"""Pure ASGI middleware (security headers, body size limit); also applies to 413/500 responses."""
from __future__ import annotations

import logging

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .constants import MAX_BODY_BYTES
from .errors import HTTP_MESSAGES

log = logging.getLogger("studenthub")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def security_headers(path: str, production: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": PERMISSIONS_POLICY,
    }
    # Swagger UI loads scripts from a CDN, so skip CSP there
    if not path.startswith("/api/docs"):
        headers["Content-Security-Policy"] = CSP
    if path.startswith("/api/"):
        headers["Cache-Control"] = "no-store"
    if production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


class SecurityHeadersMiddleware:
    """Add security headers to every response; turn unhandled exceptions into a 500 JSON response."""

    def __init__(self, app: ASGIApp, production: bool = False):
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(scope["path"], self.production)
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in extra.items():
                    headers.setdefault(name, value)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            log.exception("Необроблена помилка: %s %s", scope.get("method"), scope["path"])
            if started:  # response already started; can't replace it
                raise
            await JSONResponse({"error": "Внутрішня помилка сервера"}, status_code=500)(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """Reject bodies over max_bytes with 413, by Content-Length and while streaming."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await JSONResponse({"error": HTTP_MESSAGES[413]}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:  # covers chunked bodies without Content-Length
                    raise HTTPException(413)
            return message

        await self.app(scope, limited_receive, send)
