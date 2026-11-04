"""IDOR matrix for the production routes over HTTP (SEC-03 / PERM-23), with the named warehouse-scope tests.

The world adds branch FAC with warehouse WH-FAC and a work order there (planned by Deepa acting for FAC). Operations
(Ravi) is scoped to HO: the FAC work order and everything under it is a 404 on every path. Deepa (production) reads
work orders company-wide but her stock keys are HO-branch scoped, so WH-FAC is invisible to her: she cannot plan in
it, post against it, assess feasibility in it or pass one of its locations. Ids of another record (a material or
operation of another work order, an invisible order line or cut plan) are refused without confirming they exist."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.modules.cutting.models import Plan
from app.modules.inventory import documents
from app.modules.inventory import service as inventory
from app.modules.inventory.schemas import WarehouseCreate
from app.modules.orders.models import SalesOrder
from app.modules.production import service
from app.modules.production.schemas import WorkOrderCreate
from app.platform.authz.context import ActorContext
from app.platform.org.models import Branch
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld
from tests.integration.sales.http import api_app  # noqa: F401

pytestmark = pytest.mark.db
API = "/api/v1/production"
RAVI, SAHIL, MEERA, NEHA, PRIYA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.PRIYA


@pytest.fixture
def world_b(prod_world: ProdWorld) -> ProdWorld:
    w = prod_world
    with w.system() as uow:
        fac = Branch(id=uuid.uuid7(), company_id=w.company_id, branch_code="FAC", name="Factory")
        uow.add(fac)
        fac_id = fac.id
    w.ctx.refs["FAC"] = fac_id
    with w.uow(PRIYA) as uow:
        wh = documents.create_warehouse(uow, WarehouseCreate(code="WH-FAC", name="Factory store", branch_id=fac_id))
        w.ctx.refs["WH_FAC"] = wh.id
    w.actors["DEEPA_FAC"] = w.actor(DEEPA).with_(branch_ids=frozenset({fac_id}))
    with UnitOfWork(w.actors["DEEPA_FAC"], clock=w.ctx.clock) as uow:
        wo = service.create_work_order(uow, WorkOrderCreate(product_id=w.panel_set, quantity=Decimal(1), warehouse_id=wh.id))
        w.ctx.refs["WO_FAC"] = wo.id
        w.ctx.refs["WO_FAC_MAT"] = wo.materials[0].id
        w.ctx.refs["WO_FAC_OP"] = wo.operations[0].id
    with w.system() as uow:
        w.ctx.refs["FAC_STOCK"] = inventory.default_location(uow, wh.id).id
    return w


@pytest.fixture
def client(api_app: FastAPI, world_b: ProdWorld) -> Iterator[TestClient]:  # noqa: F811
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


def _as(persona: str, key: str | None = None) -> dict[str, str]:
    return {"x-test-persona": persona, "Idempotency-Key": key or str(uuid.uuid7())}


def _code(r: Any) -> tuple[int, str | None]:
    body = r.json() if r.headers.get("content-type", "").startswith("application/") else {}
    return r.status_code, body.get("code") if isinstance(body, dict) else None


def _wo(client: TestClient, persona: str, wo_id: uuid.UUID) -> dict[str, Any]:
    r = client.get(f"{API}/work-orders/{wo_id}", headers=_as(persona))
    assert r.status_code == 200, r.text
    return r.json()


# ---- named tests -------------------------------------------------------------------------------------------------------
def test_work_order_of_another_branch_is_not_found_on_every_path(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    wo_id, mat, op = w.ref("WO_FAC"), w.ref("WO_FAC_MAT"), w.ref("WO_FAC_OP")
    v = {"expected_version": 1}
    calls = [
        ("get", f"/work-orders/{wo_id}", None),
        ("patch", f"/work-orders/{wo_id}", {**v, "notes": "x"}),
        ("post", f"/work-orders/{wo_id}/transitions", {**v, "action": "release"}),
        ("post", f"/work-orders/{wo_id}/recheck", v),
        ("post", f"/work-orders/{wo_id}/issue", {**v, "lines": [{"material_id": str(mat), "quantity": "1"}]}),
        ("post", f"/work-orders/{wo_id}/consume", {**v, "lines": [{"material_id": str(mat), "quantity": "1"}]}),
        ("post", f"/work-orders/{wo_id}/return", {**v, "lines": [{"material_id": str(mat), "quantity": "1"}]}),
        ("post", f"/work-orders/{wo_id}/output", {**v, "qty_good": "1"}),
        ("post", f"/work-orders/{wo_id}/operations/{op}/complete", v),
        ("post", f"/work-orders/{wo_id}/operations/{op}/schedule", {**v, "planned_date": "2026-10-14"}),
        ("post", f"/work-orders/{wo_id}/operations/{op}/cut-plan", {**v, "cut_plan_id": str(w.ref(keys.CUT_PLAN_REFS.WALNUT))}),
        ("post", f"/work-orders/{wo_id}/offcuts", {**v, "material_id": str(mat), "length_mm": "500", "width_mm": "400"}),
    ]
    for method, path, body in calls:
        r = getattr(client, method)(f"{API}{path}", headers=_as(RAVI), **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    listed = client.get(f"{API}/work-orders", headers=_as(RAVI)).json()
    assert str(wo_id) not in {x["id"] for x in listed["items"]}
    assert client.get(f"{API}/work-orders/lookup", params={"wo_number": "WO-2026-0002"}, headers=_as(RAVI)).status_code == 404


def test_creating_a_work_order_in_an_invisible_warehouse_is_not_found(client: TestClient, world_b: ProdWorld) -> None:
    r = client.post(f"{API}/work-orders", headers=_as(DEEPA), json={
        "product_id": str(world_b.panel_set), "quantity": "1", "warehouse_id": str(world_b.ref("WH_FAC"))})
    assert _code(r) == (404, "not_found")


def test_posting_against_an_invisible_warehouse_is_not_found_and_without_post_forbidden(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    wo_id = w.ref("WO_FAC")
    # Deepa reads the FAC work order (production reads company-wide) but cannot see its warehouse: 404
    assert client.get(f"{API}/work-orders/{wo_id}", headers=_as(DEEPA)).status_code == 200
    r = client.post(f"{API}/work-orders/{wo_id}/issue", headers=_as(DEEPA),
                    json={"expected_version": 1, "lines": [{"material_id": str(w.ref("WO_FAC_MAT")), "quantity": "1"}]})
    assert _code(r) == (404, "not_found")  # the warehouse scope is checked before the work order's state
    released = client.post(f"{API}/work-orders/{w.wo_id}/issue", headers=_as(SAHIL), json={
        "expected_version": _wo(client, DEEPA, w.wo_id)["version"],
        "lines": [{"material_id": _wo(client, DEEPA, w.wo_id)["materials"][0]["id"], "quantity": "1"}]})
    assert _code(released) == (403, "permission_denied")  # management reads work orders but does not post stock


def test_releasing_a_work_order_whose_warehouse_is_invisible_is_not_found(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    detail = _wo(client, DEEPA, w.ref("WO_FAC"))
    r = client.post(f"{API}/work-orders/{w.ref('WO_FAC')}/transitions", headers=_as(DEEPA),
                    json={"action": "release", "expected_version": detail["version"]})
    assert _code(r) == (404, "not_found")
    assert _wo(client, DEEPA, w.ref("WO_FAC"))["status"] == "draft"


def test_issuing_from_a_location_of_another_warehouse_is_rejected(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    wo = _wo(client, DEEPA, w.wo_id)
    r = client.post(f"{API}/work-orders/{w.wo_id}/issue", headers=_as(DEEPA), json={
        "expected_version": wo["version"], "lines": [{"material_id": wo["materials"][0]["id"], "quantity": "1",
                                                       "lot_id": str(w.walnut_lot()), "from_location_id": str(w.ref("FAC_STOCK"))}]})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "location_not_in_warehouse"


def test_foreign_material_and_operation_ids_are_refused(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    wo = _wo(client, DEEPA, w.wo_id)
    r = client.post(f"{API}/work-orders/{w.wo_id}/issue", headers=_as(DEEPA), json={
        "expected_version": wo["version"], "lines": [{"material_id": str(w.ref("WO_FAC_MAT")), "quantity": "1"}]})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "material_not_found"
    r = client.post(f"{API}/work-orders/{w.wo_id}/operations/{w.ref('WO_FAC_OP')}/complete", headers=_as(DEEPA),
                    json={"expected_version": wo["version"]})
    assert r.status_code == 404


def test_planning_from_an_invisible_order_line_is_not_found(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    line_id = w.get_order(MEERA, order_id).lines[0].id
    with w.system() as uow:
        uow.session.get(SalesOrder, order_id).branch_id = w.ref("FAC")
        uow.flush()
    r = client.post(f"{API}/work-orders", headers=_as(DEEPA), json={"sales_order_line_id": str(line_id)})
    assert _code(r) == (404, "not_found")
    r = client.post(f"{API}/work-orders", headers=_as(DEEPA), json={"sales_order_line_id": str(uuid.uuid7())})
    assert _code(r) == (404, "not_found")


def test_linking_an_invisible_cut_plan_is_not_found(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    with w.uow(DEEPA) as uow:
        draft = service.create_work_order(uow, WorkOrderCreate(product_id=w.panel_set, quantity=Decimal(1),
                                                               warehouse_id=w.warehouse_id))
    with w.system() as uow:
        plan = uow.session.scalars(select(Plan).where(Plan.id == w.ref(keys.CUT_PLAN_REFS.WALNUT))).one()
        plan.branch_id, plan.owner_user_id = w.ref("FAC"), w.user_id(PRIYA)
        uow.flush()
    board = next(o for o in draft.operations if o.is_board_cutting)
    r = client.post(f"{API}/work-orders/{draft.id}/operations/{board.id}/cut-plan", headers=_as(RAVI),
                    json={"expected_version": draft.version, "cut_plan_id": str(w.ref(keys.CUT_PLAN_REFS.WALNUT))})
    assert _code(r) == (404, "not_found")
    r = client.post(f"{API}/work-orders/{draft.id}/operations/{board.id}/cut-plan", headers=_as(RAVI),
                    json={"expected_version": draft.version, "cut_plan_id": str(uuid.uuid7())})
    assert _code(r) == (404, "not_found")


def test_feasibility_for_an_invisible_warehouse_or_order_line_is_not_found(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    r = client.post(f"{API}/feasibility", headers=_as(DEEPA), json={
        "product_id": str(w.panel_set), "quantity": "1", "need_by": "2026-10-20", "warehouse_id": str(w.ref("WH_FAC"))})
    assert _code(r) == (404, "not_found")
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    line_id = w.get_order(MEERA, order_id).lines[0].id
    assert client.get(f"{API}/feasibility/order-lines/{line_id}", headers=_as(MEERA),
                      params={"need_by": "2026-10-20"}).status_code == 200
    assert _code(client.get(f"{API}/feasibility/order-lines/{line_id}", headers=_as(NEHA),
                            params={"need_by": "2026-10-20"})) == (404, "not_found")
    r = client.post(f"{API}/simulations", headers=_as(DEEPA), json={
        "checks": [{"product_id": str(w.panel_set), "quantity": "1", "need_by": "2026-10-20"}],
        "stock_changes": [{"product_id": str(w.walnut), "delta": "5", "warehouse_id": str(w.ref("WH_FAC"))}]})
    assert _code(r) == (404, "not_found")


def test_unknown_permission_holders_are_forbidden(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    assert _code(client.get(f"{API}/work-orders", headers=_as(MEERA)))[0] == 403  # sales do not read work orders
    assert _code(client.post(f"{API}/boms", headers=_as(RAVI), json={"product_id": str(w.panel_set)}))[0] == 403
    assert _code(client.post(f"{API}/cost-rollups", headers=_as(RAVI), json={"product_id": str(w.panel_set)}))[0] == 403
    assert _code(client.post(f"{API}/simulations", headers=_as(MEERA), json={
        "checks": [{"product_id": str(w.panel_set), "quantity": "1", "need_by": "2026-10-20"}]}))[0] == 403


def test_idempotent_issue_replay_and_cost_redaction_over_http(client: TestClient, world_b: ProdWorld) -> None:
    w = world_b
    w.cancel_seed_wo()
    created = client.post(f"{API}/work-orders", headers=_as(DEEPA), json={
        "product_id": str(w.panel_set), "quantity": "1", "warehouse_id": str(w.warehouse_id)})
    assert created.status_code == 201, created.text
    wo = created.json()
    wo = client.post(f"{API}/work-orders/{wo['id']}/transitions", headers=_as(DEEPA),
                     json={"action": "release", "expected_version": wo["version"]}).json()
    key = str(uuid.uuid7())
    body = {"expected_version": wo["version"], "lines": [{"material_id": wo["materials"][0]["id"], "quantity": "6",
                                                          "lot_id": str(w.walnut_lot()), "from_location_id": str(w.ref(keys.WAREHOUSE_REFS.BIN_A12))}]}
    before = w.wo_postings()
    first = client.post(f"{API}/work-orders/{wo['id']}/issue", headers=_as(DEEPA, key), json=body)
    again = client.post(f"{API}/work-orders/{wo['id']}/issue", headers=_as(DEEPA, key), json=body)
    assert first.status_code == 200 and again.status_code == 200, again.text
    assert again.headers.get("Idempotent-Replayed") == "true" and w.wo_postings() == before + 1
    rollup = client.post(f"{API}/cost-rollups", headers=_as(DEEPA), json={"product_id": str(w.panel_set)})
    assert rollup.status_code == 201 and rollup.json()["total"]["amount"]
    seen = client.get(f"{API}/cost-rollups/{rollup.json()['id']}", headers=_as(RAVI)).json()
    assert seen["total"] is None and seen["lines"] is None and "total" in seen["redacted_fields"]
    wc = client.get(f"{API}/work-centers", headers=_as(RAVI)).json()
    assert all(c["rate_per_hour"] is None for c in wc)
