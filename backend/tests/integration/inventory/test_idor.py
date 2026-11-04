"""IDOR matrix for the Slice-4 routes over HTTP (SEC-03 / PERM-23 for orders and inventory).

The world adds a second branch (FAC) with warehouse WH-FAC. Operations (Ravi) and the warehouse assistant (Kabir) are
scoped to HO, so WH-FAC and everything in it is invisible to them (404); sales see other owners' orders as 404.
Named warehouse-scope tests: an actor scoped to warehouse A cannot reserve, set an order's default warehouse, create
an order's challan, or issue a challan against warehouse B."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.modules.inventory import documents
from app.modules.inventory.schemas import AdjustmentCreate, AdjustmentLineIn, WarehouseCreate
from app.platform.authz.context import ActorContext
from app.platform.org.models import Branch
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld
from tests.integration.sales.http import api_app  # noqa: F401

pytestmark = pytest.mark.db
API = "/api/v1"
MEERA, NEHA, RAVI, KABIR, PRIYA = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.RAVI, keys.USERS.KABIR, keys.USERS.PRIYA


@pytest.fixture
def world_b(inv_world: InvWorld) -> InvWorld:
    """Branch FAC with warehouse WH-FAC (stock and an adjustment), invisible to HO-scoped personas."""
    w = inv_world
    with w.system() as uow:
        fac = Branch(id=uuid.uuid7(), company_id=w.company_id, branch_code="FAC", name="Factory")
        uow.add(fac)
        fac_id = fac.id
    with w.uow(PRIYA) as uow:
        wh = documents.create_warehouse(uow, WarehouseCreate(code="WH-FAC", name="Factory store", branch_id=fac_id))
        w.ctx.refs["WH_FAC"] = wh.id
        adj = documents.create_adjustment(uow, AdjustmentCreate(warehouse_id=wh.id, reason_code="found",
                                                                lines=[AdjustmentLineIn(product_id=w.ref("OAK_TRAY"), quantity=Decimal(5), direction="in")]))
        w.ctx.refs["ADJ_FAC"] = adj.id
    return w


@pytest.fixture
def client(api_app: FastAPI, world_b: InvWorld) -> Iterator[TestClient]:  # noqa: F811
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", RAVI)
        actor = world_b.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))
        return actor.with_(auth_strength="mfa", recent_auth_at=world_b.ctx.clock.now())

    api_app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(api_app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        api_app.dependency_overrides.clear()


def _as(persona: str) -> dict[str, str]:
    return {"x-test-persona": persona, "Idempotency-Key": str(uuid.uuid7())}


def _code(r: Any) -> tuple[int, str | None]:
    body = r.json() if r.headers.get("content-type", "").startswith("application/") else {}
    return r.status_code, body.get("code") if isinstance(body, dict) else None


def _confirmed_order(w: InvWorld) -> tuple[uuid.UUID, Any]:
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    return order_id, w.get_order(MEERA, order_id)


# ---- the named warehouse-scope tests (security fix) --------------------------------------------------------
def test_reserve_against_another_branch_warehouse_is_not_found(client: TestClient, world_b: InvWorld) -> None:
    order_id, _ = _confirmed_order(world_b)
    r = client.post(f"{API}/orders/sales-orders/{order_id}/reserve", json={"warehouse_id": str(world_b.ref("WH_FAC"))}, headers=_as(RAVI))
    assert _code(r) == (404, "not_found")
    assert world_b.summary("OAK_TRAY") == (Decimal(600), Decimal(0))  # nothing reserved anywhere
    ok = client.post(f"{API}/orders/sales-orders/{order_id}/reserve", json={}, headers=_as(RAVI))  # their own warehouse works
    assert ok.status_code == 200 and Decimal(ok.json()["outcomes"][0]["granted"]) == 240


def test_setting_another_branch_warehouse_as_order_default_is_not_found(client: TestClient, world_b: InvWorld) -> None:
    order_id, d = _confirmed_order(world_b)
    r = client.patch(f"{API}/orders/sales-orders/{order_id}", json={"expected_version": d.version, "default_warehouse_id": str(world_b.ref("WH_FAC"))},
                     headers=_as(RAVI))
    assert _code(r) == (404, "not_found")
    assert world_b.get_order(MEERA, order_id).default_warehouse is not None
    assert world_b.get_order(MEERA, order_id).default_warehouse.code == keys.WAREHOUSES.MAIN  # type: ignore[union-attr]


def test_order_challan_from_another_branch_warehouse_is_not_found(client: TestClient, world_b: InvWorld) -> None:
    order_id, d = _confirmed_order(world_b)
    r = client.post(f"{API}/orders/sales-orders/{order_id}/challans",
                    json={"quantities": {str(d.lines[0].id): "10"}, "warehouse_id": str(world_b.ref("WH_FAC"))}, headers=_as(RAVI))
    assert _code(r) == (404, "not_found")


def test_issuing_a_challan_from_another_branch_warehouse_is_not_found(client: TestClient, world_b: InvWorld) -> None:
    w = world_b
    draft = w.new_challan(RAVI, ("OAK_TRAY", "5"), party_id=w.ref("NORDHAUS"), source_warehouse_id=w.ref("WH_FAC"))
    r = client.post(f"{API}/challans/challans/{draft.id}/transitions", json={"action": "issue", "expected_version": draft.version}, headers=_as(RAVI))
    assert _code(r) == (404, "not_found")
    assert w.challan(RAVI, draft.id).status == "draft" and w.postings("challan", draft.id) == 0


# ---- the route matrix ----------------------------------------------------------------------------------------
def test_inventory_documents_and_stock_of_an_invisible_warehouse(client: TestClient, world_b: InvWorld) -> None:
    w = world_b
    fac, adj = w.ref("WH_FAC"), w.ref("ADJ_FAC")
    for persona in (RAVI, KABIR):
        assert _code(client.get(f"{API}/inventory/adjustments/{adj}", headers=_as(persona)))[0] == 404
        assert _code(client.post(f"{API}/inventory/adjustments/{adj}/submit", json={"expected_version": 1}, headers=_as(persona)))[0] in (403, 404)
        assert _code(client.get(f"{API}/inventory/availability", params={"product_id": str(w.ref("OAK_TRAY")), "warehouse_id": str(fac)},
                                headers=_as(persona)))[0] == 404
        assert client.get(f"{API}/inventory/stock", params={"warehouse_id": str(fac)}, headers=_as(persona)).json()["items"] == []
        codes = [wh["code"] for wh in client.get(f"{API}/inventory/warehouses", headers=_as(persona)).json()]
        assert codes == [keys.WAREHOUSES.MAIN]
    # company-scoped readers (management) see both warehouses
    codes = [wh["code"] for wh in client.get(f"{API}/inventory/warehouses", headers=_as(keys.USERS.SAHIL)).json()]
    assert codes == ["WH-FAC", keys.WAREHOUSES.MAIN]
    # writes beyond the key's scope: Ravi cannot approve an adjustment in FAC (404), sales cannot create one (403)
    r = client.post(f"{API}/inventory/adjustments", headers=_as(MEERA), json={"warehouse_id": str(w.warehouse_id), "reason_code": "found",
                                                                               "lines": [{"product_id": str(w.ref("OAK_TRAY")), "quantity": "1", "direction": "in"}]})
    assert _code(r) == (403, "permission_denied")
    # unknown ids are 404 on every detail route
    for path in ("adjustments", "opening-batches", "transfers", "stock-counts", "pick-lists", "postings"):
        assert client.get(f"{API}/inventory/{path}/{uuid.uuid7()}", headers=_as(RAVI)).status_code == 404


def test_orders_are_scoped_by_owner_and_branch(client: TestClient, world_b: InvWorld) -> None:
    order_id, d = _confirmed_order(world_b)
    for path in ("", "/impact-preview"):
        assert client.get(f"{API}/orders/sales-orders/{order_id}{path}", headers=_as(NEHA)).status_code == 404
    assert _code(client.post(f"{API}/orders/sales-orders/{order_id}/reserve", json={}, headers=_as(NEHA)))[0] == 404
    assert _code(client.post(f"{API}/orders/sales-orders/{order_id}/transitions", json={"action": "hold", "expected_version": d.version,
                                                                                         "reason_code": "credit"}, headers=_as(NEHA)))[0] == 404
    listed = client.get(f"{API}/orders/sales-orders", headers=_as(NEHA)).json()
    assert all(item["id"] != str(order_id) for item in listed["items"])
    # the warehouse assistant reads stock but has no order rights: 403 on the order routes
    assert client.get(f"{API}/orders/sales-orders/{order_id}", headers=_as(KABIR)).status_code == 403
    # conversion of someone else's quote: 404
    quote_id = world_b.won_quote(MEERA, "BERG", ("OAK_TRAY", "240"))
    assert client.post(f"{API}/orders/sales-orders/convert", json={"quote_id": str(quote_id)}, headers=_as(NEHA)).status_code == 404
    r = client.post(f"{API}/orders/sales-orders/convert", json={"quote_id": str(quote_id)}, headers=_as(MEERA))
    again = client.post(f"{API}/orders/sales-orders/convert", json={"quote_id": str(quote_id)}, headers=_as(MEERA))
    assert (r.status_code, r.json()["created"], again.status_code, again.json()["created"]) == (201, True, 200, False)
    assert r.json()["order"]["id"] == again.json()["order"]["id"]
