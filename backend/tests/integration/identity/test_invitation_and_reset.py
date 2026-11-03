"""Invitations and password resets (PARITY LM-04 create part, LM-05, PERM-27, API-04 invite, API-06; platform
design §4): single-use, expiring links with fragment tokens, hashes only, demo .eml output, rate limits."""

from __future__ import annotations

from email import message_from_bytes
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.events.models import DomainEvent
from app.platform.identity import ratelimit
from app.platform.identity.auth_models import AuthSession
from app.platform.identity.credential_models import Invitation, MfaFactor, PasswordReset
from app.platform.identity.models import AppUser, Membership
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    enrol_mfa,
    login,
    login_admin,
    make_member,
    origin_headers,
    system,
    totp_code,
    verify_code,
)

pytestmark = pytest.mark.db

NEW_PASSWORD = "harbour-Lantern-58-meadow"  # noqa: S105 - test value
INVITES = "/api/v1/identity/invitations"


def _token(link: str) -> str:
    assert "#t=" in link and "?" not in link, link  # the token travels only in the fragment
    return link.split("#t=", 1)[1]


def _eml(outbox: Path, name: str) -> str:
    msg = message_from_bytes((outbox / name).read_bytes())
    assert msg["X-Lamikraft-Delivery"] == "demo (not sent)"
    payload = msg.get_payload(decode=True)
    assert isinstance(payload, bytes)
    return payload.decode()


def _invite(client: TestClient, tenant: Tenant, email: str = "arjun.new@example.test", roles=("sales",)):  # type: ignore[no-untyped-def]
    return client.post(
        INVITES,
        json={"email": email, "display_name": "Arjun N", "job_title": "Sales executive", "role_keys": list(roles), "branch_ids": [str(tenant.ho_branch_id)]},
        headers=csrf_headers(client),
    )


def test_invitation_link_is_single_use_and_signs_the_person_in(client: TestClient, tenant: Tenant, demo_outbox: Path) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    r = _invite(client, tenant)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["delivery"]["mode"] == "demo_outbox" and body["delivery"]["label"] == "Email delivery: Demo, not sent"
    token = _token(body["delivery"]["manual_link"])
    assert body["invitation"]["status"] == "open" and body["invitation"]["send_count"] == 1
    # the .eml in the demo outbox carries the same link
    assert body["delivery"]["manual_link"] in _eml(demo_outbox, body["delivery"]["outbox_file"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        row = uow.session.get(Invitation, body["invitation"]["id"])
        assert row is not None and row.token_hash is not None and token.encode() not in bytes(row.token_hash)
        member = uow.session.get(Membership, body["invitation"]["membership_id"])
        assert member is not None and member.status == "invited"

    guest = TestClient(client.app, base_url="http://testserver")
    preview = guest.post(f"{INVITES}/preview", json={"token": token}, headers=origin_headers())
    assert preview.status_code == 200 and preview.json()["email"] == "arjun.new@example.test"
    assert preview.json()["has_password"] is False
    weak = guest.post(f"{INVITES}/acceptance", json={"token": token, "password": "short"}, headers=origin_headers())
    assert weak.status_code == 422
    accepted = guest.post(f"{INVITES}/acceptance", json={"token": token, "password": NEW_PASSWORD}, headers=origin_headers())
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["stage"] == "active"
    assert guest.get("/api/v1/identity/me").json()["membership"]["status"] == "active"
    # single use
    reused = TestClient(client.app, base_url="http://testserver").post(
        f"{INVITES}/acceptance", json={"token": token, "password": NEW_PASSWORD}, headers=origin_headers()
    )
    assert reused.status_code == 401 and reused.json()["code"] == "link_invalid_or_used"
    with UnitOfWork(system(tenant.company_id)) as uow:
        types = [e.event_type for e in uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == tenant.company_id).order_by(DomainEvent.seq))]
    assert "identity.invitation.sent" in types and "identity.invitation.accepted" in types
    assert "identity.membership.activated" in types


