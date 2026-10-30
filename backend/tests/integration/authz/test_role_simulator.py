"""Role simulator: effective permissions with sources, why-not explanations (PARITY LM-09, API-07, UI-94 backend)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.identity.fixtures import TEST_PASSWORD, Tenant, csrf_headers, login, login_admin, make_member

pytestmark = pytest.mark.db


def test_effective_permissions_with_sources(client: TestClient, tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    target = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login_admin(client, admin)
    # a personal grant and a personal revoke on top of the sales template
    for key, body in (
        ("pricing.cost.read", {"effect": "grant", "scope": "company", "reason": "Costing review"}),
        ("sales.quote.export", {"effect": "revoke", "reason": "No exports"}),
    ):
        r = client.put(f"/api/v1/identity/users/{target.user_id}/permission-overrides/{key}", json=body, headers=csrf_headers(client))
        assert r.status_code == 200, r.text

    sim = client.get("/api/v1/identity/access/effective", params={"user_id": str(target.user_id)})
    assert sim.status_code == 200, sim.text
    body = sim.json()
    assert body["subject"] == "member" and body["role_keys"] == ["sales"]
    granted = {g["key"]: g for g in body["granted"]}
    assert granted["sales.quote.read"]["scope"] == "own"
    assert granted["sales.quote.read"]["sources"][0]["kind"] == "role"
    assert any(s["kind"] == "employee_base" for s in granted["search.global.use"]["sources"])
    assert granted["pricing.cost.read"]["sources"] == [
        {"kind": "override_grant", "label": "Personal grant: Costing review", "role_key": None, "scope": "company", "expires_at": None}
    ]
    removed = {r["key"]: r for r in body["removed"]}
    assert "sales.quote.export" not in granted
    assert [s["kind"] for s in removed["sales.quote.export"]["sources"]] == ["role", "override_revoke"]

    why_not = client.get(
        "/api/v1/identity/access/check",
        params={"user_id": str(target.user_id), "permission_key": "sales.quote.read", "scope": "company"},
    ).json()
    assert why_not["allowed"] is False and why_not["scope"] == "own" and why_not["needed_scope"] == "company"
    assert any("wider" in r for r in why_not["reasons"])
    revoked = client.get(
        "/api/v1/identity/access/check", params={"user_id": str(target.user_id), "permission_key": "sales.quote.export"}
    ).json()
    assert revoked["allowed"] is False and any("Personal revoke" in r for r in revoked["reasons"])
    admin_key = client.get(
        "/api/v1/identity/access/check", params={"user_id": str(admin.user_id), "permission_key": "identity.user.manage", "scope": "company"}
    ).json()
    assert admin_key["allowed"] is True and any("authenticator" in r for r in admin_key["reasons"])

    # a role on its own
    roles = {r["key"]: r for r in client.get("/api/v1/identity/roles").json()["items"]}
    assert roles["sales"]["kind"] == "system_template" and roles["sales"]["member_count"] >= 1
    role_sim = client.get("/api/v1/identity/access/effective", params={"role_id": roles["operations"]["id"]}).json()
    assert role_sim["subject"] == "role" and any(g["key"] == "sales.quote.read" for g in role_sim["granted"])
    catalogue = client.get("/api/v1/identity/permissions").json()["items"]
    assert len(catalogue) >= 200 and any(p["key"] == "identity.user.manage" and p["requires_mfa"] for p in catalogue)


def test_simulator_needs_identity_read_keys(client: TestClient, tenant: Tenant) -> None:
    sales = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    login(client, sales.email)
    r = client.get("/api/v1/identity/access/effective", params={"user_id": str(sales.user_id)})
    assert r.status_code == 403
