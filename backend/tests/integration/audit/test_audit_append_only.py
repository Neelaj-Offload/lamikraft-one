"""PARITY LM-100 / SEC-07: the audit log is append-only (trigger + lk_app privileges) and records security events:
sign-in, MFA enrolment, role changes with diffs, permission overrides, deactivation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.platform.audit.models import AuditLog
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (  # noqa: F401
    TEST_PASSWORD,
    Tenant,
    api_app,
    client,
    csrf_headers,
    login_admin,
    make_member,
    system,
    tenant,
)

pytestmark = pytest.mark.db


def test_update_delete_rejected_and_security_events_recorded(client: TestClient, tenant: Tenant) -> None:  # noqa: F811
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    target = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login_admin(client, admin)
    users = f"/api/v1/identity/users/{target.user_id}"
    assert client.put(f"{users}/roles", json={"role_keys": ["operations"]}, headers=csrf_headers(client)).status_code == 200
    put = client.put(f"{users}/permission-overrides/sales.quote.read", json={"effect": "revoke", "reason": "Audit test"}, headers=csrf_headers(client))
    assert put.status_code == 200
    assert client.post(f"{users}/deactivation", json={"reason": "Left"}, headers=csrf_headers(client)).status_code == 200

    with UnitOfWork(system(tenant.company_id)) as uow:
        rows = {r.action: r for r in uow.session.scalars(select(AuditLog).where(AuditLog.company_id == tenant.company_id))}
    for action in (
        "auth.login.succeeded",
        "auth.mfa.enrolled",
        "identity.membership.roles_changed",
        "identity.permission_override.set",
        "identity.membership.deactivated",
    ):
        assert action in rows, action
    assert rows["identity.membership.roles_changed"].changes == {"roles": {"from": ["sales"], "to": ["operations"]}}
    assert rows["identity.membership.roles_changed"].actor_user_id == admin.user_id
    assert rows["identity.permission_override.set"].reason == "Audit test"
    assert rows["identity.membership.deactivated"].session_id is not None

    # append-only: neither UPDATE nor DELETE is possible for the application role
    any_id = rows["auth.login.succeeded"].id
    for statement in ("UPDATE audit_log SET action = 'x' WHERE id = :i", "DELETE FROM audit_log WHERE id = :i"):
        with pytest.raises(DBAPIError), UnitOfWork(system(tenant.company_id)) as uow:
            uow.session.execute(text(statement), {"i": any_id})
