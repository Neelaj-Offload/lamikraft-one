"""Custom roles: inheritance, deny, validation and anti-escalation (PARITY PERM-16, FG-USR-02, SEC-07 role part)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.events.models import DomainEvent
from app.platform.identity import provisioning
from app.platform.identity.models import Role
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    login,
    login_admin,
    make_member,
    system,
)

pytestmark = pytest.mark.db

ROLES = "/api/v1/identity/roles"


def _role_id(tenant: Tenant, key: str) -> str:
    with UnitOfWork(system(tenant.company_id)) as uow:
        return str(uow.session.scalar(select(Role.id).where(Role.company_id == tenant.company_id, Role.role_key == key)))


def _create(client: TestClient, body: dict):  # type: ignore[no-untyped-def,type-arg]
    return client.post(ROLES, json=body, headers=csrf_headers(client))


def test_unknown_key_scope_cycle_and_escalation_rejected(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    sales_id = _role_id(tenant, "sales")

    assert _create(client, {"key": "bad", "name": "Bad", "entries": [{"key": "nope.thing.read", "scope": "own"}]}).status_code == 422
    bad_scope = _create(client, {"key": "bad", "name": "Bad", "entries": [{"key": "identity.user.read", "scope": "own"}]})
    assert bad_scope.status_code == 422 and bad_scope.json()["errors"][0]["code"] == "scope_not_allowed"
    assert _create(client, {"key": "Bad Key", "name": "Bad"}).status_code == 422

    # a chain: senior_sales -> sales; a deny removes an inherited key
    senior = _create(
        client,
        {
            "key": "senior_sales",
            "name": "Senior sales",
            "inherits_role_id": sales_id,
            "entries": [
                {"key": "sales.quote.read", "scope": "company"},
                {"key": "sales.quote.export", "effect": "deny"},
            ],
        },
    )
    assert senior.status_code == 201, senior.text
    detail = senior.json()
    effective = {e["key"]: e for e in detail["effective"]}
    assert effective["sales.quote.read"]["scope"] == "company"
    assert "sales.quote.export" not in effective
    assert effective["sales.quote.create"]["sources"][0]["kind"] == "inherited"
    assert [r["key"] for r in detail["chain"]] == ["sales", "senior_sales"]

    # cycles and depth
    lead = _create(client, {"key": "sales_lead", "name": "Lead", "inherits_role_id": detail["role"]["id"]}).json()
    cyc = client.patch(
        f"{ROLES}/{detail['role']['id']}",
        json={"expected_version": detail["role"]["version"], "inherits_role_id": lead["role"]["id"]},
        headers=csrf_headers(client),
    )
    assert cyc.status_code == 422 and cyc.json()["errors"][0]["code"] == "inheritance_cycle"
    third = _create(client, {"key": "lvl3", "name": "L3", "inherits_role_id": lead["role"]["id"]}).json()
    too_deep = _create(client, {"key": "lvl4", "name": "L4", "inherits_role_id": third["role"]["id"]})
    assert too_deep.status_code == 422 and too_deep.json()["errors"][0]["code"] == "inheritance_too_deep"

    # templates are immutable; a stale version is a 409
    tpl = client.patch(f"{ROLES}/{sales_id}", json={"expected_version": 1, "name": "x"}, headers=csrf_headers(client))
    assert tpl.status_code == 409 and tpl.json()["code"] == "role_immutable"
    stale = client.patch(f"{ROLES}/{detail['role']['id']}", json={"expected_version": 99, "name": "x"}, headers=csrf_headers(client))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"

    # anti-escalation: a role manager cannot create a role granting more than they hold
    role_admin = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(uow, role_admin.membership_id, permission_key="identity.role.manage", effect="grant", reason="test", scope="company")
    other = TestClient(client.app, base_url="http://testserver")
    assert login(other, role_admin.email).json()["stage"] == "mfa_enrollment_required"
    from tests.integration.identity.fixtures import enrol_mfa

    enrol_mfa(other)
    esc = _create(other, {"key": "escalate", "name": "Esc", "entries": [{"key": "sales.quote.delete", "scope": "company"}]})
    assert esc.status_code == 403 and esc.json()["code"] == "permission_escalation"


def test_resolution_applies_inheritance_deny_and_events(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    sales_id = _role_id(tenant, "sales")
    role = _create(
        client,
        {"key": "quiet_sales", "name": "Quiet sales", "inherits_role_id": sales_id, "entries": [{"key": "sales.quote.export", "effect": "deny"}]},
    ).json()
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    r = client.put(f"/api/v1/identity/users/{member.user_id}/roles", json={"role_keys": ["quiet_sales"]}, headers=csrf_headers(client))
    assert r.status_code == 200, r.text
    m = TestClient(client.app, base_url="http://testserver")
    login(m, member.email)
    perms = {p["key"]: p["scope"] for p in m.get("/api/v1/identity/me").json()["permissions"]}
    assert "sales.quote.export" not in perms and perms["sales.quote.read"] == "own"

    # archiving is blocked while assigned
    blocked = client.post(f"{ROLES}/{role['role']['id']}/archive", headers=csrf_headers(client))
    assert blocked.status_code == 409 and blocked.json()["code"] == "role_in_use"
    with UnitOfWork(system(tenant.company_id)) as uow:
        types = [e.event_type for e in uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == tenant.company_id))]
        audits = {a.action: a for a in uow.session.scalars(select(AuditLog).where(AuditLog.company_id == tenant.company_id))}
    assert "identity.role.created" in types and "identity.membership.access_changed" in types
    assert audits["identity.membership.roles_changed"].changes == {"roles": {"from": ["sales"], "to": ["quiet_sales"]}}
    assert audits["identity.role.created"].changes["entries"]["to"] == {"sales.quote.export": "deny:company"}


def test_role_reads_and_writes_need_identity_keys(client: TestClient, tenant: Tenant) -> None:
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login(client, sales.email)
    assert client.get(ROLES).status_code == 403
    assert client.get("/api/v1/identity/permissions").status_code == 403
    assert _create(client, {"key": "x_role", "name": "X"}).status_code == 403
