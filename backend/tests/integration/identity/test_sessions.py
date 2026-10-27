"""Session lifetime, rotation and revocation; CSRF and Origin enforcement on unsafe requests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.identity.auth_models import AuthSession
from app.platform.identity.models import AppUser, Membership
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    login,
    make_member,
    origin_headers,
    system,
)

pytestmark = pytest.mark.db

ME = "/api/v1/identity/me"
PREFS = "/api/v1/identity/me/preferences"


def _signed_in(client: TestClient, tenant: Tenant):  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, member.email).status_code == 200
    return member


def _session_rows(user_id) -> list[AuthSession]:  # type: ignore[no-untyped-def]
    with UnitOfWork(system(None)) as uow:
        return list(uow.session.scalars(select(AuthSession).where(AuthSession.user_id == user_id).order_by(AuthSession.created_at, AuthSession.id)))


def test_signed_out_requests_get_a_clean_401(client: TestClient, tenant: Tenant) -> None:
    r = client.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert r.headers["content-type"].startswith("application/problem+json")
    client.cookies.set("lk_session", "not-a-real-token")
    assert client.get(ME).json()["code"] == "unauthenticated"


def test_idle_expiry_is_extended_by_activity(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = _signed_in(client, tenant)
    frozen_clock.advance(hours=11)
    assert client.get(ME).status_code == 200  # touches the session: idle expiry moves 12 h ahead
    frozen_clock.advance(hours=11)
    assert client.get(ME).status_code == 200
    (row,) = _session_rows(member.user_id)
    assert row.last_seen_at == row.created_at + timedelta(hours=22)
    assert row.idle_expires_at == row.last_seen_at + timedelta(hours=12)
    frozen_clock.advance(hours=12, seconds=1)
    r = client.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "session_expired"


def test_absolute_expiry_after_seven_days(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    _signed_in(client, tenant)
    for _ in range(16):  # active every 10 hours for almost seven days
        frozen_clock.advance(hours=10)
        assert client.get(ME).status_code == 200
    frozen_clock.advance(hours=8)  # 168 h after sign-in
    assert client.get(ME).json()["code"] == "session_expired"


def test_sign_in_rotates_the_browser_session(client: TestClient, tenant: Tenant) -> None:
    member = _signed_in(client, tenant)
    first_token = client.cookies.get("lk_session")
    payload = {"email": member.email, "password": TEST_PASSWORD}
    # with a live session in the browser, sign-in is an ordinary unsafe request and needs the CSRF token
    blocked = client.post("/api/v1/identity/session", json=payload, headers=origin_headers())
    assert blocked.status_code == 403 and blocked.json()["code"] == "csrf_token_invalid"
    assert client.post("/api/v1/identity/session", json=payload, headers=csrf_headers(client)).status_code == 200
    assert client.cookies.get("lk_session") != first_token
    old, new = _session_rows(member.user_id)
    assert old.revoked_at is not None and old.revoked_reason == "rotated"
    assert new.rotated_from_id == old.id and new.revoked_at is None
    stale = TestClient(client.app, base_url="http://testserver")
    stale.cookies.set("lk_session", first_token or "")
    assert stale.get(ME).json()["code"] == "session_expired"


def test_logout_revokes_and_clears_cookies(client: TestClient, tenant: Tenant) -> None:
    member = _signed_in(client, tenant)
    token = client.cookies.get("lk_session")
    r = client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    assert r.status_code == 204
    cleared = r.headers.get_list("set-cookie")
    assert any(c.startswith("lk_session=") and "Max-Age=0" in c for c in cleared)
    assert any(c.startswith("lk_csrf=") and "Max-Age=0" in c for c in cleared)
    (row,) = _session_rows(member.user_id)
    assert row.revoked_reason == "logout"
    replay = TestClient(client.app, base_url="http://testserver")
    replay.cookies.set("lk_session", token or "")
    assert replay.get(ME).json()["code"] == "session_expired"


def test_signing_into_another_company_replaces_the_foreign_session(client: TestClient, tenant: Tenant) -> None:
    """Review finding: revoking the browser's session of company A inside a unit of work bound to company B hit
    the tenant stamp (PermissionError, 500). It is now a Core update, and only same-user same-company is a rotation."""
    from tests.integration.identity.fixtures import make_tenant

    first = _signed_in(client, tenant)
    other = make_member(make_tenant(), ["sales"], password=TEST_PASSWORD)
    r = client.post("/api/v1/identity/session", json={"email": other.email, "password": TEST_PASSWORD}, headers=csrf_headers(client))
    assert r.status_code == 200, r.text
    (old,) = _session_rows(first.user_id)
    assert old.revoked_at is not None and old.revoked_reason == "replaced"
    (new,) = _session_rows(other.user_id)
    assert new.rotated_from_id is None and new.company_id == other.company_id
    assert client.get(ME).json()["user"]["email"] == other.email


def test_an_expired_foreign_cookie_does_not_block_sign_in(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.identity.fixtures import make_tenant

    first = _signed_in(client, tenant)
    frozen_clock.advance(days=8)  # expired, never revoked
    other = make_member(make_tenant(), ["sales"], password=TEST_PASSWORD)
    assert login(client, other.email).status_code == 200
    (old,) = _session_rows(first.user_id)
    assert old.revoked_reason == "replaced"


def test_logout_with_a_dead_session_still_clears_the_cookies(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    _signed_in(client, tenant)
    frozen_clock.advance(days=8)
    r = client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    cleared = r.headers.get_list("set-cookie")
    assert any(c.startswith("lk_session=") and "Max-Age=0" in c for c in cleared)
    assert any(c.startswith("lk_csrf=") and "Max-Age=0" in c for c in cleared)
    signed_out = TestClient(client.app, base_url="http://testserver")
    r = signed_out.delete("/api/v1/identity/session", headers=origin_headers())
    assert r.status_code == 401 and any(c.startswith("lk_session=") for c in r.headers.get_list("set-cookie"))


def test_revocation_and_deactivation_apply_on_the_next_request(client: TestClient, tenant: Tenant) -> None:
    member = _signed_in(client, tenant)
    assert client.get(ME).status_code == 200
    with UnitOfWork(system(tenant.company_id)) as uow:
        m = uow.session.get(Membership, member.membership_id)
        assert m is not None
        m.status = "deactivated"
    assert client.get(ME).json()["code"] == "session_expired"
    with UnitOfWork(system(tenant.company_id)) as uow:
        m = uow.session.get(Membership, member.membership_id)
        assert m is not None
        m.status = "active"
    assert client.get(ME).status_code == 200
    with UnitOfWork(system(None)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None
        user.status = "disabled"
    assert client.get(ME).json()["code"] == "session_expired"


def test_unsafe_requests_need_the_session_csrf_token(client: TestClient, tenant: Tenant) -> None:
    _signed_in(client, tenant)
    body = {"ui": {"theme": "dark"}, "expected_version": 0}
    missing = client.patch(PREFS, json=body, headers=origin_headers())
    assert missing.status_code == 403 and missing.json()["code"] == "csrf_token_invalid"
    wrong = client.patch(PREFS, json=body, headers={**origin_headers(), "X-CSRF-Token": "forged"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "csrf_token_invalid"
    foreign = client.patch(PREFS, json=body, headers={**csrf_headers(client), "Origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["code"] == "origin_mismatch"
    cross = client.patch(PREFS, json=body, headers={**csrf_headers(client), "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403 and cross.json()["code"] == "cross_site_request"
    referer_only = client.patch(
        PREFS,
        json=body,
        headers={"Referer": origin_headers()["Origin"] + "/settings", "X-CSRF-Token": client.cookies.get("lk_csrf") or ""},
    )
    assert referer_only.status_code == 200  # Origin falls back to the Referer
    ok = client.patch(PREFS, json={**body, "expected_version": 1}, headers=csrf_headers(client))
    assert ok.status_code == 200
    assert client.get(ME).status_code == 200  # safe methods need no token


def test_csrf_token_is_bound_to_its_session(client: TestClient, tenant: Tenant) -> None:
    _signed_in(client, tenant)
    mine = client.cookies.get("lk_csrf")
    other = TestClient(client.app, base_url="http://testserver")
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(other, member.email).status_code == 200
    r = other.patch(PREFS, json={"ui": {"theme": "dark"}, "expected_version": 0}, headers={**origin_headers(), "X-CSRF-Token": mine or ""})
    assert r.status_code == 403 and r.json()["code"] == "csrf_token_invalid"


def test_bootstrap_rotates_the_csrf_token(client: TestClient, tenant: Tenant) -> None:
    _signed_in(client, tenant)
    before = client.cookies.get("lk_csrf")
    r = client.get("/api/v1/session/bootstrap")
    assert r.status_code == 200
    after = r.json()["csrf_token"]
    assert after != before and client.cookies.get("lk_csrf") == after
    stale = client.patch(PREFS, json={"ui": {"theme": "dark"}, "expected_version": 0}, headers={**origin_headers(), "X-CSRF-Token": before or ""})
    assert stale.status_code == 403 and stale.json()["code"] == "csrf_token_invalid"
    assert client.patch(PREFS, json={"ui": {"theme": "dark"}, "expected_version": 0}, headers=csrf_headers(client)).status_code == 200


def test_tokens_never_come_from_the_url(client: TestClient, tenant: Tenant) -> None:
    _signed_in(client, tenant)
    token = client.cookies.get("lk_session")
    anonymous = TestClient(client.app, base_url="http://testserver")
    for param in ("token", "auth", "session"):
        assert anonymous.get(ME, params={param: token}).status_code == 401