def test_invitations_expire_are_reissued_and_revoked(client: TestClient, tenant: Tenant, demo_outbox: Path, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    secret = login_admin(client, admin)
    first = _invite(client, tenant).json()
    old = _token(first["delivery"]["manual_link"])
    again = client.post(f"{INVITES}/{first['invitation']['id']}/reissue", headers=csrf_headers(client))
    assert again.status_code == 200 and again.json()["invitation"]["send_count"] == 2
    new = _token(again.json()["delivery"]["manual_link"])
    guest = TestClient(client.app, base_url="http://testserver")
    assert guest.post(f"{INVITES}/preview", json={"token": old}, headers=origin_headers()).status_code == 401
    assert guest.post(f"{INVITES}/preview", json={"token": new}, headers=origin_headers()).status_code == 200
    frozen_clock.advance(days=7, seconds=1)
    expired = guest.post(f"{INVITES}/acceptance", json={"token": new, "password": NEW_PASSWORD}, headers=origin_headers())
    assert expired.status_code == 401 and expired.json()["code"] == "link_invalid_or_used"
    # reissue restarts the 7 days; revoking closes the link for good
    assert client.get("/api/v1/identity/me").status_code == 401  # the admin's own session ended meanwhile (7 days)
    assert login(client, admin.email).json()["stage"] == "mfa_pending"
    assert verify_code(client, totp_code(secret)).status_code == 200
    third = client.post(f"{INVITES}/{first['invitation']['id']}/reissue", headers=csrf_headers(client))
    assert third.status_code == 200
    revoked = client.delete(f"{INVITES}/{first['invitation']['id']}", headers=csrf_headers(client))
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    latest = _token(third.json()["delivery"]["manual_link"])
    assert guest.post(f"{INVITES}/preview", json={"token": latest}, headers=origin_headers()).status_code == 401


def test_inviting_needs_user_manage_and_never_duplicates_members(client: TestClient, tenant: Tenant, demo_outbox: Path) -> None:
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login(client, sales.email)
    assert _invite(client, tenant).status_code == 403
    admin_client = TestClient(client.app, base_url="http://testserver")
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(admin_client, admin)
    dup = _invite(admin_client, tenant, email=sales.email.upper())
    assert dup.status_code == 409 and dup.json()["code"] == "already_member"
    unknown_role = _invite(admin_client, tenant, roles=("nonexistent",))
    assert unknown_role.status_code == 422


def test_admin_reset_never_returns_password(client: TestClient, tenant: Tenant, demo_outbox: Path) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login_admin(client, admin)
    member_client = TestClient(client.app, base_url="http://testserver")
    assert login(member_client, member.email).status_code == 200
    secret, _ = enrol_mfa(member_client)  # the member opted in to MFA: a reset keeps it

    r = client.post(f"/api/v1/identity/users/{member.user_id}/password-reset", headers=csrf_headers(client))
    assert r.status_code == 201, r.text
    body = r.json()
    assert "password" not in {k.lower() for k in body} and set(body) == {"user_id", "expires_at", "delivery"}
    token = _token(body["delivery"]["manual_link"])
    assert body["delivery"]["manual_link"] in _eml(demo_outbox, body["delivery"]["outbox_file"])
    with UnitOfWork(system(None)) as uow:
        rows = list(uow.session.scalars(select(PasswordReset).where(PasswordReset.user_id == member.user_id)))
    assert len(rows) == 1 and rows[0].kind == "admin_issued" and token.encode() not in bytes(rows[0].token_hash)
    assert (rows[0].expires_at - rows[0].created_at).total_seconds() == 24 * 3600

    guest = TestClient(client.app, base_url="http://testserver")
    done = guest.post("/api/v1/identity/password-resets/completion", json={"token": token, "password": NEW_PASSWORD}, headers=origin_headers())
    assert done.status_code == 204, done.text
    # every session ended; the old password no longer works; MFA is kept
    assert member_client.get("/api/v1/identity/me").status_code == 401
    assert login(guest, member.email).status_code == 401
    assert login(guest, member.email, NEW_PASSWORD).json()["stage"] == "mfa_pending"
    with UnitOfWork(system(None)) as uow:
        assert uow.session.scalars(select(MfaFactor).where(MfaFactor.user_id == member.user_id, MfaFactor.disabled_at.is_(None))).first()
        open_sessions = uow.session.scalars(
            select(AuthSession).where(AuthSession.user_id == member.user_id, AuthSession.revoked_at.is_(None))
        ).all()
    assert len(open_sessions) == 1  # only the new pending sign-in
    # single use
    again = TestClient(client.app, base_url="http://testserver").post(
        "/api/v1/identity/password-resets/completion", json={"token": token, "password": NEW_PASSWORD + "x"}, headers=origin_headers()
    )
    assert again.status_code == 401 and again.json()["code"] == "link_invalid_or_used"
    with UnitOfWork(system(tenant.company_id)) as uow:
        kinds = [e.payload.get("kind") for e in uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "identity.user.credentials_changed"))]
    assert "password_reset" in kinds
    # an administrator cannot reset their own password this way
    own = client.post(f"/api/v1/identity/users/{admin.user_id}/password-reset", headers=csrf_headers(client))
    assert own.status_code == 403


