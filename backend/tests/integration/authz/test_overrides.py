"""Per-user permission overrides over HTTP (PARITY LM-08, API-08, API-09; permissions.md §6-§7)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.events.models import DomainEvent
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import (
    TEST_PASSWORD,
    Tenant,
    csrf_headers,
    login,
    make_member,
    system,
)

pytestmark = pytest.mark.db


def _url(user_id: uuid.UUID, key: str | None = None) -> str:
    base = f"/api/v1/identity/users/{user_id}/permission-overrides"
    return f"{base}/{key}" if key else base


def _epoch(tenant: Tenant) -> int:
    with UnitOfWork(system(tenant.company_id)) as uow:
        return int(uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id)) or 0)


def _override_events(tenant: Tenant) -> list[DomainEvent]:
    with UnitOfWork(system(tenant.company_id)) as uow:
        return list(
            uow.session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == "identity.permission_override.changed", DomainEvent.company_id == tenant.company_id)
                .order_by(DomainEvent.seq)
            )
        )


def test_grant_and_revoke_with_reason_and_epoch_bump(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    target = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, admin.email).status_code == 200

    listed = client.get(_url(target.user_id))
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"user_id": str(target.user_id), "membership_id": str(target.membership_id), "items": []}

    epoch = _epoch(tenant)
    grant = {"effect": "grant", "scope": "company", "reason": "Covers the export desk"}
    r = client.put(_url(target.user_id, "sales.quote.read"), json=grant, headers=csrf_headers(client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["permission_key"], body["effect"], body["scope"], body["reason"]) == ("sales.quote.read", "grant", "company", grant["reason"])
    assert body["in_effect"] is True and body["created_by"] == str(admin.user_id)
    assert _epoch(tenant) == epoch + 1
    # repeating the same PUT changes nothing
    again = client.put(_url(target.user_id, "sales.quote.read"), json=grant, headers=csrf_headers(client))
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    assert _epoch(tenant) == epoch + 1

    revoke = {"effect": "revoke", "reason": "Exports go through the manager"}
    r = client.put(_url(target.user_id, "sales.quote.export"), json=revoke, headers=csrf_headers(client))
    assert r.status_code == 200 and r.json()["scope"] is None
    assert _epoch(tenant) == epoch + 2
    items = {i["permission_key"]: i for i in client.get(_url(target.user_id)).json()["items"]}
    assert set(items) == {"sales.quote.read", "sales.quote.export"}

    # the member sees the effect on the next request
    member_client = TestClient(client.app, base_url="http://testserver")
    assert login(member_client, target.email).status_code == 200
    perms = {p["key"]: p["scope"] for p in member_client.get("/api/v1/identity/me").json()["permissions"]}
    assert perms["sales.quote.read"] == "company" and "sales.quote.export" not in perms

    assert client.delete(_url(target.user_id, "sales.quote.export"), headers=csrf_headers(client)).status_code == 204
    assert _epoch(tenant) == epoch + 3
    missing = client.delete(_url(target.user_id, "sales.quote.export"), headers=csrf_headers(client))
    assert missing.status_code == 404
    perms = {p["key"] for p in member_client.get("/api/v1/identity/me").json()["permissions"]}
    assert "sales.quote.export" in perms  # the sales role grants it again

    events = _override_events(tenant)
    assert [(e.payload["permission_key"], e.payload["effect"], e.payload["archived"]) for e in events] == [
        ("sales.quote.read", "grant", False),
        ("sales.quote.export", "revoke", False),
        ("sales.quote.export", "revoke", True),
    ]


def test_override_api_validation_and_authority(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    target = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, admin.email).status_code == 200
    headers = csrf_headers(client)
    no_scope = client.put(_url(target.user_id, "sales.quote.read"), json={"effect": "grant", "reason": "x"}, headers=headers)
    assert no_scope.status_code == 422
    no_reason = client.put(_url(target.user_id, "sales.quote.read"), json={"effect": "revoke", "reason": ""}, headers=headers)
    assert no_reason.status_code == 422
    unknown_key = client.put(_url(target.user_id, "sales.quote.fly"), json={"effect": "revoke", "reason": "x"}, headers=headers)
    assert unknown_key.status_code == 422
    stranger = client.put(_url(uuid.uuid4(), "sales.quote.read"), json={"effect": "revoke", "reason": "x"}, headers=headers)
    assert stranger.status_code == 404
    own = client.put(_url(admin.user_id, "sales.quote.read"), json={"effect": "revoke", "reason": "x"}, headers=headers)
    assert own.status_code == 403 and own.json()["code"] == "self_access_change"

    sales = TestClient(client.app, base_url="http://testserver")
    assert login(sales, target.email).status_code == 200
    denied = sales.put(_url(admin.user_id, "sales.quote.read"), json={"effect": "revoke", "reason": "x"}, headers=csrf_headers(sales))
    assert denied.status_code == 403
    assert sales.get(_url(admin.user_id)).status_code == 403


def test_override_changes_need_a_recent_password_sign_in(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    target = make_member(tenant, ["sales"])
    assert login(client, admin.email).status_code == 200
    frozen_clock.advance(minutes=11)
    body = {"effect": "revoke", "reason": "No exports"}
    r = client.put(_url(target.user_id, "sales.quote.export"), json=body, headers=csrf_headers(client))
    assert r.status_code == 401 and r.json()["code"] == "reauth_required"
    assert client.get(_url(target.user_id)).status_code == 200  # reading needs no step-up
    # signing in again with the password (a live session: the CSRF token is needed) refreshes recent authentication
    again = client.post("/api/v1/identity/session", json={"email": admin.email, "password": TEST_PASSWORD}, headers=csrf_headers(client))
    assert again.status_code == 200
    r = client.put(_url(target.user_id, "sales.quote.export"), json=body, headers=csrf_headers(client))
    assert r.status_code == 200, r.text
