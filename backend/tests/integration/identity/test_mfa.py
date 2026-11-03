"""Two-step sign-in (TOTP) for administrators, step-up on admin actions, recovery codes and resets
(PARITY LP-01.8, PERM-29 MFA part; platform design §4 MFA; permissions.md §6 MFA/RA flags)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.events.models import DomainEvent
from app.platform.identity import service
from app.platform.identity.auth_models import AuthAttempt, AuthSession
from app.platform.identity.credential_models import MfaFactor, MfaRecoveryCode
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    enrol_mfa,
    login,
    login_admin,
    make_member,
    make_tenant,
    origin_headers,
    system,
    totp_code,
    verify_code,
)

pytestmark = pytest.mark.db

ME = "/api/v1/identity/me"


def _override(client: TestClient, user_id, key: str = "sales.quote.export"):  # type: ignore[no-untyped-def]
    return client.put(
        f"/api/v1/identity/users/{user_id}/permission-overrides/{key}",
        json={"effect": "revoke", "reason": "Exports go through the manager"},
        headers=csrf_headers(client),
    )


def test_admin_enrolment_replay_rejected_recovery_once(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)

    # 1. the password alone gives an enrolment-only session for an administrator
    first = login(client, admin.email)
    assert first.status_code == 200 and first.json()["stage"] == "mfa_enrollment_required"
    blocked = client.get(ME)
    assert blocked.status_code == 401 and blocked.json()["code"] == "mfa_enrollment_required"
    status = client.get(f"{ME}/mfa").json()
    assert status["required"] is True and status["enrolled"] is False

    # 2. enrolment: the seed is stored encrypted, recovery codes as hashes, the session becomes MFA-verified
    secret, codes = enrol_mfa(client)
    assert len(codes) == 10 and len(set(codes)) == 10
    me = client.get(ME)
    assert me.status_code == 200, me.text
    assert client.get(f"{ME}/mfa").json() | {"confirmed_at": None} == {
        "enrolled": True,
        "pending": False,
        "confirmed_at": None,
        "recovery_codes_remaining": 10,
        "required": True,
        "session_verified": True,
    }
    with UnitOfWork(system(None)) as uow:
        factor = uow.session.scalars(select(MfaFactor).where(MfaFactor.user_id == admin.user_id)).one()
        assert secret.encode() not in bytes(factor.secret_ciphertext)
        stored = [bytes(r.code_hash) for r in uow.session.scalars(select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == admin.user_id))]
        assert all(code.encode() not in h for code in codes for h in stored)
    used_code = totp_code(secret)

    # 3. the next sign-in waits for a code; the code of an already used step is a replay
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    pending = login(client, admin.email)
    assert pending.json()["stage"] == "mfa_pending"
    assert client.get(ME).json()["code"] == "mfa_verification_required"
    replay = verify_code(client, used_code)
    assert replay.status_code == 401 and replay.json()["code"] == "invalid_code"
    frozen_clock.advance(seconds=30)
    fresh = totp_code(secret)
    ok = verify_code(client, fresh)
    assert ok.status_code == 200, ok.text
    assert ok.json()["stage"] == "active"
    assert client.get(ME).status_code == 200

    # 4. a recovery code works exactly once
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    login(client, admin.email)
    assert verify_code(client, codes[0]).status_code == 200
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    login(client, admin.email)
    again = verify_code(client, codes[0])
    assert again.status_code == 401 and again.json()["code"] == "invalid_code"
    assert verify_code(client, fresh).status_code == 401  # the TOTP replay is refused here too
    assert verify_code(client, codes[1].upper().replace("-", " ")).status_code == 200  # typed loosely: still valid
    assert client.get(f"{ME}/mfa").json()["recovery_codes_remaining"] == 8

    with UnitOfWork(system(None)) as uow:
        kinds = {(a.kind, a.outcome) for a in uow.session.scalars(select(AuthAttempt).where(AuthAttempt.user_id == admin.user_id))}
    assert ("mfa", "invalid_code") in kinds and ("mfa", "success") in kinds


def test_five_wrong_codes_end_the_pending_session(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    login(client, admin.email)
    for _ in range(4):
        assert verify_code(client, "000000").json()["code"] == "invalid_code"
    last = verify_code(client, "000000")
    assert last.status_code == 401 and last.json()["code"] == "session_expired"
    with UnitOfWork(system(None)) as uow:
        revoked = uow.session.scalars(
            select(AuthSession).where(AuthSession.user_id == admin.user_id, AuthSession.revoked_reason == "mfa_attempts")
        ).all()
    assert len(revoked) == 1


def test_members_without_privileged_keys_sign_in_directly_and_may_opt_in(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    r = login(client, sales.email)
    assert r.json()["stage"] == "active"
    assert client.get(f"{ME}/mfa").json()["required"] is False
    secret, _codes = enrol_mfa(client)
    # opted in: the authenticator is now asked for at every sign-in
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    assert login(client, sales.email).json()["stage"] == "mfa_pending"
    frozen_clock.advance(seconds=30)
    assert verify_code(client, totp_code(secret)).status_code == 200
    # and the member may remove it again with a current code
    frozen_clock.advance(seconds=30)
    removed = client.request("DELETE", f"{ME}/mfa/totp", json={"code": totp_code(secret)}, headers=csrf_headers(client))
    assert removed.status_code == 200 and removed.json()["enrolled"] is False
    client.delete("/api/v1/identity/session", headers=csrf_headers(client))
    assert login(client, sales.email).json()["stage"] == "active"


def test_admins_cannot_remove_the_required_authenticator(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    secret = login_admin(client, admin)
    frozen_clock.advance(seconds=30)
    r = client.request("DELETE", f"{ME}/mfa/totp", json={"code": totp_code(secret)}, headers=csrf_headers(client))
    assert r.status_code == 409 and r.json()["code"] == "mfa_required_by_policy"
    # a second enrolment is refused while one is confirmed
    again = client.post(f"{ME}/mfa/totp", headers=csrf_headers(client))
    assert again.status_code == 409 and again.json()["code"] == "mfa_already_enrolled"
    # recovery codes can be regenerated with a current code (the old ones stop working)
    frozen_clock.advance(seconds=30)
    regenerated = client.post(f"{ME}/mfa/recovery-codes", json={"code": totp_code(secret)}, headers=csrf_headers(client))
    assert regenerated.status_code == 200 and len(regenerated.json()["recovery_codes"]) == 10


def test_admin_actions_need_an_mfa_verified_session(db: None, api_app, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    """Demo-link sessions are not forced to enrol, but an MFA-flagged action needs a code (step-up)."""
    demo = make_tenant(is_demo=True)
    admin = make_member(demo, ["admin"])
    target = make_member(demo, ["sales"])
    link = service.issue_demo_link(company_key=demo.key, email=admin.email)
    with TestClient(api_app, base_url="http://testserver") as c:
        signed = c.post("/api/v1/identity/demo-sign-in", json={"token": link.token}, headers=origin_headers())
        assert signed.status_code == 200 and signed.json()["stage"] == "active"
        denied = _override(c, target.user_id)
        assert denied.status_code == 401 and denied.json()["code"] == "mfa_required"
        # a password re-authentication does not satisfy the MFA flag (demo members have no password anyway)
        assert c.post("/api/v1/identity/session/reauthentication", json={"password": "x" * 12}, headers=csrf_headers(c)).status_code == 422
        secret, _ = enrol_mfa(c)  # enrolling verifies the session (and counts as a recent authentication)
        assert _override(c, target.user_id).status_code == 200
        frozen_clock.advance(minutes=11)
        assert _override(c, target.user_id, "sales.quote.read").json()["code"] == "reauth_required"
        frozen_clock.advance(seconds=30)
        step_up = c.post("/api/v1/identity/session/reauthentication", json={"code": totp_code(secret)}, headers=csrf_headers(c))
        assert step_up.status_code == 200 and step_up.json()["auth_strength"] == "mfa"
        assert _override(c, target.user_id, "sales.quote.read").status_code == 200


def test_security_policy_all_requires_every_member_to_enrol(client: TestClient, tenant: Tenant) -> None:
    from app.platform.org import service as org

    with UnitOfWork(system(tenant.company_id)) as uow:
        org.update_setting(uow, "security_policy", value={"mfa_required_for": "all"}, expected_version=0)
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, sales.email).json()["stage"] == "mfa_enrollment_required"
    assert client.get(f"{ME}/mfa").json()["required"] is True


def test_admin_resets_a_lost_authenticator(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    other_admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    other = TestClient(client.app, base_url="http://testserver")
    login_admin(other, other_admin)
    url = f"/api/v1/identity/users/{other_admin.user_id}/mfa"
    own = client.request("DELETE", f"/api/v1/identity/users/{admin.user_id}/mfa", json={"reason": "x"}, headers=csrf_headers(client))
    assert own.status_code == 403
    r = client.request("DELETE", url, json={"reason": "Lost phone"}, headers=csrf_headers(client))
    assert r.status_code == 204, r.text
    assert other.get(ME).status_code == 401  # their sessions ended
    assert login(other, other_admin.email).json()["stage"] == "mfa_enrollment_required"
    with UnitOfWork(system(tenant.company_id)) as uow:
        events = list(uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "identity.user.credentials_changed")))
    assert {e.payload["kind"] for e in events} >= {"mfa_enrolled", "mfa_reset"}
    # a member without identity.mfa.manage cannot
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    s = TestClient(client.app, base_url="http://testserver")
    login(s, sales.email)
    assert s.request("DELETE", url, json={"reason": "x"}, headers=csrf_headers(s)).status_code == 403


def test_privileged_keys_are_identity_org_audit_system_administration() -> None:
    from app.platform.identity import mfa

    keys = mfa.privileged_keys()
    assert {"identity.user.manage", "identity.role.manage", "audit.log.read", "org.company.update"} <= keys
    assert not any(k.startswith(("sales.", "pricing.", "finance.")) for k in keys)
