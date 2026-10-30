"""Delegation (time-bounded, scoped, audited; never adds keys), leave and access requests (platform-2 item 3)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.authz.policy import ResourcePolicy, scope_clause
from app.platform.events.models import DomainEvent
from app.platform.identity import delegation as delegation_service
from app.platform.identity.models import Membership
from app.platform.uow import UnitOfWork
from app.platform.sources import read as read_source
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


def _client(app, member) -> TestClient:  # type: ignore[no-untyped-def]
    c = TestClient(app, base_url="http://testserver")
    assert login(c, member.email).status_code == 200
    return c


def _events(tenant: Tenant, prefix: str) -> list[str]:
    with UnitOfWork(system(tenant.company_id)) as uow:
        return [
            e.event_type
            for e in uow.session.scalars(
                select(DomainEvent).where(DomainEvent.company_id == tenant.company_id, DomainEvent.event_type.like(f"{prefix}%")).order_by(DomainEvent.seq)
            )
        ]


def test_delegation_never_adds_keys_and_extends_reach(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Meera")
    neha = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Neha")
    kabir = make_member(tenant, ["warehouse"], password=TEST_PASSWORD, name="Kabir")
    m = _client(client.app, meera)
    now = frozen_clock.now()
    body = {
        "delegate_user_id": str(neha.user_id),
        "permission_keys": ["sales.quote.read", "sales.quote.update"],
        "ends_at": (now + timedelta(days=5)).isoformat(),
        "reason": "leave",
    }
    r = m.post("/api/v1/identity/delegations", json=body, headers=csrf_headers(m))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "active" and r.json()["delegate_name"] == "Neha"

    # Neha (own scope) now reaches Meera's records for those keys; her keys themselves are unchanged
    from app.platform.identity.actors import actor_for

    neha_ctx = actor_for(tenant.company_id, neha.user_id)
    assert neha_ctx is not None
    assert neha_ctx.delegated["sales.quote.read"] == frozenset({meera.user_id})
    assert neha_ctx.permissions["sales.quote.read"].label == "own"
    assert "sales.quote.delete" not in neha_ctx.permissions
    fake = ResourcePolicy(resource_type="test.thing", model=Membership, permission_prefix="sales.quote", owner_columns=("user_id",))
    with UnitOfWork(neha_ctx) as uow:
        visible = set(uow.session.scalars(select(Membership.user_id).where(scope_clause(neha_ctx, fake, "read"))))
    assert visible == {neha.user_id, meera.user_id}

    # a delegate without the key gains nothing: Kabir (warehouse) holds no quote keys
    r2 = m.post("/api/v1/identity/delegations", json={**body, "delegate_user_id": str(kabir.user_id)}, headers=csrf_headers(m))
    assert r2.status_code == 201
    kabir_ctx = actor_for(tenant.company_id, kabir.user_id)
    assert kabir_ctx is not None and "sales.quote.read" not in kabir_ctx.delegated and "sales.quote.read" not in kabir_ctx.permissions

    # validation: non-delegable keys, keys the delegator lacks, more than 90 days, self
    bad = m.post("/api/v1/identity/delegations", json={**body, "permission_keys": ["sales.quote.delete"]}, headers=csrf_headers(m))
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "not_delegable"
    long = m.post("/api/v1/identity/delegations", json={**body, "ends_at": (now + timedelta(days=91)).isoformat()}, headers=csrf_headers(m))
    assert long.status_code == 422
    selfie = m.post("/api/v1/identity/delegations", json={**body, "delegate_user_id": str(meera.user_id)}, headers=csrf_headers(m))
    assert selfie.status_code == 422

    # the delegate sees it; a third person cannot cancel it; the delegator can
    n = _client(client.app, neha)
    listed = n.get("/api/v1/identity/delegations").json()["items"]
    assert [d["delegator_name"] for d in listed] == ["Meera"] and listed[0]["capabilities"]["cancel"]["allowed"] is False
    k = _client(client.app, kabir)
    assert k.post(f"/api/v1/identity/delegations/{r.json()['id']}/cancel", headers=csrf_headers(k)).status_code == 404
    cancelled = m.post(f"/api/v1/identity/delegations/{r.json()['id']}/cancel", headers=csrf_headers(m))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    neha_after = actor_for(tenant.company_id, neha.user_id)
    assert neha_after is not None and not neha_after.delegated
    assert _events(tenant, "identity.delegation.") == [
        "identity.delegation.created",
        "identity.delegation.started",
        "identity.delegation.created",
        "identity.delegation.started",
        "identity.delegation.cancelled",
    ]
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert uow.session.scalars(select(AuditLog).where(AuditLog.action == "identity.delegation.created")).first()


def test_scheduled_delegation_starts_and_ends_on_time(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    neha = make_member(tenant, ["sales"])
    m = _client(client.app, meera)
    now = frozen_clock.now()
    r = m.post(
        "/api/v1/identity/delegations",
        json={
            "delegate_user_id": str(neha.user_id),
            "permission_keys": ["sales.quote.read"],
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=2)).isoformat(),
            "reason": "travel",
        },
        headers=csrf_headers(m),
    )
    assert r.json()["status"] == "scheduled"
    from app.platform.identity.actors import actor_for

    assert not actor_for(tenant.company_id, neha.user_id).delegated  # type: ignore[union-attr]
    frozen_clock.advance(days=1, minutes=1)
    assert actor_for(tenant.company_id, neha.user_id).delegated  # type: ignore[union-attr]  # cache expired at the boundary
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert delegation_service.notify_boundaries(uow) == {"started": 1, "ended": 0}
    frozen_clock.advance(days=1)
    assert not actor_for(tenant.company_id, neha.user_id).delegated  # type: ignore[union-attr]
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert delegation_service.notify_boundaries(uow) == {"started": 0, "ended": 1}
        assert delegation_service.notify_boundaries(uow) == {"started": 0, "ended": 0}  # once each


def test_leave_request_approval_cancel_and_reader(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Meera")
    neha = make_member(tenant, ["sales"], password=TEST_PASSWORD, name="Neha")
    m = _client(client.app, meera)
    today = frozen_clock.now().date()
    r = m.post(
        "/api/v1/identity/absences",
        json={"starts_on": (today + timedelta(days=3)).isoformat(), "ends_on": (today + timedelta(days=7)).isoformat(), "cover_user_id": str(neha.user_id), "note": "Family visit"},
        headers=csrf_headers(m),
    )
    assert r.status_code == 201, r.text
    absence = r.json()
    assert absence["status"] == "requested" and absence["cover_name"] == "Neha"
    assert absence["capabilities"]["decide"]["allowed"] is False  # never your own
    overlap = m.post("/api/v1/identity/absences", json={"starts_on": (today + timedelta(days=5)).isoformat(), "ends_on": (today + timedelta(days=9)).isoformat()}, headers=csrf_headers(m))
    assert overlap.status_code == 409
    assert m.post(f"/api/v1/identity/absences/{absence['id']}/decision", json={"expected_version": 1, "decision": "approve"}, headers=csrf_headers(m)).status_code == 403
    n = _client(client.app, neha)
    assert n.post(f"/api/v1/identity/absences/{absence['id']}/decision", json={"expected_version": 1, "decision": "approve"}, headers=csrf_headers(n)).status_code == 404

    a = TestClient(client.app, base_url="http://testserver")
    login_admin(a, admin)
    team = a.get("/api/v1/identity/absences", params={"scope": "team"}).json()["items"]
    assert [x["display_name"] for x in team] == ["Meera"]
    ok = a.post(f"/api/v1/identity/absences/{absence['id']}/decision", json={"expected_version": absence["version"], "decision": "approve"}, headers=csrf_headers(a))
    assert ok.status_code == 200, ok.text
    # identity.absence.approve is admin-only in the catalogue: admin decides
    assert ok.json()["status"] == "approved"
    with UnitOfWork(system(tenant.company_id)) as uow:
        facts = read_source(uow, "identity.absence", ok.json()["id"])
    assert facts is not None and facts.facts["cover_user_id"] == str(neha.user_id)
    assert m.post(f"/api/v1/identity/absences/{absence['id']}/cancel", headers=csrf_headers(m)).json()["status"] == "cancelled"
    assert _events(tenant, "identity.absence.") == ["identity.absence.requested", "identity.absence.approved", "identity.absence.cancelled"]
    past = m.post("/api/v1/identity/absences", json={"starts_on": date(2020, 1, 1).isoformat(), "ends_on": date(2020, 1, 2).isoformat()}, headers=csrf_headers(m))
    assert past.status_code == 422


def test_access_request_grant_with_expiry(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    meera = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    m = _client(client.app, meera)
    asked = m.post(
        "/api/v1/identity/access-requests",
        json={"permission_key": "pricing.cost.read", "scope": "company", "reason": "Margin review for Nordhaus", "duration_days": 7},
        headers=csrf_headers(m),
    )
    assert asked.status_code == 201, asked.text
    req = asked.json()
    dup = m.post("/api/v1/identity/access-requests", json={"permission_key": "pricing.cost.read", "scope": "company", "reason": "again"}, headers=csrf_headers(m))
    assert dup.status_code == 409 and dup.json()["code"] == "request_pending"
    assert m.post(f"/api/v1/identity/access-requests/{req['id']}/decision", json={"expected_version": 1, "decision": "approve"}, headers=csrf_headers(m)).status_code == 403
    assert m.get("/api/v1/identity/access-requests", params={"scope": "all"}).status_code == 403

    a = TestClient(client.app, base_url="http://testserver")
    login_admin(a, admin)
    pending = a.get("/api/v1/identity/access-requests", params={"scope": "all", "status": "pending"}).json()["items"]
    assert [p["id"] for p in pending] == [req["id"]]
    ok = a.post(
        f"/api/v1/identity/access-requests/{req['id']}/decision",
        json={"expected_version": req["version"], "decision": "approve", "duration_days": 3, "note": "OK for this week"},
        headers=csrf_headers(a),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    perms = {p["key"]: p["scope"] for p in m.get("/api/v1/identity/me").json()["permissions"]}
    assert perms["pricing.cost.read"] == "company"
    frozen_clock.advance(days=3, minutes=1)
    m2 = _client(client.app, meera)
    assert "pricing.cost.read" not in {p["key"] for p in m2.get("/api/v1/identity/me").json()["permissions"]}
    assert _events(tenant, "identity.access_request.") == ["identity.access_request.submitted", "identity.access_request.decided"]

    # withdraw and reject paths
    r2 = m2.post("/api/v1/identity/access-requests", json={"permission_key": "sales.quote.read", "scope": "company", "reason": "Cover the desk"}, headers=csrf_headers(m2)).json()
    assert m2.post(f"/api/v1/identity/access-requests/{r2['id']}/withdrawal", headers=csrf_headers(m2)).json()["status"] == "withdrawn"
    already = m2.post("/api/v1/identity/access-requests", json={"permission_key": "sales.quote.read", "scope": "own", "reason": "x"}, headers=csrf_headers(m2))
    assert already.status_code == 409 and already.json()["code"] == "already_granted"
