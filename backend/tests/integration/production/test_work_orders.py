"""Work orders: release reserves materials and blocks on a shortage (``caused_by`` = the inventory shortage), the
``production.material_retry`` consumer unblocks it when stock arrives (events, replay-safe), the briefing issue
follows; issue / consume / return / output post through the inventory posting service and reconcile with the
ledger; the state machine table; planning from an order line."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.modules.inventory import service as inventory
from app.modules.inventory.models import Reservation, StockPosting
from app.modules.production import service
from app.modules.production.models import WoTransaction
from app.modules.production.schemas import (
    IssueLine,
    IssueRequest,
    OperationComplete,
    OutputRequest,
    WipLine,
    WipRequest,
    WorkOrderCreate,
)
from app.modules.production.work_orders import TRANSITIONS
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
MEERA, RAVI = keys.USERS.MEERA, keys.USERS.RAVI


def _events(w: ProdWorld, name: str, aggregate_id: uuid.UUID | None = None) -> list[DomainEvent]:
    with w.system() as uow:
        stmt = select(DomainEvent).where(DomainEvent.company_id == w.company_id, DomainEvent.event_type == name)
        if aggregate_id:
            stmt = stmt.where(DomainEvent.aggregate_id == aggregate_id)
        return list(uow.session.scalars(stmt.order_by(DomainEvent.seq)))


def test_release_blocks_on_shortage_and_unblocks_on_receipt(prod_world: ProdWorld) -> None:
    w = prod_world
    wo = w.wo(w.wo_id)
    assert wo.status == "released" and wo.is_blocked
    [cause] = wo.blocked_causes
    assert cause.type == "inventory.shortage" and cause.label == "Short of LK-WB-1800"
    [mat] = wo.materials
    assert (mat.qty_required, mat.qty_reserved, mat.short) == (Decimal(48), Decimal(40), True)
    assert len(_events(w, "production.work_order.blocked", w.wo_id)) == 1
    w.drain()
    # the briefing family: one open issue for the blocked work order with the shortage as evidence
    from app.modules.tasks.models import Issue, IssueMember

    with w.system() as uow:
        issue = uow.session.scalars(select(Issue).where(Issue.company_id == w.company_id,
                                                        Issue.issue_key == f"wo:{w.wo_id}:blocked")).one()
        assert issue.family == "ops.production_dependencies" and issue.state == "open"
        refs = {m.ref_type for m in uow.session.scalars(select(IssueMember).where(IssueMember.issue_id == issue.id))}
        assert {"production.work_order", "inventory.shortage"} <= refs
        # the ops.shortages issue of the same shortage names the blocked work order as a cause (merge request 5)
        shortage_issues = uow.session.scalars(
            select(Issue).where(Issue.company_id == w.company_id, Issue.family == "ops.shortages",
                                Issue.state == "open")
        ).all()
        wo_members = [
            m.ref_id
            for i in shortage_issues
            for m in uow.session.scalars(select(IssueMember).where(IssueMember.issue_id == i.id))
            if m.ref_type == "production.work_order"
        ]
        assert wo_members == [w.wo_id]
    # supply arrives (a goods receipt stand-in posting through the inventory service): 8 more sheets of the lot
    w.receive("WALNUT_BOARD", "8", lot_code=keys.LOTS.WALNUT, location=keys.WAREHOUSE_REFS.BIN_A12)
    w.drain()
    wo = w.wo(w.wo_id)
    assert not wo.is_blocked and wo.blocked_causes == [] and wo.materials[0].qty_reserved == Decimal(48)
    assert len(_events(w, "production.work_order.unblocked", w.wo_id)) == 1
    with w.system() as uow:
        issue = uow.session.scalars(select(Issue).where(Issue.company_id == w.company_id,
                                                        Issue.issue_key == f"wo:{w.wo_id}:blocked")).one()
        assert issue.state != "open"
    # replaying every stock event to the retry consumer changes nothing
    from app.modules.production.work_orders import handle_material_retry

    reservations = w.count(Reservation)
    with w.system() as uow:
        for ev in uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                DomainEvent.event_type == "inventory.stock.posted")):
            handle_material_retry(uow, ev)
    assert w.count(Reservation) == reservations
    assert len(_events(w, "production.work_order.unblocked", w.wo_id)) == 1
    assert_ledger_consistent(w)


def test_issue_consume_return_output_reconcile_with_the_ledger(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    wo = w.new_wo("5")  # 30 sheets
    wo = w.act(wo.id, "release")
    assert wo.status == "released" and not wo.is_blocked and wo.materials[0].qty_reserved == Decimal(30)
    lot = w.walnut_lot()
    mat = wo.materials[0]
    before = w.wo_postings()
    key = str(uuid.uuid7())
    body = IssueRequest(expected_version=wo.version, lines=[IssueLine(material_id=mat.id, quantity=Decimal(30), lot_id=lot,
                                                                       from_location_id=w.ref(keys.WAREHOUSE_REFS.BIN_A12))])
    with w.uow(DEEPA, idempotency_key=key) as uow:
        wo = service.issue_materials(uow, wo.id, body)
    assert wo.status == "in_progress" and wo.materials[0].qty_issued == Decimal(30) and wo.materials[0].qty_reserved == 0
    a_on_hand, a_reserved = w.summary("WALNUT_BOARD")
    assert a_reserved == 0  # the issue consumed the reservation
    with pytest.raises(ValidationFailed) as exc, w.uow(DEEPA) as uow:
        service.issue_materials(uow, wo.id, IssueRequest(expected_version=wo.version, lines=[
            IssueLine(material_id=mat.id, quantity=Decimal(1), lot_id=lot)]))
    assert exc.value.extra["errors"][0]["code"] == "over_issue"
    with w.uow(DEEPA) as uow:
        wo = service.consume_materials(uow, wo.id, WipRequest(expected_version=wo.version,
                                                              lines=[WipLine(material_id=mat.id, quantity=Decimal(24))]))
        wo = service.return_materials(uow, wo.id, WipRequest(expected_version=wo.version,
                                                             lines=[WipLine(material_id=mat.id, quantity=Decimal(6))]))
        for op in wo.operations:
            wo = service.complete_operation(uow, wo.id, op.id, OperationComplete(expected_version=wo.version, actual_minutes=Decimal(100)))
        wo = service.report_output(uow, wo.id, OutputRequest(expected_version=wo.version, qty_good=Decimal(4), qty_scrap=Decimal(1)))
    m = wo.materials[0]
    assert (m.qty_issued, m.qty_consumed, m.qty_returned, m.qty_in_wip) == (Decimal(30), Decimal(24), Decimal(6), Decimal(0))
    assert (wo.qty_good, wo.qty_scrap) == (Decimal(4), Decimal(1))
    # one posting per event, each referenced by exactly one transaction of the work order
    assert w.wo_postings() == before + 4
    with w.system() as uow:
        txns = list(uow.session.scalars(select(WoTransaction).where(WoTransaction.work_order_id == wo.id)))
        postings = {p.id: p for p in uow.session.scalars(select(StockPosting).where(StockPosting.source_type == "work_order"))}
        assert sorted(t.kind for t in txns) == ["consume", "issue", "output", "return"]
        for t in txns:
            p = postings[t.posting_id]
            assert p.source_id == t.id and p.purpose == {"issue": "issue", "consume": "consume", "return": "return", "output": "output"}[t.kind]
        wip = inventory.wip_location(uow, w.warehouse_id)
        from app.modules.inventory.models import StockBalance

        assert sum(Decimal(b.quantity) for b in uow.session.scalars(select(StockBalance).where(StockBalance.location_id == wip.id))) == 0
    # 6 sheets came back: on hand 40 - 30 + 6 = 16, reserved again for the work order (it still requires 30) until it
    # completes; four sets of output on hand (no QC for the panel set)
    assert w.summary("WALNUT_BOARD") == (Decimal(16), Decimal(6))
    with w.system() as uow:
        s = inventory.summary_of(uow, w.panel_set, w.warehouse_id)
        assert Decimal(s.available_on_hand) == Decimal(4)
    wo = w.act(wo.id, "complete")
    assert wo.status == "completed" and wo.allowed_transitions[0].action == "close"
    assert w.summary("WALNUT_BOARD") == (Decimal(16), Decimal(0))  # completion releases what was not issued
    wo = w.act(wo.id, "close")
    assert wo.status == "closed"
    assert_ledger_consistent(w)


def test_close_refuses_material_left_in_wip_and_cancel_refuses_postings(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    wo = w.act(w.new_wo("1").id, "release")
    mat, lot = wo.materials[0], w.walnut_lot()
    with w.uow(DEEPA) as uow:
        wo = service.issue_materials(uow, wo.id, IssueRequest(expected_version=wo.version, lines=[
            IssueLine(material_id=mat.id, quantity=Decimal(6), lot_id=lot, from_location_id=w.ref(keys.WAREHOUSE_REFS.BIN_A12))]))
        wo = service.consume_materials(uow, wo.id, WipRequest(expected_version=wo.version, lines=[WipLine(material_id=mat.id, quantity=Decimal(5))]))
        wo = service.report_output(uow, wo.id, OutputRequest(expected_version=wo.version, qty_good=Decimal(1)))
    assert wo.capabilities["cancel"].allowed is False
    with pytest.raises(Conflict) as exc:
        w.act(wo.id, "cancel", reason_code="replanned")
    assert exc.value.code == "work_order_has_postings"
    wo = w.act(wo.id, "complete")
    assert wo.capabilities["close"].reason_code == "wip_not_cleared"
    with pytest.raises(Conflict) as exc:
        w.act(wo.id, "close")
    assert exc.value.code == "wip_not_cleared"


def test_transition_table() -> None:
    assert {a: (sorted(f), t) for a, (f, t) in TRANSITIONS.items()} == {
        "release": (["draft"], "released"),
        "complete": (["in_progress"], "completed"),
        "close": (["completed"], "closed"),
        "cancel": (["draft", "in_progress", "released"], "cancelled"),
    }


def test_invalid_transition_is_a_conflict(prod_world: ProdWorld) -> None:
    w = prod_world
    with pytest.raises(Conflict) as exc:
        w.act(w.wo_id, "close")
    assert exc.value.code == "invalid_transition"


def test_plan_from_an_order_line_reserves_through_inventory_and_releases_on_cancel(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    # a quote for the panel set does not exist in the price lists: plan the walnut board line of a won order instead
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    line = w.get_order(MEERA, order_id).lines[0]
    with w.uow(DEEPA) as uow, pytest.raises(ValidationFailed) as exc:
        service.create_work_order(uow, WorkOrderCreate(sales_order_line_id=line.id))
    assert exc.value.extra["errors"][0]["code"] == "bom_not_approved"  # oak trays have no BOM: honest refusal
    wo = w.new_wo("3", notes="for stock")
    wo = w.act(wo.id, "release")
    assert w.summary("WALNUT_BOARD")[1] == Decimal(18)
    wo = w.act(wo.id, "cancel", reason_code="not_needed", reason="test")
    assert wo.status == "cancelled" and w.summary("WALNUT_BOARD")[1] == Decimal(0)
    assert len(_events(w, "production.work_order.cancelled", wo.id)) == 1


def test_output_of_a_qc_required_product_requests_one_inspection_linked_to_the_work_order(prod_world: ProdWorld) -> None:
    """Slice-4 merge (procurement-logistics request 5): output of a QC-required product lands in QC hold and asks
    quality for an inspection of exactly that output; ``quality_inspection.work_order_id`` references the work order."""
    from app.modules.catalogue.models import Product
    from app.modules.quality.models import Inspection

    w = prod_world
    w.cancel_seed_wo()
    with w.system() as uow:
        product = uow.session.get(Product, w.panel_set)
        assert product is not None
        product.qc_required = True
    wo = w.act(w.new_wo("2").id, "release")
    for qty in ("1", "1"):
        with w.uow(DEEPA, idempotency_key=str(uuid.uuid7())) as uow:
            wo = service.report_output(uow, wo.id, OutputRequest(expected_version=wo.version, qty_good=Decimal(qty)))
    with w.system() as uow:
        outputs = list(uow.session.scalars(select(WoTransaction).where(WoTransaction.work_order_id == wo.id,
                                                                       WoTransaction.kind == "output")))
        inspections = list(uow.session.scalars(select(Inspection).where(Inspection.work_order_id == wo.id)))
        assert len(outputs) == 2
        assert sorted(i.subject_id for i in inspections) == sorted(t.id for t in outputs)
        assert {(i.subject_type, i.status, i.quantity, i.source_id) for i in inspections} == {
            ("production.work_order", "pending", Decimal(1), wo.id)
        }
    assert len(_events(w, "quality.inspection.requested")) == 2