def test_self_service_reset_is_always_accepted_and_rate_limited(client: TestClient, tenant: Tenant, demo_outbox: Path, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    unknown = client.post("/api/v1/identity/password-resets", json={"email": "nobody@example.test"}, headers=origin_headers())
    assert unknown.status_code == 202 and not demo_outbox.exists()
    known = client.post("/api/v1/identity/password-resets", json={"email": member.email}, headers=origin_headers())
    assert known.status_code == 202
    files = list(demo_outbox.glob("*password_reset*.eml"))
    assert len(files) == 1
    text = _eml(demo_outbox, files[0].name)
    token = text.split("#t=", 1)[1].split()[0]
    with UnitOfWork(system(None)) as uow:
        row = uow.session.scalars(select(PasswordReset).where(PasswordReset.user_id == member.user_id)).one()
    assert row.kind == "self_service" and (row.expires_at - row.created_at).total_seconds() == 30 * 60
    frozen_clock.advance(minutes=31)
    late = client.post("/api/v1/identity/password-resets/completion", json={"token": token, "password": NEW_PASSWORD}, headers=origin_headers())
    assert late.status_code == 401
    # per-address limit (shared by the reset endpoints): 30 per 10-minute window, then 429 with Retry-After
    statuses = [
        client.post("/api/v1/identity/password-resets", json={"email": "x@example.test"}, headers=origin_headers())
        for _ in range(ratelimit.IP_LIMIT)
    ]
    assert [r.status_code for r in statuses[:-1]] == [202] * (ratelimit.IP_LIMIT - 1)
    assert statuses[-1].status_code == 429 and statuses[-1].headers.get("retry-after")


def test_existing_people_from_another_company_confirm_their_password(client: TestClient, tenant: Tenant, demo_outbox: Path) -> None:
    from tests.integration.identity.fixtures import make_tenant

    other = make_tenant()
    person = make_member(other, ["sales"], password=TEST_PASSWORD)
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    r = _invite(client, tenant, email=person.email)
    assert r.status_code == 201
    token = _token(r.json()["delivery"]["manual_link"])
    guest = TestClient(client.app, base_url="http://testserver")
    assert guest.post(f"{INVITES}/preview", json={"token": token}, headers=origin_headers()).json()["has_password"] is True
    wrong = guest.post(f"{INVITES}/acceptance", json={"token": token, "password": NEW_PASSWORD}, headers=origin_headers())
    assert wrong.status_code == 422
    ok = guest.post(f"{INVITES}/acceptance", json={"token": token, "password": TEST_PASSWORD}, headers=origin_headers())
    assert ok.status_code == 200
    with UnitOfWork(system(None)) as uow:
        user = uow.session.get(AppUser, person.user_id)
        assert user is not None and user.status == "active"
