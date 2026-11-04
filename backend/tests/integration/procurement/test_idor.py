"""IDOR matrix for the procurement, quality and logistics routes over HTTP (SEC-03 / PERM-23).

The world adds branch FAC with warehouse WH-FAC and a test-local operations persona **Omar** scoped to FAC. Ravi
(operations, HO) never sees FAC documents or warehouses; Omar never sees HO ones; sales see logistics only for their
own orders. Every entry point that names a warehouse, location, vendor, order, challan, packing list or document is
checked: an id outside the actor's scope is a 404 (never a leak of existence), a visible record with a forbidden
action is a 403, and an id that belongs to a different parent is a 422."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from types import MappingProxyType
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.modules.inventory import documents
from app.modules.inventory.schemas import BinCreate, WarehouseCreate
from app.modules.orders import service as orders
from app.modules.orders.schemas import ChallanFromOrder
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.org.models import Branch
from app.seed.world import keys
from tests.integration.catalogue import world as catalogue_world
from tests.integration.procurement.world import ANANYA, KABIR, MEERA, NEHA, PRIYA, RAVI, SAHIL, TARA, PqlWorld
from tests.integration.sales.http import api_app  # noqa: F401
from tests.support import create_user

pytestmark = pytest.mark.db
API = "/api/v1"
OMAR = "OMAR"
#: purchasing without party visibility (a vendor id it guesses must be a 404, not a lookup)
BLIND = "BLIND"


@pytest.fixture
def world_b(pql_world: PqlWorld) -> PqlWorld:
    w = pql_world
    with w.system() as uow:
        fac = Branch(id=uuid.uuid7(), company_id=w.company_id, branch_code="FAC", name="Factory")
        uow.add(fac)
        fac_id = fac.id
    for key, name, template, branches, perms in (
        (OMAR, "Omar Siddiqui", "operations", {fac_id}, None),
        (BLIND, "Blind Buyer", "procurement", {w.branch_id}, {"parties.party.read": Scope.OWN}),
    ):
        user_id = create_user(w.company_id, name)
        grants = dict(template_grants()[template])
        grants.update(perms or {})
        actor = ActorContext(actor_type="user", company_id=w.company_id, user_id=user_id, display_name=name,
                             branch_ids=frozenset(branches), permissions=MappingProxyType(grants), channel="test")
        w.actors[key], w.ctx.refs[key] = actor, user_id
        catalogue_world._PERSONAS[(w.company_id, user_id)] = actor
    with w.uow(PRIYA) as uow:
        wh = documents.create_warehouse(uow, WarehouseCreate(code="WH-FAC", name="Factory store", branch_id=fac_id))
        documents.create_bin(uow, wh.id, BinCreate(code="F-01", name="Bin F-01"))
        w.ctx.refs["WH_FAC"] = wh.id
    # a PO into WH-FAC (Tara buys for every branch), received by Omar: QC-held boards with an inspection
    po_fac = w.new_po(("WALNUT_BOARD", "10", None), warehouse_id=wh.id, expected=date(2026, 10, 20))
    w.po_action(po_fac, "submit")
    w.po_action(po_fac, "approve", SAHIL)
    w.po_action(po_fac, "issue")
    w.ctx.refs["PO_FAC"] = po_fac
    grn = w.receive(po_fac, (1, "4", "WB-FAC-1"), person=OMAR)
    w.ctx.refs["GRN_FAC"] = grn.id
    w.ctx.refs["QC_FAC"] = w.inspections(grn.id)[0].id
    # an HO order with a packing list, a draft challan and a shipment
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    w.reserve(MEERA, order_id)
    w.ctx.refs["SO_HO"] = order_id
    w.ctx.refs["PK_HO"] = w.packing_list(order_id).id
    with w.uow(RAVI) as uow:
        w.ctx.refs["DC_HO"] = orders.create_challan_for_order(uow, order_id, ChallanFromOrder())
    w.ctx.refs["SH_HO"] = w.shipment(sales_order_id=order_id, mode="road", cutoff_date=date(2026, 10, 13)).id
    return w


@pytest.fixture
def client(api_app: FastAPI, world_b: PqlWorld) -> Iterator[TestClient]:  # noqa: F811
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


def _errors(r: Any) -> list[str]:
    return [e.get("code") for e in (r.json().get("errors") or [])]


# ---- procurement: warehouse, vendor and document ids ------------------------------------------------------------
def test_requisition_for_another_branch_warehouse_is_not_found(client: TestClient, world_b: PqlWorld) -> None:
    w = world_b
    body = {"warehouse_id": str(w.ref("WH_FAC")), "required_by": "2026-10-20",
            "lines": [{"product_id": str(w.ref("OAK_TRAY")), "quantity": "24"}]}
    assert _code(client.post(f"{API}/procurement/requisitions", json=body, headers=_as(RAVI))) == (404, "not_found")
    ok = client.post(f"{API}/procurement/requisitions", json={**body, "warehouse_id": str(w.warehouse_id)},
                     headers=_as(RAVI))
    assert ok.status_code == 201
    rid = ok.json()["id"]
    for persona in (OMAR, MEERA, KABIR):  # another branch's operations, sales, the warehouse assistant
        assert client.get(f"{API}/procurement/requisitions/{rid}", headers=_as(persona)).status_code in (403, 404)
    assert client.get(f"{API}/procurement/requisitions/{rid}", headers=_as(OMAR)).status_code == 404
    r = client.post(f"{API}/procurement/requisitions/{rid}/transitions", json={"action": "submit", "expected_version": 1},
                    headers=_as(OMAR))
    assert _code(r) == (404, "not_found")
    assert all(i["id"] != rid for i in client.get(f"{API}/procurement/requisitions", headers=_as(OMAR)).json()["items"])


def test_purchase_order_into_another_branch_warehouse_or_to_an_invisible_vendor(client: TestClient,
                                                                                world_b: PqlWorld) -> None:
    w = world_b
    line = {"product_id": str(w.ref("OAK_TRAY")), "quantity": "24", "unit_price": "300", "expected_date": "2026-10-20"}
    base = {"vendor_party_id": str(w.ref("KAVERI")), "warehouse_id": str(w.warehouse_id), "lines": [line]}
    assert client.post(f"{API}/procurement/purchase-orders", json=base, headers=_as(TARA)).status_code == 201
    # a purchaser who cannot see the vendor: 404, not "vendor exists"
    assert _code(client.post(f"{API}/procurement/purchase-orders", json=base, headers=_as(BLIND))) == (404, "not_found")
    # a customer is not a vendor: 422
    r = client.post(f"{API}/procurement/purchase-orders", json={**base, "vendor_party_id": str(w.ref("NORDHAUS"))},
                    headers=_as(TARA))
    assert r.status_code == 422 and "party_not_vendor" in _errors(r)
    # unknown vendor and unknown warehouse ids: 404
    for field in ("vendor_party_id", "warehouse_id"):
        r = client.post(f"{API}/procurement/purchase-orders", json={**base, field: str(uuid.uuid7())}, headers=_as(TARA))
        assert r.status_code == 404
    # vendor items filtered by an invisible vendor: 404
    r = client.get(f"{API}/procurement/vendor-items", params={"vendor_party_id": str(w.ref("KAVERI"))},
                   headers=_as(BLIND))
    assert r.status_code == 404


def test_purchase_order_documents_of_another_branch_are_not_found(client: TestClient, world_b: PqlWorld) -> None:
    w = world_b
    po_fac, grn_fac = w.ref("PO_FAC"), w.ref("GRN_FAC")
    line_id = str(w.po_lines(po_fac)[0].id)
    ho_po = w.ref("PO_KAVERI")
    for path, method, body in (
        (f"purchase-orders/{po_fac}", "GET", None),
        (f"purchase-orders/{po_fac}", "PATCH", {"expected_version": 1, "notes": "x"}),
        (f"purchase-orders/{po_fac}/transitions", "POST", {"action": "close", "expected_version": 1, "reason": "x"}),
        (f"purchase-orders/{po_fac}/lines/{line_id}/expected-date", "POST",
         {"expected_version": 1, "expected_date": "2026-10-25"}),
        (f"purchase-orders/{po_fac}/lines/{line_id}/cancel", "POST", {"expected_version": 1, "quantity": "1", "reason": "x"}),
        (f"goods-receipts/{grn_fac}", "GET", None),
        (f"goods-receipts/{grn_fac}/post", "POST", {"expected_version": 1}),
        (f"goods-receipts/{grn_fac}/cancel", "POST", {"expected_version": 1}),
    ):
        r = client.request(method, f"{API}/procurement/{path}", json=body, headers=_as(RAVI))
        assert _code(r) == (404, "not_found"), path
    # a line of another PO under a visible PO: 404 on the line
    r = client.post(f"{API}/procurement/purchase-orders/{ho_po}/lines/{line_id}/expected-date",
                    json={"expected_version": 1, "expected_date": "2026-10-25"}, headers=_as(TARA))
    assert r.status_code == 404
    assert all(i["id"] != str(po_fac) for i in client.get(f"{API}/procurement/purchase-orders", headers=_as(RAVI)).json()["items"])
    assert all(i["id"] != str(grn_fac) for i in client.get(f"{API}/procurement/goods-receipts", headers=_as(RAVI)).json()["items"])
    # Omar (FAC) cannot see the HO fixture PO
    assert client.get(f"{API}/procurement/purchase-orders/{ho_po}", headers=_as(OMAR)).status_code == 404
    assert client.get(f"{API}/procurement/purchase-orders/lookup", params={"po_number": "PO-2026-0001"},
                      headers=_as(OMAR)).status_code == 404



def test_goods_receipt_against_invisible_po_warehouse_or_foreign_line_and_location(client: TestClient,
                                                                                   world_b: PqlWorld) -> None:
    w = world_b
    po_fac, ho_po = w.ref("PO_FAC"), w.ref("PO_KAVERI")
    fac_line, ho_line = str(w.po_lines(po_fac)[0].id), str(w.po_lines(ho_po)[0].id)
    lot = {"lot_code": "WB-X"}
    # Ravi cannot receive the FAC PO (404) ...
    r = client.post(f"{API}/procurement/goods-receipts", headers=_as(RAVI),
                    json={"purchase_order_id": str(po_fac), "lines": [{"po_line_id": fac_line, "quantity": "1", **lot}]})
    assert _code(r) == (404, "not_found")
    # ... nor redirect the HO PO into WH-FAC (404)
    r = client.post(f"{API}/procurement/goods-receipts", headers=_as(RAVI),
                    json={"purchase_order_id": str(ho_po), "warehouse_id": str(w.ref("WH_FAC")),
                          "lines": [{"po_line_id": ho_line, "quantity": "1", **lot}]})
    assert _code(r) == (404, "not_found")
    # a line of another PO: 422
    r = client.post(f"{API}/procurement/goods-receipts", headers=_as(RAVI),
                    json={"purchase_order_id": str(ho_po), "lines": [{"po_line_id": fac_line, "quantity": "1", **lot}]})
    assert r.status_code == 422 and "po_line_mismatch" in _errors(r)
    # a stock location of another warehouse for a QC-free product: 422 (location IDOR)
    tray_po = w.issued_po(("OAK_TRAY", "24", "300"), expected=date(2026, 10, 20))
    tray_line = str(w.po_lines(tray_po)[0].id)
    with w.system() as uow:
        from sqlalchemy import select

        from app.modules.inventory.models import Location

        fac_bin = uow.session.scalar(select(Location.id).where(Location.code == "F-01",
                                                               Location.warehouse_id == w.ref("WH_FAC")))
    r = client.post(f"{API}/procurement/goods-receipts", headers=_as(RAVI),
                    json={"purchase_order_id": str(tray_po), "lines": [{"po_line_id": tray_line, "quantity": "1",
                                                                        "location_id": str(fac_bin)}]})
    assert r.status_code == 422 and "location_not_in_warehouse" in _errors(r)
    # sales and the warehouse assistant hold no receiving key: 403 / 404
    r = client.post(f"{API}/procurement/goods-receipts", headers=_as(MEERA),
                    json={"purchase_order_id": str(tray_po), "lines": [{"po_line_id": tray_line, "quantity": "1"}]})
    assert r.status_code in (403, 404)


def test_vendor_bill_scope_and_foreign_lines(client: TestClient, world_b: PqlWorld) -> None:
    w = world_b
    ho_po, po_fac = w.ref("PO_KAVERI"), w.ref("PO_FAC")
    fac_line = str(w.po_lines(po_fac)[0].id)
    body = {"purchase_order_id": str(ho_po), "bill_number": "KTS/9", "bill_date": "2026-10-12",
            "subtotal_amount": "4850", "total_amount": "4850",
            "lines": [{"po_line_id": fac_line, "quantity": "1", "unit_price": "4850"}]}
    r = client.post(f"{API}/procurement/vendor-bills", json=body, headers=_as(ANANYA))
    assert r.status_code == 422 and "po_line_mismatch" in _errors(r)
    assert _code(client.post(f"{API}/procurement/vendor-bills", json=body, headers=_as(RAVI)))[0] == 403  # no key
    assert client.get(f"{API}/procurement/vendor-bills/{uuid.uuid7()}", headers=_as(ANANYA)).status_code == 404
    assert client.get(f"{API}/procurement/purchase-orders/{uuid.uuid7()}/bills", headers=_as(ANANYA)).status_code == 404


# ---- quality -------------------------------------------------------------------------------------------------------
def test_inspections_of_another_branch_are_not_found(client: TestClient, world_b: PqlWorld) -> None:
    w = world_b
    qc = w.ref("QC_FAC")
    assert client.get(f"{API}/quality/inspections/{qc}", headers=_as(RAVI)).status_code == 404
    r = client.post(f"{API}/quality/inspections/{qc}/decide", headers=_as(RAVI),
                    json={"expected_version": 1, "qty_accepted": "4", "qty_rejected": "0"})
    assert _code(r) == (404, "not_found")
    assert all(i["id"] != str(qc) for i in client.get(f"{API}/quality/inspections", headers=_as(RAVI)).json()["items"])
    r = client.post(f"{API}/quality/inspections", headers=_as(RAVI),
                    json={"product_id": str(w.ref("WALNUT_BOARD")), "warehouse_id": str(w.ref("WH_FAC")), "quantity": "1"})
    assert _code(r) == (404, "not_found")
    # Omar decides it, but cannot release into an HO bin (422)
    r = client.post(f"{API}/quality/inspections/{qc}/decide", headers=_as(OMAR),
                    json={"expected_version": 1, "qty_accepted": "4", "qty_rejected": "0",
                          "release_location_id": str(w.ref(keys.WAREHOUSE_REFS.BIN_A12))})
    assert r.status_code == 422 and "location_not_in_warehouse" in _errors(r)
    ok = client.post(f"{API}/quality/inspections/{qc}/decide", headers=_as(OMAR),
                     json={"expected_version": 1, "qty_accepted": "4", "qty_rejected": "0"})
    assert ok.status_code == 200 and ok.json()["status"] == "passed"
    assert client.get(f"{API}/quality/inspections/{qc}", headers=_as(MEERA)).status_code == 404  # no quality key


# ---- logistics -----------------------------------------------------------------------------------------------------
def test_logistics_documents_are_scoped_by_order_owner_and_branch(client: TestClient, world_b: PqlWorld) -> None:
    w = world_b
    so, pk, sh, dc = w.ref("SO_HO"), w.ref("PK_HO"), w.ref("SH_HO"), w.ref("DC_HO")
    # Omar (FAC): every HO document and every command naming one is a 404
    for method, path, body in (
        ("GET", f"packing-lists/{pk}", None),
        ("POST", f"packing-lists/{pk}/finalise", {"expected_version": 1}),
        ("POST", f"packing-lists/{pk}/refresh", {"expected_version": 1}),
        ("GET", f"shipments/{sh}", None),
        ("PATCH", f"shipments/{sh}", {"expected_version": 1, "cutoff_date": "2026-10-14"}),
        ("POST", f"shipments/{sh}/transitions", {"action": "cancel", "expected_version": 1, "reason": "x"}),
        ("POST", f"shipments/{sh}/tracking-refs", {"ref_type": "lr", "value": "LR-1"}),
        ("POST", "packing-lists", {"sales_order_id": str(so)}),
        ("POST", "shipments", {"sales_order_id": str(so), "mode": "road"}),
        ("POST", "shipments", {"challan_id": str(dc), "mode": "road"}),
        ("POST", "load-suggestions", {"packing_list_id": str(pk), "container_profile_id": str(w.ref("CONTAINER_20GP"))}),
    ):
        r = client.request(method, f"{API}/logistics/{path}", json=body, headers=_as(OMAR))
        assert _code(r) == (404, "not_found"), (method, path)
    # Ravi links a packing list / transporter he cannot see: 404
    version = client.get(f"{API}/logistics/shipments/{sh}", headers=_as(RAVI)).json()["version"]
    r = client.patch(f"{API}/logistics/shipments/{sh}", headers=_as(RAVI),
                     json={"expected_version": version, "packing_list_id": str(uuid.uuid7())})
    assert r.status_code == 404
    r = client.post(f"{API}/logistics/shipments", headers=_as(RAVI),
                    json={"sales_order_id": str(so), "mode": "road", "transporter_party_id": str(uuid.uuid7())})
    assert r.status_code == 404
    # a challan of another order is refused (422) when packing
    other = w.order(MEERA, w.won_quote(MEERA, "BERG", ("OAK_TRAY", "240")))
    r = client.post(f"{API}/logistics/packing-lists", headers=_as(RAVI),
                    json={"sales_order_id": str(other), "challan_id": str(dc)})
    assert r.status_code == 422 and "challan_order_mismatch" in _errors(r)
    # sales: Meera reads her own order's packing list and shipment; Neha sees neither (404)
    assert client.get(f"{API}/logistics/packing-lists/{pk}", headers=_as(MEERA)).status_code == 200
    assert client.get(f"{API}/logistics/shipments/{sh}", headers=_as(MEERA)).status_code == 200
    for path in (f"packing-lists/{pk}", f"shipments/{sh}"):
        assert client.get(f"{API}/logistics/{path}", headers=_as(NEHA)).status_code == 404
    assert client.get(f"{API}/logistics/packing-lists", headers=_as(NEHA)).json()["items"] == []
    # sales may read but not change: 403
    r = client.post(f"{API}/logistics/shipments/{sh}/transitions", headers=_as(MEERA),
                    json={"action": "book", "expected_version": version})
    assert r.status_code == 403
    # unknown ids are 404 on every detail route
    for path in ("packing-lists", "shipments"):
        assert client.get(f"{API}/logistics/{path}/{uuid.uuid7()}", headers=_as(RAVI)).status_code == 404

