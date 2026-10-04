"""Pure-ASGI middleware: request IDs, access logging and security headers."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Iterable

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# The API only ever returns JSON, so its CSP can deny everything. Interactive docs
# (development only) need scripts and styles from the FastAPI CDN, so they are exempt.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware:
    """Assigns a request ID (honouring a well-formed inbound one) and logs each request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = inbound if _VALID_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],  # path only: query strings may carry tokens
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool, docs_paths: Iterable[str] = DOCS_PATHS):
        self.app = app
        self.hsts = hsts
        self.docs_paths = tuple(docs_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_docs = scope["path"].startswith(self.docs_paths)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("x-content-type-options", "nosniff")
                headers.setdefault("x-frame-options", "DENY")
                headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
                headers.setdefault(
                    "permissions-policy", "camera=(), microphone=(), geolocation=(), payment=()"
                )
                headers.setdefault("cross-origin-opener-policy", "same-origin")
                headers.setdefault("cross-origin-resource-policy", "same-site")
                if not is_docs:
                    headers.setdefault("content-security-policy", API_CSP)
                    headers.setdefault("cache-control", "no-store")
                if self.hsts:
                    headers.setdefault(
                        "strict-transport-security", "max-age=63072000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware:
    """Rejects state-changing browser requests from origins outside the allowlist.

    Complements SameSite cookies and the CSRF token, and covers endpoints that run before a
    session exists (login CSRF on /v1/auth/login). Requests without an Origin header
    (server-to-server calls from the web app, CLI tools) are passed through.
    """

    def __init__(self, app: ASGIApp, *, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed = frozenset(o.rstrip("/") for o in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        origin = dict(scope["headers"]).get(b"origin", b"").decode("latin-1")
        if origin and origin.rstrip("/") not in self.allowed:
            response = JSONResponse(
                {"detail": {"code": "origin_rejected", "message": "Request origin not allowed."}},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
