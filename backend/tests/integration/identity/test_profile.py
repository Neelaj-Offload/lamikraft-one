"""Own profile (PARITY LM-02/API-02) and self-service password change (LM-03/API-03)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.identity import passwords, provisioning
from app.platform.identity.auth_models import AuthAttempt, AuthSession
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    login,
    make_member,
    make_tenant,
    origin_headers,
    system,
)

pytestmark = pytest.mark.db

ME = "/api/v1/identity/me"
PASSWORD = "/api/v1/identity/me/password"
NEW_PASSWORD = "harbour-Cobalt-73-lantern"  # noqa: S105 - generated for these tests only


def _sessions(user_id) -> list[AuthSession]:  # type: ignore[no-untyped-def]
    with UnitOfWork(system(None)) as uow:
        return list(uow.session.scalars(select(AuthSession).where(AuthSession.user_id == user_id).order_by(AuthSession.created_at, AuthSession.id)))


def test_me_returns_profile_and_effective_permissions(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.export", effect="revoke", reason="no exports"
        )
        provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.read", effect="grant", scope="team", reason="covers the team"
        )
    assert login(client, member.email).status_code == 200
    me = client.get(ME).json()
    perms = {p["key"]: p["scope"] for p in me["permissions"]}
    assert perms["sales.quote.read"] == "team" and "sales.quote.export" not in perms
    assert perms["org.company.read"] == "company"  # the employee base
    overrides = {o["permission_key"]: o for o in me["overrides"]}
    assert set(overrides) == {"sales.quote.export", "sales.quote.read"}
    assert overrides["sales.quote.export"]["effect"] == "revoke" and overrides["sales.quote.export"]["scope"] is None
    assert overrides["sales.quote.read"]["reason"] == "covers the team" and overrides["sales.quote.read"]["in_effect"] is True
    # the bootstrap reports the same effective permissions
    boot = client.get("/api/v1/session/bootstrap").json()
    assert {p["key"]: p["scope"] for p in boot["permissions"]} == perms


def test_sign_in_records_the_attempt_and_last_login(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, member.email, "not-the-password-1").status_code == 401
    assert login(client, member.email).status_code == 200
    with UnitOfWork(system(None)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None and user.last_login_at is not None
        attempts = list(uow.session.scalars(select(AuthAttempt).where(AuthAttempt.user_id == member.user_id).order_by(AuthAttempt.occurred_at)))
    outcomes = [a.outcome for a in attempts]
    assert len(outcomes) == 2 and outcomes == ["invalid_credentials", "success"]


def test_change_password_revokes_other_sessions(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    other_device = TestClient(client.app, base_url="http://testserver")
    assert login(other_device, member.email).status_code == 200
    # a second company of the same user: its sessions end too
    elsewhere = make_tenant()
    with UnitOfWork(system(elsewhere.company_id)) as uow:
        provisioning.provision_membership(
            uow, user_id=member.user_id, status="active", role_keys=["sales"], default_branch_id=elsewhere.ho_branch_id
        )
    assert login(client, member.email).status_code == 200
    before = client.cookies.get("lk_session")
    r = client.post(PASSWORD, json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD}, headers=csrf_headers(client))
    assert r.status_code == 200, r.text
    assert r.json()["csrf_token"] == client.cookies.get("lk_csrf")
    assert client.cookies.get("lk_session") != before  # the caller's session rotated
    assert client.get(ME).status_code == 200
    assert other_device.get(ME).json()["code"] == "session_expired"
    live = [s for s in _sessions(member.user_id) if s.revoked_at is None]
    assert len(live) == 1
    reasons = sorted(s.revoked_reason or "" for s in _sessions(member.user_id) if s.revoked_at is not None)
    assert reasons == ["password_changed", "rotated"]
    with UnitOfWork(system(None)) as uow:
        user = uow.session.get(AppUser, member.user_id)
        assert user is not None and user.password_changed_at is not None
        assert passwords.verify_password(user.password_hash, NEW_PASSWORD)
    with UnitOfWork(system(tenant.company_id)) as uow:
        audited = list(uow.session.scalars(select(AuditLog).where(AuditLog.action == "auth.password.changed")))
    assert len(audited) == 1 and (audited[0].details or {}).get("other_sessions_revoked") == 1
    fresh = TestClient(client.app, base_url="http://testserver")
    assert login(fresh, member.email).status_code == 401
    assert login(fresh, member.email, NEW_PASSWORD).status_code == 200


def test_change_password_needs_the_current_password_and_the_policy(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, member.email).status_code == 200
    wrong = client.post(PASSWORD, json={"current_password": "not-it-at-all", "new_password": NEW_PASSWORD}, headers=csrf_headers(client))
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["code"] == "invalid_current_password"
    assert "not-it-at-all" not in wrong.text
    weak = client.post(PASSWORD, json={"current_password": TEST_PASSWORD, "new_password": "short"}, headers=csrf_headers(client))
    assert weak.status_code == 422
    same = client.post(PASSWORD, json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD}, headers=csrf_headers(client))
    assert same.status_code == 422 and same.json()["errors"][0]["code"] == "password_unchanged"
    assert client.get(ME).status_code == 200  # nothing changed: the session is still live
    signed_out = TestClient(client.app, base_url="http://testserver")
    r = signed_out.post(PASSWORD, json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD}, headers=origin_headers())
    assert r.status_code == 401


def test_change_password_is_rate_limited(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, member.email).status_code == 200
    body = {"current_password": "wrong-guess-000", "new_password": NEW_PASSWORD}
    codes = [client.post(PASSWORD, json=body, headers=csrf_headers(client)).status_code for _ in range(11)]
    assert codes[:10] == [422] * 10 and codes[10] == 429
