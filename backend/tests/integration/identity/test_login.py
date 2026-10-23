"""Password sign-in: argon2id, cookies, generic failures, lockout with backoff, Postgres rate limits, audit."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.identity.auth_models import AuthAttempt, AuthSession
from app.platform.identity.errors import GENERIC_SIGN_IN_FAILURE
from app.platform.identity.models import AppUser, Membership
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import TEST_PASSWORD, Tenant, login, make_member, system

pytestmark = pytest.mark.db


def _problem(response) -> dict:  # type: ignore[no-untyped-def]
    body = response.json()
    body.pop("request_id", None)
    return body


def test_successful_sign_in_sets_session_cookies(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Meera Test")
    r = login(client, member.email.upper())  # emails are case-insensitive
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == str(member.user_id)
    assert body["company"]["id"] == str(tenant.company_id)
    assert body["membership_id"] == str(member.membership_id)
    assert body["session"]["auth_method"] == "password"
    assert "token" not in body and body["csrf_token"] == client.cookies.get("lk_csrf")
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("lk_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("lk_csrf="))
    ui_cookie = next(c for c in cookies if c.startswith("lk_ui="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie and "Path=/" in session_cookie
    assert "Max-Age=604800" in session_cookie  # absolute lifetime, 7 days
    assert "HttpOnly" not in csrf_cookie and "HttpOnly" not in ui_cookie
    assert "Secure" not in session_cookie  # development/test; production adds Secure and the __Host- prefix
    assert "theme=system&motion=full" in ui_cookie.replace('"', "")
    with UnitOfWork(system(tenant.company_id)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None and user.password_hash is not None and user.password_hash.startswith("$argon2id$")
        stored = uow.session.scalars(select(AuthSession).where(AuthSession.user_id == member.user_id)).one()
        assert bytes(stored.token_hash) != client.cookies.get("lk_session", "").encode()  # only the hash is stored
        assert stored.idle_expires_at - stored.created_at == timedelta(hours=12)
        assert stored.absolute_expires_at - stored.created_at == timedelta(days=7)
        assert stored.recent_auth_at == stored.created_at and stored.revoked_at is None
        actions = [a.action for a in uow.session.scalars(select(AuditLog).where(AuditLog.actor_user_id == member.user_id))]
    assert "auth.login.succeeded" in actions
    me = client.get("/api/v1/identity/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == member.email


def test_every_failure_is_the_same_generic_401(client: TestClient, tenant: Tenant) -> None:
    good = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    passwordless = make_member(tenant, ["sales"])
    suspended = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    with UnitOfWork(system(tenant.company_id)) as uow:
        m = uow.session.get(Membership, suspended.membership_id)
        assert m is not None
        m.status = "suspended"
    cases = [
        (good.email, TEST_PASSWORD + "x"),  # wrong password
        ("nobody@example.test", TEST_PASSWORD),  # unknown email
        (passwordless.email, TEST_PASSWORD),  # no credentials (demo users)
        (suspended.email, TEST_PASSWORD),  # inactive membership, correct password
        (good.email, "short"),  # outside the policy
    ]
    bodies = []
    for email, password in cases:
        r = login(client, email, password)
        assert r.status_code == 401, (email, r.text)
        bodies.append(_problem(r))
    assert all(b == bodies[0] for b in bodies)
    assert bodies[0]["code"] == "invalid_credentials" and bodies[0]["detail"] == GENERIC_SIGN_IN_FAILURE
    assert "lk_session" not in client.cookies


def test_lockout_after_five_failures_with_backoff(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    for _ in range(5):
        assert login(client, member.email, "wrong-password-123").status_code == 401
    locked = login(client, member.email, TEST_PASSWORD)  # even the right password is refused while locked
    assert locked.status_code == 429
    assert locked.json()["code"] == "account_locked"
    assert int(locked.headers["Retry-After"]) == 15 * 60
    with UnitOfWork(system(tenant.company_id)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None and user.lock_count == 1 and user.locked_until is not None
        actions = [a.action for a in uow.session.scalars(select(AuditLog).where(AuditLog.actor_user_id == member.user_id))]
    assert actions.count("auth.login.failed") == 5 and actions.count("auth.login.locked") == 1

    frozen_clock.advance(minutes=15, seconds=1)
    for _ in range(5):
        assert login(client, member.email, "wrong-password-123").status_code == 401
    second = login(client, member.email, TEST_PASSWORD)
    assert second.status_code == 429 and int(second.headers["Retry-After"]) == 30 * 60  # 15 min x 2^1

    frozen_clock.advance(minutes=30, seconds=1)
    ok = login(client, member.email, TEST_PASSWORD)
    assert ok.status_code == 200
    with UnitOfWork(system(tenant.company_id)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None and (user.failed_login_count, user.lock_count, user.locked_until) == (0, 0, None)


def test_unknown_emails_lock_the_same_way(client: TestClient, tenant: Tenant) -> None:
    for _ in range(5):
        assert login(client, "ghost@example.test", "wrong-password-123").status_code == 401
    r = login(client, "ghost@example.test", "wrong-password-123")
    assert r.status_code == 429 and r.json()["code"] == "account_locked"


def test_email_rate_limit_ten_per_ten_minutes(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    codes = [login(client, member.email, "wrong-password-123").json().get("code") for _ in range(11)]
    assert codes[:5] == ["invalid_credentials"] * 5
    assert codes[5:10] == ["account_locked"] * 5
    assert codes[10] == "rate_limited"
    with UnitOfWork(system(None)) as uow:
        outcomes = [a.outcome for a in uow.session.scalars(select(AuthAttempt).order_by(AuthAttempt.occurred_at, AuthAttempt.id))]
    assert outcomes[-1] == "rate_limited"


def test_ip_rate_limit_thirty_per_ten_minutes(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    for i in range(30):
        r = login(client, f"user{i}@example.test", "wrong-password-123")
        assert r.status_code == 401, i
    blocked = login(client, "user-final@example.test", "wrong-password-123")
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= 600
    frozen_clock.advance(minutes=10)
    assert login(client, "user-next@example.test", "wrong-password-123").status_code == 401  # a new window


def test_sign_in_needs_a_same_origin_request(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    payload = {"email": member.email, "password": TEST_PASSWORD}
    assert client.post("/api/v1/identity/session", json=payload).json()["code"] == "origin_mismatch"
    foreign = client.post("/api/v1/identity/session", json=payload, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["code"] == "origin_mismatch"
    from tests.integration.identity.fixtures import origin_headers

    cross = client.post(
        "/api/v1/identity/session", json=payload, headers={**origin_headers(), "Sec-Fetch-Site": "cross-site"}
    )
    assert cross.status_code == 403 and cross.json()["code"] == "cross_site_request"
    assert login(client, member.email).status_code == 200  # no session yet: Origin is enough


def test_validation_errors_never_echo_the_password(client: TestClient, tenant: Tenant) -> None:
    from tests.integration.identity.fixtures import origin_headers

    r = client.post(
        "/api/v1/identity/session",
        json={"email": "a@b.test", "password": "x" * 2000},
        headers=origin_headers(),
    )
    assert r.status_code == 422
    assert "x" * 50 not in r.text
