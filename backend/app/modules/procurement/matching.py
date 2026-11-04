"""Vendor bills and the three-way match (PO, accepted receipts, bill).

Per bill line (all Decimal):
- quantity: billed <= accepted - already billed on other handed-off bills for the PO line (else ``qty_mismatch``);
  goods still waiting in QC make the shortfall ``pending_qc`` (match status ``pending``) instead of a mismatch;
- price: |bill price - PO price| <= PO price x ``price_variance_tolerance_pct`` / 100 (else ``price_variance``);
- amounts: each line amount is quantity x price HALF_UP to the minor unit; the entered subtotal must equal their sum
  (else ``amount_mismatch``).
A matched bill can be handed off to finance (``procurement.vendor_bill.handed_off``; the accounting adapter arrives in
Slice 5); a mismatch emits ``procurement.vendor_bill.mismatch_detected`` once per match run that finds one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict
from app.core.money import quantize_money
from app.modules.procurement import events as ev
from app.modules.procurement.common import ZERO, cap, invalid, money4, party_briefs, plain, product_briefs
from app.modules.procurement.enums import MatchStatus, VendorBillStatus
from app.modules.procurement.events import ProcurementPolicy
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderLine, VendorBill, VendorBillLine
from app.modules.procurement.policies import BILL_CREATE, BILL_READ
from app.modules.procurement.purchase_orders import lines_of
from app.modules.procurement.schemas import BillCreate, BillLineRead, BillRead, DocLink, MatchException
from app.platform.uow import UnitOfWork

B = VendorBillStatus
M = MatchStatus


def _policy(uow: UnitOfWork) -> ProcurementPolicy:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "procurement_policy")
    assert isinstance(value, ProcurementPolicy)
    return value


def bill_lines(uow: UnitOfWork, bill_id: uuid.UUID) -> list[VendorBillLine]:
    return list(
        uow.session.scalars(
            select(VendorBillLine)
            .where(VendorBillLine.vendor_bill_id == bill_id)
            .order_by(VendorBillLine.line_no)
        )
    )


def create_bill(uow: UnitOfWork, data: BillCreate) -> VendorBill:
    uow.actor.require(BILL_CREATE)
    po = uow.repo(PurchaseOrder).get(data.purchase_order_id, for_update=True)
    if po.status in ("draft", "pending_approval", "cancelled"):
        raise Conflict(
            "Bills are matched against approved orders", code="invalid_status", current_status=po.status
        )
    clash = uow.session.scalar(
        select(VendorBill.id).where(
            VendorBill.company_id == uow.actor.company_id,
            VendorBill.vendor_party_id == po.vendor_party_id,
            VendorBill.bill_number == data.bill_number,
            VendorBill.status != B.CANCELLED.value,
        )
    )
    if clash is not None:
        raise Conflict("This vendor bill number is already recorded", code="duplicate_bill_number")
    po_lines = {ln.id: ln for ln in lines_of(uow, po.id)}
    bill = VendorBill(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        vendor_party_id=po.vendor_party_id,
        purchase_order_id=po.id,
        bill_number=data.bill_number,
        bill_date=data.bill_date,
        currency=po.currency,
        subtotal_amount=data.subtotal_amount,
        tax_amount=data.tax_amount,
        total_amount=data.total_amount,
        status=B.DRAFT.value,
        match_status=M.PENDING.value,
        notes=data.notes,
    )
    uow.add(bill)
    uow.flush()
    for i, ln in enumerate(data.lines, start=1):
        pl = po_lines.get(ln.po_line_id)
        if pl is None:
            raise invalid(
                "The line is not on this purchase order", ["lines", i - 1, "po_line_id"], "po_line_mismatch"
            )
        uow.add(
            VendorBillLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                vendor_bill_id=bill.id,
                line_no=i,
                po_line_id=pl.id,
                goods_receipt_line_id=ln.goods_receipt_line_id,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                line_amount=quantize_money(Decimal(ln.quantity) * Decimal(ln.unit_price), po.currency),
            )
        )
    uow.flush()
    match_bill(uow, bill.id)
    uow.audit(
        "procurement.vendor_bill.create",
        resource_type="procurement.vendor_bill",
        resource_id=bill.id,
        resource_label=bill.bill_number,
        details={"po_number": po.po_number},
    )
    return bill


def _billed_elsewhere(uow: UnitOfWork, po_line_id: uuid.UUID, bill_id: uuid.UUID) -> Decimal:
    return Decimal(
        uow.session.scalar(
            select(func.coalesce(func.sum(VendorBillLine.quantity), 0))
            .join(VendorBill, VendorBill.id == VendorBillLine.vendor_bill_id)
            .where(
                VendorBillLine.po_line_id == po_line_id,
                VendorBill.id != bill_id,
                VendorBill.status == B.HANDED_OFF.value,
            )
        )
        or 0
    )


def evaluate(uow: UnitOfWork, bill: VendorBill) -> tuple[str, list[MatchException]]:
    """Pure evaluation of the match (no writes)."""
    tol = _policy(uow).price_variance_tolerance_pct
    po_lines = {ln.id: ln for ln in lines_of(uow, bill.purchase_order_id)}
    lines = bill_lines(uow, bill.id)
    out: list[MatchException] = []
    billed: dict[uuid.UUID, Decimal] = {}
    for ln in lines:
        billed[ln.po_line_id] = billed.get(ln.po_line_id, ZERO) + Decimal(ln.quantity)
    for ln in lines:
        pl = po_lines[ln.po_line_id]
        po_price, price = Decimal(pl.unit_price), Decimal(ln.unit_price)
        if abs(price - po_price) > po_price * Decimal(tol) / 100:
            out.append(
                MatchException(
                    code="price_variance",
                    po_line_id=pl.id,
                    line_no=ln.line_no,
                    expected=po_price,
                    actual=price,
                )
            )
    for po_line_id, qty in billed.items():
        pl = po_lines[po_line_id]
        open_to_bill = Decimal(pl.qty_accepted) - _billed_elsewhere(uow, pl.id, bill.id)
        if qty > open_to_bill:
            pending_qc = Decimal(pl.qty_received) - Decimal(pl.qty_accepted) - Decimal(pl.qty_rejected)
            code = "pending_qc" if qty <= open_to_bill + pending_qc else "qty_mismatch"
            out.append(
                MatchException(
                    code=code,
                    po_line_id=pl.id,
                    line_no=pl.line_no,
                    expected=plain(open_to_bill),  # type: ignore[arg-type]
                    actual=plain(qty),
                )
            )
    computed = sum((Decimal(ln.line_amount) for ln in lines), ZERO)
    if quantize_money(Decimal(bill.subtotal_amount), bill.currency) != computed:
        out.append(
            MatchException(code="amount_mismatch", expected=computed, actual=Decimal(bill.subtotal_amount))
        )
    codes = {e.code for e in out}
    if "qty_mismatch" in codes:
        status = M.QTY_MISMATCH.value
    elif "price_variance" in codes:
        status = M.PRICE_VARIANCE.value
    elif "amount_mismatch" in codes:
        status = M.AMOUNT_MISMATCH.value
    elif "pending_qc" in codes:
        status = M.PENDING.value
    else:
        status = M.MATCHED.value
    return status, out


def match_bill(uow: UnitOfWork, bill_id: uuid.UUID, *, expected_version: int | None = None) -> VendorBill:
    bill = uow.repo(VendorBill).get(bill_id, for_update=True)
    uow.actor.require(BILL_CREATE)
    if expected_version is not None:
        uow.expect_version(bill, expected_version)
    if bill.status in (B.HANDED_OFF.value, B.CANCELLED.value):
        raise Conflict("This bill is closed", code="invalid_status", current_status=bill.status)
    status, exceptions = evaluate(uow, bill)
    bill.match_status = status
    bill.match_exceptions = [e.model_dump(mode="json") for e in exceptions]
    bill.matched_at = uow.now()
    bill.status = (
        B.MATCHED.value
        if status == M.MATCHED.value
        else (B.MISMATCH.value if status != M.PENDING.value else B.DRAFT.value)
    )
    uow.flush()
    if status not in (M.MATCHED.value, M.PENDING.value):
        uow.emit(
            ev.BILL_MISMATCH,
            aggregate_id=bill.id,
            aggregate_version=bill.version,
            payload={"vendor_bill_id": str(bill.id), "match_status": status},
        )
    return bill


def hand_off(uow: UnitOfWork, bill_id: uuid.UUID, expected_version: int) -> VendorBill:
    bill = uow.repo(VendorBill).get(bill_id, for_update=True)
    uow.actor.require(BILL_CREATE)
    uow.expect_version(bill, expected_version)
    po = uow.session.get(PurchaseOrder, bill.purchase_order_id)
    assert po is not None
    pls = {ln.id: ln for ln in lines_of(uow, po.id, for_update=True)}
    status, exceptions = evaluate(uow, bill)  # re-checked under the PO line locks
    if bill.status != B.MATCHED.value or status != M.MATCHED.value:
        bill.match_status, bill.match_exceptions = status, [e.model_dump(mode="json") for e in exceptions]
        uow.flush()
        raise Conflict("Only a matched bill is handed off", code="bill_not_matched", match_status=status)
    for ln in bill_lines(uow, bill.id):
        pl = pls[ln.po_line_id]
        pl.qty_billed = Decimal(pl.qty_billed) + Decimal(ln.quantity)
    bill.status, bill.handed_off_at, bill.handed_off_by = B.HANDED_OFF.value, uow.now(), uow.actor.user_id
    uow.flush()
    uow.emit(
        ev.BILL_HANDED_OFF,
        aggregate_id=bill.id,
        aggregate_version=bill.version,
        payload={"vendor_bill_id": str(bill.id), "match_status": bill.match_status},
    )
    uow.audit(
        "procurement.vendor_bill.hand_off",
        resource_type="procurement.vendor_bill",
        resource_id=bill.id,
        resource_label=bill.bill_number,
        details={"po_number": po.po_number},
    )
    return bill


def read(uow: UnitOfWork, bill: VendorBill) -> BillRead:
    lines = bill_lines(uow, bill.id)
    pls = {ln.id: ln for ln in lines_of(uow, bill.purchase_order_id)}
    products = product_briefs(uow, [pls[ln.po_line_id].product_id for ln in lines])
    po = uow.session.get(PurchaseOrder, bill.purchase_order_id)
    assert po is not None
    can = uow.actor.can(BILL_CREATE)
    open_ = bill.status not in (B.HANDED_OFF.value, B.CANCELLED.value)
    return BillRead(
        id=bill.id,
        bill_number=bill.bill_number,
        bill_date=bill.bill_date,
        vendor=party_briefs(uow, [bill.vendor_party_id])[bill.vendor_party_id],
        purchase_order=DocLink(
            id=po.id, number=po.po_number, status=po.status, path=f"/operations/purchasing/orders/{po.id}"
        ),
        currency=bill.currency,
        subtotal_amount=money4(bill.subtotal_amount),
        tax_amount=money4(bill.tax_amount),
        total_amount=money4(bill.total_amount),
        computed_subtotal=money4(sum((Decimal(ln.line_amount) for ln in lines), ZERO)),
        status=bill.status,
        match_status=bill.match_status,  # type: ignore[arg-type]
        match_exceptions=[MatchException.model_validate(e) for e in bill.match_exceptions or []],
        matched_at=bill.matched_at,
        handed_off_at=bill.handed_off_at,
        notes=bill.notes,
        lines=[
            BillLineRead(
                id=ln.id,
                line_no=ln.line_no,
                po_line_id=ln.po_line_id,
                po_line_no=pls[ln.po_line_id].line_no,
                product=products[pls[ln.po_line_id].product_id],
                quantity=plain(ln.quantity),
                unit_price=money4(ln.unit_price),
                line_amount=money4(ln.line_amount),
                po_unit_price=money4(pls[ln.po_line_id].unit_price),
                qty_accepted=plain(pls[ln.po_line_id].qty_accepted),
                qty_billed_before=plain(_billed_elsewhere(uow, ln.po_line_id, bill.id)),
            )
            for ln in lines
        ],
        capabilities={
            "match": cap(can and open_, "invalid_status" if can else "permission_denied"),
            "hand_off": cap(
                can and bill.status == B.MATCHED.value, "bill_not_matched" if can else "permission_denied"
            ),
        },
        version=bill.version,
    )


def list_bills(uow: UnitOfWork, purchase_order_id: uuid.UUID) -> list[BillRead]:
    uow.actor.require(BILL_READ)
    uow.repo(PurchaseOrder).get(purchase_order_id)  # the PO must be visible
    rows = list(
        uow.session.scalars(
            select(VendorBill)
            .where(
                VendorBill.company_id == uow.actor.company_id,
                VendorBill.purchase_order_id == purchase_order_id,
            )
            .order_by(VendorBill.created_at)
        )
    )
    return [read(uow, b) for b in rows]


def get_bill(uow: UnitOfWork, bill_id: uuid.UUID) -> BillRead:
    bill = uow.repo(VendorBill).get(bill_id)
    uow.repo(PurchaseOrder).get(bill.purchase_order_id)
    return read(uow, bill)


__all__ = ["create_bill", "evaluate", "get_bill", "hand_off", "list_bills", "match_bill", "PurchaseOrderLine"]
