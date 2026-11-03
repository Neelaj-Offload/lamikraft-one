"""Deactivation and reactivation (PARITY LM-06, LM-07, API-05, FG-USR-04): never a hard delete, sessions and links
end at once, attribution kept as "Name (inactive)", last-admin guard, no self-deactivation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.events.models import DomainEvent
from app.platform.identity.credential_models import Invitation
from app.platform.identity.models import AppUser, Membership
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


def test_deactivation_keeps_attribution_and_revokes_sessions(client: TestClient, tenant: Tenant, demo_outbox) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Meera")
    neha = make_member(tenant, ["sales"], name="Neha")
    login_admin(client, admin)
    m = TestClient(client.app, base_url="http://testserver")
    assert login(m, meera.email).status_code == 200

    r = client.post(
        f"{USERS}/{meera.user_id}/deactivation",
        json={"reason": "Left the company", "reassign_to_user_id": str(neha.user_id)},
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "deactivated" and body["display_name"] == "Meera (inactive)"
    assert body["deactivation_reason"] == "Left the company" and body["capabilities"]["reactivate"]["allowed"]
    assert m.get("/api/v1/identity/me").status_code == 401  # the next request is refused
    assert login(TestClient(client.app, base_url="http://testserver"), meera.email).status_code == 401
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert uow.session.get(AppUser, meera.user_id) is not None  # never hard-deleted
        event = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "identity.membership.deactivated")).one()
    assert event.payload["reassign_to_membership_id"] == str(neha.membership_id)
    listed = {i["user_id"]: i for i in client.get(USERS).json()["items"]}
    assert listed[str(meera.user_id)]["display_name"] == "Meera (inactive)"

    back = client.post(f"{USERS}/{meera.user_id}/reactivation", headers=csrf_headers(client))
    assert back.status_code == 200 and back.json()["status"] == "active" and back.json()["roles"][0]["key"] == "sales"
    assert login(TestClient(client.app, base_url="http://testserver"), meera.email).status_code == 200
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "identity.membership.reactivated")).first()


def test_last_admin_guard_and_no_self_deactivation(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    own = client.post(f"{USERS}/{admin.user_id}/deactivation", json={"reason": "x"}, headers=csrf_headers(client))
    assert own.status_code == 403 and own.json()["code"] == "self_access_change"
    # the only other admin cannot be removed by a second admin if that leaves nobody: here two admins exist
    second = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    assert client.post(f"{USERS}/{second.user_id}/deactivation", json={"reason": "x"}, headers=csrf_headers(client)).status_code == 200
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert uow.session.get(Membership, second.membership_id).status == "deactivated"  # type: ignore[union-attr]
    # the last active holder of role management can never be deactivated, even by the system
    from app.core.errors import Conflict
    from app.platform.identity import provisioning

    with pytest.raises(Conflict) as exc, UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.deactivate_membership(uow, admin.membership_id, reason="x")
    assert exc.value.code == "last_admin"


def test_deactivating_an_invited_member_closes_the_invitation(client: TestClient, tenant: Tenant, demo_outbox) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    login_admin(client, admin)
    inv = client.post(
        "/api/v1/identity/invitations",
        json={"email": "late@example.test", "display_name": "Late", "role_keys": ["sales"]},
        headers=csrf_headers(client),
    ).json()
    user_id = inv["invitation"]["user_id"]
    assert client.post(f"{USERS}/{user_id}/deactivation", json={"reason": "Offer withdrawn"}, headers=csrf_headers(client)).status_code == 200
    with UnitOfWork(system(tenant.company_id)) as uow:
        row = uow.session.get(Invitation, inv["invitation"]["id"])
    assert row is not None and row.revoked_at is not None and row.token_hash is None
