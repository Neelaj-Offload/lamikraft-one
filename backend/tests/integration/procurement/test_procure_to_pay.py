"""Requisition -> PO -> partial GRN -> QC -> bill match, end to end through the services (operations.md §5).

Tara (purchasing) raises a requisition for 60 sheets of LK-WB-1800 (lot-tracked, QC required) and 48 LK-OT-0450;
Sahil approves it and the PO; Ravi receives part of it (stock goes to QC hold for the board, straight to stock for the
trays), inspects (accepts 18, rejects 2), Ananya matches the bill (price variance, then a quantity mismatch, then a
match) and hands it off. The ledger stays consistent; QC-held stock is not available until released."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden
from app.modules.inventory.models import StockBalance, StockPosting
from app.modules.procurement import matching, purchase_orders, requisitions
from app.modules.procurement.schemas import (
    ConvertToPo,
    RequisitionCreate,
    RequisitionDecision,
    RequisitionLineIn,
)
from app.platform.events.models import DomainEvent
from app.seed.context import D0
from tests.integration.inventory.world import assert_ledger_consistent
from tests.integration.procurement.world import ANANYA, PRIYA, RAVI, SAHIL, TARA, PqlWorld

pytestmark = pytest.mark.db


def _events(w: PqlWorld, name: str) -> list[DomainEvent]:
    with w.system() as uow:
        return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                  DomainEvent.event_type == name)))


def _qc_qty(w: PqlWorld, product: str) -> Decimal:
    from app.modules.inventory.enums import LocationType
    from app.modules.inventory.models import Location

    with w.system() as uow:
        return Decimal(uow.session.scalar(
            select(func.coalesce(func.sum(StockBalance.quantity), 0))
            .join(Location, Location.id == StockBalance.location_id)
            .where(StockBalance.company_id == w.company_id, StockBalance.product_id == w.ref(product),
                   Location.location_type == LocationType.QC_HOLD.value)) or 0)


def test_requisition_to_bill_handoff(pql_world: PqlWorld) -> None:
    w = pql_world
    # ---- requisition (separation of duties) ----
    with w.uow(TARA) as uow:
        r = requisitions.create_requisition(uow, RequisitionCreate(warehouse_id=w.warehouse_id, required_by=D0.date() + timedelta(days=7), lines=[
            RequisitionLineIn(product_id=w.ref("WALNUT_BOARD"), quantity=Decimal(60)),
            RequisitionLineIn(product_id=w.ref("OAK_TRAY"), quantity=Decimal(48))]))
        rid, number = r.id, r.requisition_number
        r = requisitions.decide(uow, rid, RequisitionDecision(action="submit", expected_version=r.version))
        version = r.version
    assert number.startswith("PR-2026-")
    with w.uow(TARA) as uow, pytest.raises(Forbidden) as denied:
        requisitions.decide(uow, rid, RequisitionDecision(action="approve", expected_version=version))
    assert denied.value.code == "approver_is_requester"
    with w.uow(SAHIL) as uow:
        requisitions.decide(uow, rid, RequisitionDecision(action="approve", expected_version=version, note="ok"))
        version = requisitions.get_requisition(uow, rid).version
    # ---- convert to a PO (vendor price for the board, an entered price for the trays) ----
    with w.uow(TARA) as uow:
        tray_line = next(ln for ln in requisitions.lines_of(uow, rid) if ln.product_id == w.ref("OAK_TRAY"))
        po = purchase_orders.convert_requisition(uow, rid, ConvertToPo(
            expected_version=version, vendor_party_id=w.ref("KAVERI"), unit_prices={tray_line.id: Decimal("310.5")}))
        po_id, po_number = po.id, po.po_number
        d = purchase_orders.detail(uow, po)
    assert po_number == "PO-2026-0002"  # the fixture PO is 0001
    assert [(ln.product.product_key, str(ln.quantity), str(ln.unit_price), str(ln.line_amount)) for ln in d.lines] == [
        ("LK-WB-1800", "60", "4850.0000", "291000.0000"), ("LK-OT-0450", "48", "310.5000", "14904.0000")]
    assert str(d.total_amount) == "305904.0000"
    with w.uow(TARA) as uow:
        assert requisitions.get_requisition(uow, rid).status == "closed"  # fully ordered
    w.po_action(po_id, "submit")
    with pytest.raises(Forbidden) as own:
        w.po_action(po_id, "approve", TARA)  # buyers never approve (no key) -- and never their own submission
    assert own.value.code == "permission_denied"
    w.po_action(po_id, "approve", SAHIL)
    w.po_action(po_id, "issue")
    assert len(_events(w, "procurement.purchase_order.approved")) == 2  # the fixture PO and this one
    # ---- partial receipt: 20 boards to QC hold (lot), all 48 trays to stock ----
    board_before = w.summary("WALNUT_BOARD")
    tray_before = w.summary("OAK_TRAY")
    grn = w.receive(po_id, (1, "20", "WB-2611-K"), (2, "48", None))
    assert grn.status == "posted" and grn.grn_number == "GRN-2026-0001" and grn.awaiting_qc == 1
    assert w.summary("WALNUT_BOARD") == board_before  # QC hold is not available to promise
    assert _qc_qty(w, "WALNUT_BOARD") == 20
    assert w.summary("OAK_TRAY")[0] == tray_before[0] + 48
    assert w.postings("goods_receipt", grn.id) == 1
    lines = {ln.line_no: ln for ln in w.po_lines(po_id)}
    assert (lines[1].qty_received, lines[1].qty_accepted, lines[1].qty_outstanding) == (20, 0, 40)
    assert (lines[2].qty_received, lines[2].qty_accepted, lines[2].qty_outstanding) == (48, 48, 0)
    assert w.po(po_id).status == "partially_received"
    # ---- QC: accept 18, reject 2 (released to stock / rejected location) ----
    [insp] = w.inspections(grn.id)
    assert insp.status == "pending" and insp.inspection_number == "QC-2026-0001"
    decided = w.decide(insp.id, "18", "2")
    assert decided.status == "failed" and w.summary("WALNUT_BOARD")[0] == board_before[0] + 18
    assert _qc_qty(w, "WALNUT_BOARD") == 0
    lines = {ln.line_no: ln for ln in w.po_lines(po_id)}
    assert (lines[1].qty_accepted, lines[1].qty_rejected, lines[1].qty_outstanding) == (18, 2, 42)
    assert [e.payload["subject_type"] for e in _events(w, "quality.inspection.failed")] == ["procurement.goods_receipt_line"]
    # ---- three-way match ----
    variance = w.bill(po_id, "KTS/1101", (1, "18", "4900"))
    assert variance.match_status == "price_variance" and variance.status == "mismatch"
    too_many = w.bill(po_id, "KTS/1102", (1, "20", "4850"))
    assert too_many.match_status == "qty_mismatch"  # 2 sheets were rejected, never billable
    ok = w.bill(po_id, "KTS/1103", (1, "18", "4850"), (2, "48", "310.5"))
    assert ok.match_status == "matched" and str(ok.computed_subtotal) == "102204.0000"
    assert [e.payload["match_status"] for e in _events(w, "procurement.vendor_bill.mismatch_detected")] == [
        "price_variance", "qty_mismatch"]
    with w.uow(ANANYA) as uow:
        handed = matching.read(uow, matching.hand_off(uow, ok.id, ok.version))
    with w.uow(ANANYA) as uow, pytest.raises(Conflict) as again:
        matching.hand_off(uow, too_many.id, too_many.version)
    assert handed.status == "handed_off" and again.value.code == "bill_not_matched"
    assert [e.payload for e in _events(w, "procurement.vendor_bill.handed_off")][0]["match_status"] == "matched"
    lines = {ln.line_no: ln for ln in w.po_lines(po_id)}
    assert (lines[1].qty_billed, lines[2].qty_billed) == (18, 48)
    # a second bill for the same accepted quantity no longer matches
    assert w.bill(po_id, "KTS/1104", (2, "1", "310.5")).match_status == "qty_mismatch"
    # ---- receive the rest (42 outstanding: 40 + the 2 rejected), over-receipt refused, then close ----
    with pytest.raises(Conflict) as over:
        w.receive(po_id, (1, "43", "WB-2611-L"))
    assert over.value.code == "over_receipt"
    rest = w.receive(po_id, (1, "42", "WB-2611-L"))
    w.decide(w.inspections(rest.id)[0].id, "42")
    assert w.po(po_id).status == "received"
    w.po_action(po_id, "close")
    assert w.po(po_id).status == "closed"
    with w.system() as uow:
        receipts = uow.session.scalar(select(func.count()).select_from(StockPosting).where(
            StockPosting.company_id == w.company_id, StockPosting.source_type.in_(["goods_receipt", "qc_inspection"])))
    assert receipts == 4  # two receipts, two inspections: one posting each
    assert_ledger_consistent(w)


def test_receipt_replay_posts_once(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.issued_po(("OAK_TRAY", "24", "300"), expected=D0.date())
    grn = w.receive(po_id, (1, "10", None))
    from app.modules.procurement import receiving

    with w.uow(RAVI) as uow:  # a second click / re-delivered command
        again = receiving.post_receipt(uow, grn.id)
    assert again.posting_id == grn.posting_id and w.postings("goods_receipt", grn.id) == 1
    assert w.po_lines(po_id)[0].qty_received == 10
    assert_ledger_consistent(w)


def test_cancel_after_receipt_is_refused_and_po_approver_is_not_submitter(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.new_po(("OAK_TRAY", "24", "300"), person=PRIYA, expected=D0.date())
    w.po_action(po_id, "submit", PRIYA)
    with pytest.raises(Forbidden) as own:
        w.po_action(po_id, "approve", PRIYA)  # admin holds the key, but never for their own submission
    assert own.value.code == "approver_is_submitter"
    w.po_action(po_id, "approve", SAHIL)
    w.po_action(po_id, "issue", PRIYA)
    w.receive(po_id, (1, "5", None))
    with pytest.raises(Conflict) as refused:
        w.po_action(po_id, "cancel", TARA, reason="vendor delay")
    assert refused.value.code == "received_cannot_cancel"

