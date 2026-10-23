"""HTTP glue for identity: the session-cookie actor resolver, the CSRF verifier and cookie helpers.

Registered in the identity manifest ``on_load``:
- ``app.core.http.deps.register_actor_resolver(resolve_actor)``: ``lk_session`` → ActorContext; touches the idle
  expiry; a revoked or expired session, a disabled user or an inactive membership is a 401 ``session_expired``;
- ``app.core.http.middleware.register_csrf_verifier(verify_csrf)``: once a live session is presented, every unsafe
  ``/api`` request must echo the session's CSRF secret in ``X-CSRF-Token`` (constant-time comparison). Without a
  live session (sign-in, demo sign-in) only the Origin and Sec-Fetch-Site checks apply.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db.engine import session_factory
from app.core.errors import AppError
from app.platform.authz.context import ActorContext, AuthStrength
from app.platform.identity import sessions
from app.platform.identity.actors import bind_tenant, build_member_actor
from app.platform.identity.auth_models import AuthMethod, AuthSession
from app.platform.identity.errors import SessionExpired
from app.platform.identity.preferences import UiPreferences, ui_cookie_value
from app.platform.identity.sessions import CSRF_COOKIE, CSRF_HEADER, UI_COOKIE, ClientInfo, IssuedSession
from app.platform.identity.tokens import matches, sha256

if TYPE_CHECKING:
    from datetime import datetime

_STRENGTH: dict[str, AuthStrength] = {
    AuthMethod.PASSWORD.value: "password",
    AuthMethod.DEMO_LINK.value: "demo_link",
    AuthMethod.TEST_SUPPORT.value: "password",
}
UI_COOKIE_MAX_AGE = 400 * 24 * 3600


def client_ip(request: Request) -> str | None:
    """The caller's address for rate limits and audit.

    The browser reaches FastAPI through the same-origin Next.js rewrite (a local proxy), so the socket peer is
    a loopback address for everyone. Only when the peer is loopback is ``X-Forwarded-For`` trusted, and then
    only its last entry — the address our own proxy appended — never a client-supplied earlier entry.
    """
    peer = request.client.host if request.client else None
    if peer is None:
        return None
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if loopback and forwarded:
        last = forwarded.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            return peer
    return peer


def client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
        session_token=request.cookies.get(sessions.session_cookie_name()),
    )


def resolve_actor(request: Request) -> ActorContext | None:
    """Session cookie → ActorContext (None when no session cookie or an unknown token)."""
    token = request.cookies.get(sessions.session_cookie_name())
    if not token or len(token) > 512:
        return None
    with session_factory()() as session, session.begin():
        row = session.scalars(select(AuthSession).where(AuthSession.token_hash == sha256(token))).first()
        if row is None:
            return None
        if row.company_id is None:
            raise SessionExpired()
        now = get_clock(row.company_id).now()
        if not sessions.is_live(row, now):
            raise SessionExpired()
        bind_tenant(session, row.company_id, row.user_id)
        actor = build_member_actor(
            session,
            row.company_id,
            row.user_id,
            channel="web",
            now=now,
            session_id=row.id,
            auth_strength=_STRENGTH.get(row.auth_method, "password"),
            recent_auth_at=row.recent_auth_at,
        )
        if actor is None or actor.membership_id != row.membership_id:
            raise SessionExpired()
        sessions.touch(row, now)
        bind_tenant(session, None)
    return actor


def verify_csrf(request: Request) -> bool:
    """X-CSRF-Token must match the live session's CSRF secret; requests without a live session pass."""
    token = request.cookies.get(sessions.session_cookie_name())
    if not token or len(token) > 512:
        return True
    with session_factory()() as session, session.begin():
        row = session.scalars(select(AuthSession).where(AuthSession.token_hash == sha256(token))).first()
        if row is None or row.company_id is None:
            return True
        if not sessions.is_live(row, get_clock(row.company_id).now()):
            return True
        stored = bytes(row.csrf_hash)
    return matches(request.headers.get(CSRF_HEADER), stored)


# ---- cookies ---------------------------------------------------------------------------------------
def _secure() -> bool:
    return get_settings().is_production


def _max_age(until: datetime, now: datetime) -> int:
    return max(0, int((until - now).total_seconds()))


def set_session_cookies(response: Response, issued: IssuedSession) -> None:
    max_age = _max_age(issued.absolute_expires_at, issued.created_at)
    response.set_cookie(
        sessions.session_cookie_name(),
        issued.token,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=_secure(),
        samesite="lax",
    )
    set_csrf_cookie(response, issued.csrf_token, max_age=max_age)


def set_csrf_cookie(response: Response, csrf_token: str, *, max_age: int | None = None) -> None:
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=max_age, path="/", httponly=False, secure=_secure(), samesite="lax"
    )


def set_ui_cookie(response: Response, ui: UiPreferences) -> None:
    response.set_cookie(
        UI_COOKIE, ui_cookie_value(ui), max_age=UI_COOKIE_MAX_AGE, path="/", httponly=False, secure=_secure(), samesite="lax"
    )


def clear_session_cookies(response: Response) -> None:
    for name, httponly in ((sessions.session_cookie_name(), True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", httponly=httponly, secure=_secure(), samesite="lax")


def problem_response(request: Request, exc: AppError, headers: dict[str, str] | None = None) -> JSONResponse:
    """Render an AppError with extra headers (``Retry-After``), matching the global problem+json handler."""
    return JSONResponse(
        exc.to_problem(getattr(request.state, "request_id", None)),
        status_code=exc.status,
        media_type="application/problem+json",
        headers=headers,
    )
