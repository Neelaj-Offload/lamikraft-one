"""Logistics through the services: packing lists from an order (server-side Decimal CBM / weights, stale on packaging or
order changes, finalise blocked while incomplete), shipments with company-time cutoffs (``ops.dispatch_cutoffs`` hard
task at the cutoff), dispatch through the challan (exactly one stock posting, whichever path issues it), delivery with
evidence and exceptions, and the load suggestion."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import ProductPackaging
from app.modules.logistics import packing_lists, shipments
from app.modules.logistics.schemas import LineOverride, LoadSuggestionRequest
from app.modules.orders import service as orders
from app.modules.orders.schemas import ChallanFromOrder
from app.platform.events.models import DomainEvent
from tests.integration.inventory.world import assert_ledger_consistent
from tests.integration.procurement.world import MEERA, RAVI, PqlWorld

pytestmark = pytest.mark.db


def _order(w: PqlWorld, qty: str = "240", product: str = "OAK_TRAY") -> uuid.UUID:
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", (product, qty)))
    w.reserve(MEERA, order_id)
    return order_id


def _challan(w: PqlWorld, order_id: uuid.UUID) -> uuid.UUID:
    with w.uow(RAVI) as uow:
        return orders.create_challan_for_order(uow, order_id, ChallanFromOrder())


def _events(w: PqlWorld, name: str) -> list[DomainEvent]:
    with w.system() as uow:
        return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                  DomainEvent.event_type == name)))


def test_packing_list_from_order_stale_and_finalise(pql_world: PqlWorld) -> None:
    w = pql_world
    order_id = _order(w)
    pl = w.packing_list(order_id)
    assert pl.packing_list_number == "PK-2026-0001" and pl.party_name == "Nordhaus Interiors GmbH"
    [line] = pl.lines
    assert (line.quantity, line.cartons, line.inner_packs, line.carton_qty) == (Decimal(240), 10, 40, 24)
    assert (pl.total_cartons, pl.total_cbm, pl.total_net_kg, pl.total_gross_kg) == (
        10, Decimal("0.475200"), Decimal("108.000"), Decimal("116.000"))
    assert not pl.totals_partial and pl.capabilities["finalise"].allowed
    # the catalogue packaging changes: the draft goes stale once, finalising is blocked until refreshed
    with w.uow(keys_priya()) as uow:
        pk = uow.session.get(ProductPackaging, w.ref("OAK_TRAY"))
        assert pk is not None
        from app.modules.catalogue.models import Product
        from app.modules.catalogue.schemas import PackagingIn, ProductUpdate

        version = uow.session.get(Product, w.ref("OAK_TRAY")).version  # type: ignore[union-attr]
        packaging = PackagingIn(carton_qty=pk.carton_qty, inner_qty=pk.inner_qty, unit_weight_g=pk.unit_weight_g,
                                packing_type=pk.packing_type, carton_length_cm=pk.carton_length_cm,
                                carton_width_cm=pk.carton_width_cm, carton_height_cm=pk.carton_height_cm,
                                net_weight_kg=pk.net_weight_kg, gross_weight_kg=Decimal("12.0"), cbm=pk.cbm)
        catalogue.update_product(uow, w.ref("OAK_TRAY"), ProductUpdate(expected_version=version, packaging=packaging))
    w.drain()
    w.drain()
    with w.uow(RAVI) as uow:
        stale = packing_lists.get_packing_list(uow, pl.id)
        assert stale.is_stale and stale.stale_reason == "packaging_changed"
        with pytest.raises(Conflict) as blocked:
            packing_lists.finalise(uow, pl.id, stale.version)
    assert blocked.value.code == "packing_list_stale"
    assert len(_events(w, "logistics.packing_list.became_stale")) == 1
    with w.uow(RAVI) as uow:
        fresh = packing_lists.detail(uow, packing_lists.refresh(uow, pl.id, stale.version))
    assert not fresh.is_stale and fresh.total_gross_kg == Decimal("120.000")  # 10 x 12.0
    with w.uow(RAVI) as uow:
        final = packing_lists.detail(uow, packing_lists.finalise(uow, pl.id, fresh.version))
    assert final.status == "final" and len(_events(w, "logistics.packing_list.finalised")) == 1


def test_incomplete_lines_need_values_with_a_reason(pql_world: PqlWorld) -> None:
    w = pql_world
    order_id = _order(w)
    with w.uow(keys_priya()) as uow:  # test-local: the tray's carton dimensions, CBM and weights become unknown
        from app.modules.catalogue.models import Product
        from app.modules.catalogue.schemas import PackagingIn, ProductUpdate

        version = uow.session.get(Product, w.ref("OAK_TRAY")).version  # type: ignore[union-attr]
        catalogue.update_product(uow, w.ref("OAK_TRAY"), ProductUpdate(
            expected_version=version, packaging=PackagingIn(carton_qty=24, packing_type="Poly bag")))
    pl = w.packing_list(order_id)
    [line] = pl.lines
    assert pl.totals_partial and "missing_cbm" in line.incomplete_reasons
    assert pl.capabilities["finalise"].reason_code == "packing_list_incomplete"
    with w.uow(RAVI) as uow:
        with pytest.raises(Conflict) as blocked:
            packing_lists.finalise(uow, pl.id, pl.version)
        assert blocked.value.code == "packing_list_incomplete"
    with w.uow(RAVI) as uow:
        fixed = packing_lists.detail(uow, packing_lists.override_line(uow, pl.id, line.id, LineOverride(
            expected_version=pl.version, cbm=Decimal("0.62"), net_kg=Decimal("410"), gross_kg=Decimal("432.5"),
            reason="Measured pallet 120 x 100 x 52 cm")))
    assert fixed.lines[0].incomplete_reasons == [] and fixed.capabilities["finalise"].allowed
    assert fixed.total_cbm == Decimal("0.620000") and fixed.lines[0].override_reason


def test_shipment_cutoff_task_in_company_time(pql_world: PqlWorld) -> None:
    w = pql_world
    order_id = _order(w)
    sh = w.shipment(sales_order_id=order_id, mode="road", transporter_name="Blue Dart Surface",
                    cutoff_date=date(2026, 10, 13), cutoff_time=time(16, 0))
    assert sh.shipment_number == "SH-2026-0001"
    assert sh.cutoff_at == datetime(2026, 10, 13, 10, 30, tzinfo=UTC)  # 16:00 IST
    assert sh.cutoff_local == "13 Oct 2026 16:00"
    [scheduled] = _events(w, "logistics.shipment.scheduled")
    assert scheduled.payload["cutoff_at"] == "2026-10-13T10:30:00+00:00"
    w.drain()
    [issue] = w.issues("ops.dispatch_cutoffs")
    [task] = w.open_tasks(issue)
    assert (task.kind, task.due_kind, task.due_at, task.queue_code) == (
        "dispatch_by_cutoff", "hard", datetime(2026, 10, 13, 10, 30, tzinfo=UTC), "operations")
    assert task.title == "Dispatch SH-2026-0001 to Nordhaus Interiors GmbH by 13 Oct 2026 16:00"
    # a cutoff without a time is the end of that day's shift (18:30 IST); moving it re-schedules the task
    with w.uow(RAVI) as uow:
        from app.modules.logistics.schemas import ShipmentUpdate

        moved = shipments.detail(uow, shipments.update_shipment(uow, sh.id, ShipmentUpdate(
            expected_version=sh.version, cutoff_date=date(2026, 10, 14))))
    assert moved.cutoff_at == datetime(2026, 10, 14, 13, 0, tzinfo=UTC)
    w.drain()
    [issue] = w.issues("ops.dispatch_cutoffs")
    [task] = w.open_tasks(issue)
    assert task.due_at == datetime(2026, 10, 14, 13, 0, tzinfo=UTC)


def test_dispatch_through_shipment_or_challan_posts_once(pql_world: PqlWorld) -> None:
    w = pql_world
    # path 1: dispatch the shipment -> issues the linked draft challan (the one movement)
    order_a = _order(w)
    challan_a = _challan(w, order_a)
    sh = w.shipment(sales_order_id=order_a, challan_id=challan_a, mode="road", cutoff_date=date(2026, 10, 12))
    w.drain()
    [issue] = [i for i in w.issues("ops.dispatch_cutoffs") if i.root_ref_id == sh.id]
    assert [t.kind for t in w.open_tasks(issue)] == ["dispatch_by_cutoff"]
    with pytest.raises(Conflict):
        w.shipment_action(w.shipment(sales_order_id=order_a, mode="road").id, "dispatch")  # no challan linked
    key = str(uuid.uuid7())
    dispatched = w.shipment_action(sh.id, "dispatch", key=key)
    assert dispatched.status == "dispatched" and dispatched.dispatch_posting_id is not None
    assert w.challan(RAVI, challan_a).status == "issued" and w.postings("challan", challan_a) == 1
    w.drain()  # the challan-issued event reaches logistics.shipment_status: no second effect
    assert w.postings("challan", challan_a) == 1 and len(_events(w, "logistics.shipment.dispatched")) == 1
    assert w.open_tasks(issue) == []
    # path 2: the challan is issued from the challan screen -> the consumer marks the shipment dispatched
    order_b = _order(w)
    challan_b = _challan(w, order_b)
    sh_b = w.shipment(sales_order_id=order_b, challan_id=challan_b, mode="courier")
    w.transition_challan(RAVI, challan_b, "issue")
    w.drain()
    w.drain()
    with w.uow(RAVI) as uow:
        b = shipments.get_shipment(uow, sh_b.id)
    assert b.status == "dispatched" and w.postings("challan", challan_b) == 1
    # delivered needs evidence; exceptions in between
    with pytest.raises(ValidationFailed):
        w.shipment_action(sh.id, "deliver", evidence_kind="signed_pod")
    w.shipment_action(sh.id, "record_exception", exception_code="delayed", note="Truck held at the border")
    w.drain()

    def open_kinds() -> list[str]:
        return [t.kind for i in w.issues("ops.dispatch_cutoffs") if i.root_ref_id == sh.id for t in w.open_tasks(i)]

    assert open_kinds() == ["resolve_shipment_exception"]
    delivered = w.shipment_action(sh.id, "deliver", evidence_kind="signed_pod", evidence_note="POD signed by L. Brandt")
    assert delivered.status == "delivered" and delivered.evidence_kind == "signed_pod"
    w.drain()
    assert open_kinds() == []
    assert_ledger_consistent(w)


def test_load_suggestion_for_a_packing_list(pql_world: PqlWorld) -> None:
    w = pql_world
    pl = w.packing_list(_order(w))
    with w.uow(RAVI) as uow:
        s = shipments.suggest_load(uow, LoadSuggestionRequest(packing_list_id=pl.id,
                                                              container_profile_id=w.ref("CONTAINER_20GP")))
    assert s.container_count == 1 and s.loads[0].allocations[0].cartons == 10
    assert s.loads[0].cbm == Decimal("0.475200") and s.loads[0].binding_constraint == "volume"
    assert "no 3D stowage" in s.label and not s.totals_partial


def keys_priya() -> str:
    from app.seed.world import keys

    return keys.USERS.PRIYA
