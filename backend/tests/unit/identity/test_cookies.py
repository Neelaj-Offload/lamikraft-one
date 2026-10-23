"""Cookie attributes per environment (api-conventions §7): __Host- prefix and Secure only in production."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response

from app.core.config import reset_settings_cache
from app.platform.identity import sessions
from app.platform.identity.http import clear_session_cookies, set_session_cookies
from app.platform.identity.sessions import IssuedSession

NOW = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)


def _issued() -> IssuedSession:
    return IssuedSession(
        session_id=uuid.uuid4(),
        token="session-token-value",  # noqa: S106
        csrf_token="csrf-token-value",  # noqa: S106
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        created_at=NOW,
        idle_expires_at=NOW + sessions.IDLE_LIFETIME,
        absolute_expires_at=NOW + sessions.ABSOLUTE_LIFETIME,
        auth_method="password",
    )


@pytest.fixture
def production() -> Iterator[None]:
    previous = os.environ.get("LK_ENV")
    os.environ["LK_ENV"] = "production"
    reset_settings_cache()
    try:
        yield
    finally:
        os.environ["LK_ENV"] = previous or "test"
        reset_settings_cache()


def _cookies(response: Response) -> dict[str, str]:
    out = {}
    for raw in response.headers.getlist("set-cookie"):
        out[raw.split("=", 1)[0]] = raw
    return out


def test_test_environment_cookies() -> None:
    response = Response()
    set_session_cookies(response, _issued())
    cookies = _cookies(response)
    assert set(cookies) == {"lk_session", "lk_csrf"}
    assert "HttpOnly" in cookies["lk_session"] and "Secure" not in cookies["lk_session"]
    assert "HttpOnly" not in cookies["lk_csrf"]
    assert f"Max-Age={int(timedelta(days=7).total_seconds())}" in cookies["lk_session"]


def test_production_cookies_use_the_host_prefix_and_secure(production: None) -> None:
    assert sessions.session_cookie_name() == "__Host-lk_session"
    response = Response()
    set_session_cookies(response, _issued())
    cookies = _cookies(response)
    session_cookie = cookies["__Host-lk_session"]
    assert "Secure" in session_cookie and "HttpOnly" in session_cookie and "Path=/" in session_cookie
    assert "Domain" not in session_cookie and "SameSite=lax" in session_cookie
    assert "Secure" in cookies["lk_csrf"] and "HttpOnly" not in cookies["lk_csrf"]
    cleared = Response()
    clear_session_cookies(cleared)
    assert set(_cookies(cleared)) == {"__Host-lk_session", "lk_csrf"}
