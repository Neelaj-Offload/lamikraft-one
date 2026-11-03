"""User administration: list, detail, edit, roles (PARITY LM-04, API-04, API-05 update part, PERM-11, FG-USR-01)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
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

USERS = "/api/v1/identity/users"


def test_list_create_update_users(client: TestClient, tenant: Tenant, demo_outbox) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD, name="Priya Admin")
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Meera Sales")
    make_member(tenant, ["operations"], name="Ravi Ops")
    login_admin(client, admin)

    invited = client.post(
        "/api/v1/identity/invitations",
        json={"email": "new.hire@example.test", "display_name": "New Hire", "role_keys": ["sales"]},
        headers=csrf_headers(client),
    )
    assert invited.status_code == 201

    page = client.get(USERS, params={"limit": 2})
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 4 and len(body["items"]) == 2 and body["limit"] == 2
    # filters apply before paging
    sales = client.get(USERS, params={"role": "sales"}).json()
    assert {i["display_name"] for i in sales["items"]} == {"Meera Sales", "New Hire"}
    assert client.get(USERS, params={"status": "invited"}).json()["total"] == 1
    assert [i["display_name"] for i in client.get(USERS, params={"q": "meera"}).json()["items"]] == ["Meera Sales"]
    assert client.get(USERS, params={"q": "%"}).json()["total"] == 0  # LIKE metacharacters are literal
    admin_row = next(i for i in body["items"] + client.get(USERS, params={"offset": 2}).json()["items"] if i["user_id"] == str(admin.user_id))
    assert admin_row["mfa_enrolled"] is True

    detail = client.get(f"{USERS}/{meera.user_id}").json()
    assert detail["roles"] == [{"key": "sales", "name": "Sales"}] and detail["capabilities"]["deactivate"]["allowed"]
    assert detail["mfa_required"] is False and detail["is_self"] is False
    own = client.get(f"{USERS}/{admin.user_id}").json()
    assert own["capabilities"]["deactivate"] == {"allowed": False, "reason_code": "self_access_change"}

    edited = client.patch(
        f"{USERS}/{meera.user_id}",
        json={"expected_version": detail["version"], "display_name": "Meera K", "job_title": "Export sales"},
        headers=csrf_headers(client),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["display_name"] == "Meera K" and edited.json()["version"] == detail["version"] + 1
    stale = client.patch(f"{USERS}/{meera.user_id}", json={"expected_version": detail["version"], "job_title": "x"}, headers=csrf_headers(client))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"

    roles = client.put(f"{USERS}/{meera.user_id}/roles", json={"role_keys": ["sales", "operations"]}, headers=csrf_headers(client))
    assert roles.status_code == 200 and {r["key"] for r in roles.json()["roles"]} == {"sales", "operations"}
    assert client.put(f"{USERS}/{admin.user_id}/roles", json={"role_keys": ["sales"]}, headers=csrf_headers(client)).status_code == 403

    with UnitOfWork(system(tenant.company_id)) as uow:
        audit = {a.action: a.changes for a in uow.session.scalars(select(AuditLog).where(AuditLog.resource_id == meera.membership_id))}
    assert audit["identity.membership.updated"]["display_name"] == {"from": "Meera Sales", "to": "Meera K"}
    assert audit["identity.membership.roles_changed"] == {"roles": {"from": ["sales"], "to": ["operations", "sales"]}}


def test_user_admin_requires_manage_keys(client: TestClient, tenant: Tenant) -> None:
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    other = make_member(tenant, ["sales"])
    login(client, sales.email)
    assert client.get(USERS).status_code == 403
    assert client.get(f"{USERS}/{other.user_id}").status_code == 403
    assert client.patch(f"{USERS}/{other.user_id}", json={"expected_version": 1, "job_title": "x"}, headers=csrf_headers(client)).status_code == 403
    assert client.post(f"{USERS}/{other.user_id}/deactivation", json={"reason": "x"}, headers=csrf_headers(client)).status_code == 403


def test_email_normalised_unique(client: TestClient, tenant: Tenant, demo_outbox) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    body = {"email": "Mixed.Case@Example.TEST", "display_name": "Mixed", "role_keys": ["sales"]}
    assert client.post("/api/v1/identity/invitations", json=body, headers=csrf_headers(client)).status_code == 201
    again = client.post("/api/v1/identity/invitations", json={**body, "email": "MIXED.case@example.test"}, headers=csrf_headers(client))
    assert again.status_code == 409 and again.json()["code"] == "already_member"
