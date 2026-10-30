"""Request context, security headers and the CSRF/Origin guard (pure ASGI middleware).

Unsafe methods on /api must come from the configured public origin (Origin, else Referer;
Sec-Fetch-Site must not be cross-site) and, once a session exists, carry a valid X-CSRF-Token.
The token verifier is registered by identity. Webhook routes are exempt (they verify signatures).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

import structlog
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CsrfVerifier = Callable[[Request], bool]
_csrf_verifier: CsrfVerifier | None = None


def register_csrf_verifier(verifier: CsrfVerifier) -> None:
    global _csrf_verifier
    _csrf_verifier = verifier


def _origin_of(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


#: headers every response carries unless the route set them (lower-case names, as ASGI sends them)
_DEFAULT_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict((k.decode().lower(), v.decode()) for k, v in scope.get("headers", []))
        request_id = uuid.uuid4().hex
        correlation_id = headers.get("x-correlation-id", request_id)[:64]
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        scope["state"]["correlation_id"] = correlation_id
        structlog.contextvars.bind_contextvars(request_id=request_id, path=scope.get("path"))

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = [(b"x-request-id", request_id.encode())]
                # Security defaults, each only when the route has not set its own (a download chooses its
                # Cache-Control; a route that sets nosniff itself must not get the header twice).
                for name, value in _DEFAULT_HEADERS:
                    if name not in present:
                        extra.append((name, value))
                message["headers"] = headers + extra
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.clear_contextvars()


class CsrfOriginMiddleware:
    def __init__(self, app: ASGIApp, *, public_origin: str, exempt_paths: Callable[[], set[str]]) -> None:
        self.app = app
        self.public_origin = public_origin.rstrip("/")
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if scope["path"] in self.exempt_paths():
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        origin = _origin_of(request.headers.get("origin")) or _origin_of(request.headers.get("referer"))
        fetch_site = request.headers.get("sec-fetch-site")
        problem: str | None = None
        if fetch_site == "cross-site":
            problem = "cross_site_request"
        elif origin is None or origin != self.public_origin:
            problem = "origin_mismatch"
        elif _csrf_verifier is not None and not await run_in_threadpool(_csrf_verifier, request):
            # the verifier reads the session row; keep blocking DB I/O off the event loop
            problem = "csrf_token_invalid"
        if problem:
            body = {
                "type": f"https://lamikraft.one/problems/{problem}",
                "title": "Request blocked by CSRF protection",
                "status": 403,
                "code": problem,
                "detail": "Reload the page and try again.",
            }
            await JSONResponse(body, status_code=403, media_type="application/problem+json")(scope, receive, send)
            return
        await self.app(scope, receive, send)
