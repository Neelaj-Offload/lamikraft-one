"""Purchase orders (``PO-YYYY-NNNN``).

States: draft -> pending_approval -> approved -> issued -> partially_received -> received -> closed; cancelled.
- Only a draft is edited (its lines are replaced); prices default to the vendor's active vendor item, and any other
  price needs ``price_override_reason``. Line amounts are Decimal, HALF_UP to the currency's minor unit.
- ``approve`` needs ``procurement.purchase_order.approve`` and a different person from the submitter (403
  ``approver_is_submitter``; CHECK in the database); ``reject`` returns the PO to draft with a reason.
- ``issue`` marks it sent to the vendor (the delivery itself goes through a channel adapter later).
- ``close`` short-closes what is still outstanding (reason required when anything is outstanding); ``cancel`` is
  refused once anything was received.
- Expected dates per line can move while the vendor still owes goods (``expected_date_changed``); the overdue sweep
  emits ``became_overdue`` once per newly late set of lines.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.http.pagination import Page
from app.core.money import quantize_money
from app.modules.inventory.policies import require_warehouse
from app.modules.procurement import events as ev
from app.modules.procurement.common import (
    ZERO,
    business_date,
    cap,
    invalid,
    money4,
    number,
    party_briefs,
    plain,
    product_briefs,
    require_scope,
    require_vendor,
    stock_product,
    user_briefs,
    warehouse_briefs,
)
from app.modules.procurement.enums import PO_OPEN_FOR_RECEIPT, PoTransitionAction, PurchaseOrderStatus
from app.modules.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    Requisition,
    RequisitionLine,
    VendorBill,
)
from app.modules.procurement.schemas import (
    ConvertToPo,
    DocLink,
    ExpectedDateChange,
    LineCancel,
    PoCreate,
    PoDetail,
    PoLineIn,
    PoLineRead,
    PoSummary,
    PoTransition,
    PoUpdate,
)
from app.modules.procurement.vendor_items import active_item
from app.platform.uow import UnitOfWork

P = PurchaseOrderStatus
A = PoTransitionAction
READ = "procurement.purchase_order.read"
CREATE = "procurement.purchase_order.create"
OPEN_VALUES = frozenset(s.value for s in PO_OPEN_FOR_RECEIPT)

#: (status, action) -> (to status, permission action)
TRANSITIONS: dict[tuple[str, str], tuple[str, str]] = {
    (P.DRAFT.value, A.SUBMIT.value): (P.PENDING_APPROVAL.value, "update"),
    (P.DRAFT.value, A.CANCEL.value): (P.CANCELLED.value, "transition"),
    (P.PENDING_APPROVAL.value, A.APPROVE.value): (P.APPROVED.value, "approve"),
    (P.PENDING_APPROVAL.value, A.REJECT.value): (P.DRAFT.value, "approve"),
    (P.PENDING_APPROVAL.value, A.CANCEL.value): (P.CANCELLED.value, "transition"),
    (P.APPROVED.value, A.ISSUE.value): (P.ISSUED.value, "issue"),
    (P.APPROVED.value, A.CANCEL.value): (P.CANCELLED.value, "transition"),
    (P.ISSUED.value, A.CANCEL.value): (P.CANCELLED.value, "transition"),
    (P.ISSUED.value, A.CLOSE.value): (P.CLOSED.value, "transition"),
    #: listed so the refusal names the reason (``received_cannot_cancel``); close it instead
    (P.PARTIALLY_RECEIVED.value, A.CANCEL.value): (P.CANCELLED.value, "transition"),
    (P.PARTIALLY_RECEIVED.value, A.CLOSE.value): (P.CLOSED.value, "transition"),
    (P.RECEIVED.value, A.CLOSE.value): (P.CLOSED.value, "transition"),
}


def path(po_id: uuid.UUID) -> str:
    return f"/operations/purchasing/orders/{po_id}"


def allowed_actions(status: str) -> list[A]:
    return [A(a) for (s, a) in TRANSITIONS if s == status]


def lines_of(uow: UnitOfWork, po_id: uuid.UUID, *, for_update: bool = False) -> list[PurchaseOrderLine]:
    stmt = (
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.purchase_order_id == po_id)
        .order_by(PurchaseOrderLine.line_no)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list(uow.session.scalars(stmt))


def _line_rows(
    uow: UnitOfWork, po: PurchaseOrder, items: list[PoLineIn], *, vendor_id: uuid.UUID
) -> list[PurchaseOrderLine]:
    from app.modules.procurement.events import ProcurementPolicy
    from app.platform.org.service import stored_or_default

    policy = stored_or_default(uow, "procurement_policy")
    assert isinstance(policy, ProcurementPolicy)
    today = business_date(uow)
    rows: list[PurchaseOrderLine] = []
    for i, ln in enumerate(items, start=1):
        loc: list[str | int] = ["lines", i - 1]
        p = stock_product(uow, ln.product_id, loc)
        vi = active_item(uow, vendor_id, p.id)
        price = ln.unit_price
        override = ln.price_override_reason
        if price is None:
            if vi is None:
                raise invalid(
                    "No vendor price for this product: enter a unit price",
                    [*loc, "unit_price"],
                    "price_required",
                )
            if vi.currency != po.currency:
                raise invalid(
                    "The vendor price is in another currency", [*loc, "unit_price"], "currency_mismatch"
                )
            price = Decimal(vi.unit_price)
        elif (
            vi is not None
            and vi.currency == po.currency
            and Decimal(price) != Decimal(vi.unit_price)
            and not override
        ):
            raise invalid(
                "A price different from the vendor price needs a reason",
                [*loc, "price_override_reason"],
                "override_reason_required",
            )
        lead = vi.lead_time_days if vi is not None else None
        expected = ln.expected_date or (today + timedelta(days=lead) if lead is not None else None)
        if expected is None:
            raise invalid(
                "Enter the expected date (no lead time is known)",
                [*loc, "expected_date"],
                "expected_date_required",
            )
        if ln.requisition_line_id is not None:
            rl = uow.session.get(RequisitionLine, ln.requisition_line_id)
            if rl is None or rl.company_id != uow.actor.company_id or rl.product_id != p.id:
                raise invalid(
                    "The requisition line is for another product",
                    [*loc, "requisition_line_id"],
                    "requisition_line_mismatch",
                )
        qty = Decimal(ln.quantity)
        rows.append(
            PurchaseOrderLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                purchase_order_id=po.id,
                line_no=i,
                product_id=p.id,
                vendor_item_id=vi.id if vi is not None else None,
                requisition_line_id=ln.requisition_line_id,
                quantity=qty,
                uom_code=ln.unit or (vi.price_uom if vi is not None else None) or p.stock_uom_code,
                unit_price=Decimal(price),
                price_override_reason=override,
                line_amount=quantize_money(qty * Decimal(price), po.currency),
                lead_time_days_assumed=lead,
                expected_date=expected,
                over_receipt_tolerance_pct=ln.over_receipt_tolerance_pct
                if ln.over_receipt_tolerance_pct is not None
                else policy.default_over_receipt_tolerance_pct,
            )
        )
    return rows


def _set_lines(uow: UnitOfWork, po: PurchaseOrder, items: list[PoLineIn]) -> None:
    rows = _line_rows(uow, po, items, vendor_id=po.vendor_party_id)
    before = [ln.requisition_line_id for ln in lines_of(uow, po.id) if ln.requisition_line_id]
    for old in lines_of(uow, po.id):
        uow.session.delete(old)
    uow.flush()
    uow.add_all(rows)
    po.total_amount = sum((r.line_amount for r in rows), ZERO)
    uow.flush()
    from app.modules.procurement.requisitions import refresh_ordered

    refresh_ordered(uow, sorted({*before, *(r.requisition_line_id for r in rows if r.requisition_line_id)}))


def create_purchase_order(
    uow: UnitOfWork, data: PoCreate, *, requisition_id: uuid.UUID | None = None, origin: str = "user"
) -> PurchaseOrder:
    uow.actor.require(CREATE)
    vendor = require_vendor(uow, data.vendor_party_id)
    wh = require_warehouse(uow, data.warehouse_id)
    po = PurchaseOrder(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        po_number="PO",
        order_date=business_date(uow),
        vendor_party_id=vendor.id,
        vendor_name=vendor.display_name,
        currency=data.currency or vendor.default_currency or "INR",
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        owner_user_id=uow.actor.user_id,
        requisition_id=requisition_id,
        status=P.DRAFT.value,
        vendor_reference=data.vendor_reference,
        notes=data.notes,
        origin=origin,
    )
    po.po_number = number(uow, "procurement.purchase_order", po.id, wh.branch_id)
    po.search_text = f"{po.po_number} {vendor.display_name}".lower()
    uow.add(po)
    uow.flush()
    _set_lines(uow, po, data.lines)
    uow.audit(
        "procurement.purchase_order.create",
        resource_type="procurement.purchase_order",
        resource_id=po.id,
        resource_label=po.po_number,
    )
    return po


def _locked(uow: UnitOfWork, po_id: uuid.UUID) -> PurchaseOrder:
    po = uow.repo(PurchaseOrder).get(po_id, for_update=True)
    require_warehouse(uow, po.warehouse_id)
    return po


def update_purchase_order(uow: UnitOfWork, po_id: uuid.UUID, data: PoUpdate) -> PurchaseOrder:
    po = _locked(uow, po_id)
    uow.repo(PurchaseOrder).require_action(po, "update")  # draft only (rule) and in scope
    uow.expect_version(po, data.expected_version)
    if data.vendor_reference is not None:
        po.vendor_reference = data.vendor_reference
    if data.notes is not None:
        po.notes = data.notes
    if data.lines is not None:
        _set_lines(uow, po, data.lines)
    uow.flush()
    return po


def _emit(uow: UnitOfWork, po: PurchaseOrder, name: str) -> None:
    uow.emit(
        name,
        aggregate_id=po.id,
        aggregate_version=po.version,
        payload={"purchase_order_id": str(po.id), "po_number": po.po_number},
    )


def transition(uow: UnitOfWork, po_id: uuid.UUID, data: PoTransition) -> PurchaseOrder:
    po = _locked(uow, po_id)
    t = TRANSITIONS.get((po.status, data.action.value))
    if t is None:
        raise Conflict(
            "That action is not available now",
            code="invalid_transition",
            current_status=po.status,
            allowed_transitions=[a.value for a in allowed_actions(po.status)],
        )
    to_status, perm = t
    require_scope(uow, PurchaseOrder, po.id, perm)
    uow.expect_version(po, data.expected_version)
    lines = lines_of(uow, po.id, for_update=True)
    now = uow.now()
    action = data.action
    outstanding = sum((Decimal(ln.qty_outstanding) for ln in lines), ZERO)
    if action in (A.REJECT, A.CANCEL) or (action is A.CLOSE and outstanding > 0):
        if not (data.reason or data.reason_code):
            raise invalid("Give a reason", ["reason"], "reason_required")
    if action is A.SUBMIT:
        if not lines:
            raise invalid("Add at least one line", ["lines"], "lines_required")
        po.submitted_at, po.submitted_by = now, uow.actor.user_id
    elif action is A.APPROVE:
        if po.submitted_by == uow.actor.user_id:
            raise Forbidden(
                "The person who submitted a purchase order cannot approve it", code="approver_is_submitter"
            )
        po.approved_at, po.approved_by = now, uow.actor.user_id
    elif action is A.REJECT:
        if po.submitted_by == uow.actor.user_id:
            raise Forbidden(
                "The person who submitted a purchase order cannot decide it", code="approver_is_submitter"
            )
        po.submitted_at = po.submitted_by = None
        po.status_reason_code, po.status_reason = data.reason_code or "rejected", data.reason
    elif action is A.ISSUE:
        po.issued_at, po.issued_by = now, uow.actor.user_id
    elif action is A.CANCEL:
        if any(Decimal(ln.qty_received) > 0 for ln in lines):
            raise Conflict(
                "Goods were already received: close the order instead", code="received_cannot_cancel"
            )
        po.cancelled_at = now
        po.status_reason_code, po.status_reason = data.reason_code or "cancelled", data.reason
    elif action is A.CLOSE:
        for ln in lines:
            rest = Decimal(ln.qty_outstanding)
            if rest > 0:
                ln.qty_cancelled = Decimal(ln.qty_cancelled) + rest
        po.closed_at = now
        if outstanding > 0:
            po.status_reason_code, po.status_reason = data.reason_code or "short_closed", data.reason
    po.status = to_status
    uow.flush()
    if action is A.APPROVE:
        po.approved_version = po.version
        uow.flush()
    name = {
        A.APPROVE: ev.PO_APPROVED,
        A.ISSUE: ev.PO_ISSUED,
        A.CLOSE: ev.PO_CLOSED,
        A.CANCEL: ev.PO_CANCELLED,
    }.get(action)
    if name:
        _emit(uow, po, name)
    if action in (A.CANCEL, A.CLOSE):
        from app.modules.procurement.requisitions import refresh_ordered

        refresh_ordered(uow, sorted({ln.requisition_line_id for ln in lines if ln.requisition_line_id}))
    uow.audit(
        f"procurement.purchase_order.{action.value}",
        resource_type="procurement.purchase_order",
        resource_id=po.id,
        resource_label=po.po_number,
        reason=data.reason,
        details={"to_status": to_status, "reason_code": data.reason_code},
    )
    return po


def _line(uow: UnitOfWork, po: PurchaseOrder, line_id: uuid.UUID) -> PurchaseOrderLine:
    ln = uow.session.scalars(
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.id == line_id, PurchaseOrderLine.purchase_order_id == po.id)
        .with_for_update()
    ).first()
    if ln is None:
        raise NotFound(code="not_found", resource_type="procurement.purchase_order_line")
    return ln


def change_expected_date(
    uow: UnitOfWork, po_id: uuid.UUID, line_id: uuid.UUID, data: ExpectedDateChange
) -> PurchaseOrder:
    """Move a line's expected date while the vendor still owes goods; emits ``expected_date_changed``."""
    po = _locked(uow, po_id)
    require_scope(uow, PurchaseOrder, po.id, "update")
    ln = _line(uow, po, line_id)
    uow.expect_version(ln, data.expected_version)
    if po.status not in OPEN_VALUES | {P.DRAFT.value, P.PENDING_APPROVAL.value}:
        raise Conflict("The order no longer expects goods", code="invalid_status", current_status=po.status)
    if ln.expected_date == data.expected_date:
        return po
    before = ln.expected_date
    ln.expected_date = data.expected_date
    ln.overdue_notified_at = None
    uow.flush()
    uow.emit(
        ev.PO_LINE_DATE_CHANGED,
        aggregate_id=ln.id,
        aggregate_version=ln.version,
        payload={
            "purchase_order_id": str(po.id),
            "po_line_id": str(ln.id),
            "from_date": before.isoformat(),
            "to_date": data.expected_date.isoformat(),
        },
    )
    uow.audit(
        "procurement.purchase_order.expected_date_changed",
        resource_type="procurement.purchase_order",
        resource_id=po.id,
        resource_label=po.po_number,
        reason=data.reason,
        details={"line_no": ln.line_no, "from": before.isoformat(), "to": data.expected_date.isoformat()},
    )
    return po


def cancel_line_quantity(
    uow: UnitOfWork, po_id: uuid.UUID, line_id: uuid.UUID, data: LineCancel
) -> PurchaseOrder:
    po = _locked(uow, po_id)
    require_scope(uow, PurchaseOrder, po.id, "transition")
    ln = _line(uow, po, line_id)
    uow.expect_version(ln, data.expected_version)
    if po.status not in OPEN_VALUES:
        raise Conflict(
            "Only an approved or issued order's lines are cancelled",
            code="invalid_status",
            current_status=po.status,
        )
    if Decimal(data.quantity) > Decimal(ln.qty_outstanding):
        raise invalid("More than is outstanding", ["quantity"], "exceeds_outstanding")
    ln.qty_cancelled = Decimal(ln.qty_cancelled) + Decimal(data.quantity)
    uow.flush()
    recompute_status(uow, po)
    uow.audit(
        "procurement.purchase_order.cancel_line",
        resource_type="procurement.purchase_order",
        resource_id=po.id,
        resource_label=po.po_number,
        reason=data.reason,
        details={"line_no": ln.line_no},
    )
    return po


def recompute_status(uow: UnitOfWork, po: PurchaseOrder) -> None:
    """After receipts, QC or line cancellations: received when nothing is outstanding, else partially received."""
    if po.status not in OPEN_VALUES and po.status != P.RECEIVED.value:
        return
    lines = lines_of(uow, po.id)
    for ln in lines:
        uow.session.refresh(ln, ["qty_outstanding"])
    outstanding = sum((Decimal(ln.qty_outstanding) for ln in lines), ZERO)
    received_any = any(Decimal(ln.qty_received) > 0 for ln in lines)
    if outstanding <= 0:
        new = P.RECEIVED.value
    elif received_any:
        new = P.PARTIALLY_RECEIVED.value
    else:
        new = po.status
    if new != po.status:
        po.status = new
        uow.flush()


def convert_requisition(uow: UnitOfWork, requisition_id: uuid.UUID, data: ConvertToPo) -> PurchaseOrder:
    """A draft PO for one vendor from the approved requisition's unordered remainder (chosen lines or all)."""
    from app.modules.procurement.requisitions import lines_of as req_lines

    uow.actor.require(CREATE)
    from app.modules.procurement.requisitions import get_visible

    r = get_visible(uow, requisition_id, for_update=True)
    uow.expect_version(r, data.expected_version)
    if r.status != "approved":
        raise Conflict(
            "Only an approved requisition is converted", code="invalid_status", current_status=r.status
        )
    wanted = set(data.line_ids or [])
    items: list[PoLineIn] = []
    for ln in req_lines(uow, r.id):
        if wanted and ln.id not in wanted:
            continue
        rest = Decimal(ln.quantity) - Decimal(ln.qty_ordered)
        if rest <= 0:
            continue
        items.append(
            PoLineIn(
                product_id=ln.product_id,
                quantity=rest,
                unit=ln.uom_code,
                unit_price=data.unit_prices.get(ln.id),
                price_override_reason="price from the requisition conversion"
                if ln.id in data.unit_prices
                else None,
                expected_date=ln.required_by,
                requisition_line_id=ln.id,
            )
        )
    if not items:
        raise Conflict("Nothing left to order on this requisition", code="nothing_to_order")
    return create_purchase_order(
        uow,
        PoCreate(vendor_party_id=data.vendor_party_id, warehouse_id=r.warehouse_id, lines=items),
        requisition_id=r.id,
    )


# ---- overdue sweep ---------------------------------------------------------------------------------------------------
def sweep_overdue(uow: UnitOfWork) -> int:
    """``became_overdue`` once per PO for lines whose expected date has passed with goods still outstanding."""
    today = business_date(uow)
    rows = list(
        uow.session.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(
                PurchaseOrder.company_id == uow.actor.company_id,
                PurchaseOrder.status.in_(OPEN_VALUES),
                PurchaseOrderLine.expected_date < today,
                PurchaseOrderLine.qty_outstanding > 0,
                PurchaseOrderLine.overdue_notified_at.is_(None),
            )
            .order_by(PurchaseOrder.po_number, PurchaseOrderLine.line_no)
            .with_for_update(of=PurchaseOrderLine, skip_locked=True)
        ).all()
    )
    by_po: dict[uuid.UUID, tuple[PurchaseOrder, list[PurchaseOrderLine]]] = {}
    for ln, po in rows:
        by_po.setdefault(po.id, (po, []))[1].append(ln)
    now = uow.now()
    for po, lines in by_po.values():
        for ln in lines:
            ln.overdue_notified_at = now
        uow.flush()
        uow.emit(
            ev.PO_OVERDUE,
            aggregate_id=po.id,
            aggregate_version=po.version,
            payload={"purchase_order_id": str(po.id), "po_line_ids": [str(ln.id) for ln in lines]},
        )
    return len(by_po)


def is_line_overdue(ln: PurchaseOrderLine, po_status: str, today: date) -> bool:
    return po_status in OPEN_VALUES and ln.expected_date < today and Decimal(ln.qty_outstanding) > 0


# ---- reads ------------------------------------------------------------------------------------------------------------
def _receivable(ln: PurchaseOrderLine) -> Decimal:
    cap_qty = Decimal(ln.quantity) * (1 + Decimal(ln.over_receipt_tolerance_pct) / 100) - Decimal(
        ln.qty_cancelled
    )
    return max(cap_qty - (Decimal(ln.qty_received) - Decimal(ln.qty_rejected)), ZERO)


def receivable(ln: PurchaseOrderLine) -> Decimal:
    return _receivable(ln)


def _summaries(uow: UnitOfWork, rows: list[PurchaseOrder]) -> list[dict]:  # type: ignore[type-arg]
    today = business_date(uow)
    vendors = party_briefs(uow, [r.vendor_party_id for r in rows])
    whs = warehouse_briefs(uow, [r.warehouse_id for r in rows])
    users = user_briefs(uow, [r.owner_user_id for r in rows])
    nxt: dict[uuid.UUID, date] = {}
    late: set[uuid.UUID] = set()
    if rows:
        for po_id, d, overdue in uow.session.execute(
            select(
                PurchaseOrderLine.purchase_order_id,
                func.min(PurchaseOrderLine.expected_date),
                func.bool_or(PurchaseOrderLine.expected_date < today),
            )
            .where(
                PurchaseOrderLine.purchase_order_id.in_([r.id for r in rows]),
                PurchaseOrderLine.qty_outstanding > 0,
            )
            .group_by(PurchaseOrderLine.purchase_order_id)
        ).all():
            nxt[po_id] = d
            if overdue:
                late.add(po_id)
    return [
        {
            "id": r.id,
            "po_number": r.po_number,
            "status": r.status,
            "vendor": vendors[r.vendor_party_id],
            "warehouse": whs[r.warehouse_id],
            "owner": users[r.owner_user_id],
            "currency": r.currency,
            "total_amount": money4(r.total_amount),
            "order_date": r.order_date,
            "next_expected_date": nxt.get(r.id) if r.status in OPEN_VALUES else None,
            "is_overdue": r.status in OPEN_VALUES and r.id in late,
            "path": path(r.id),
            "version": r.version,
        }
        for r in rows
    ]


def list_purchase_orders(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    vendor_party_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[PoSummary]:
    repo = uow.repo(PurchaseOrder)
    filters = []
    if status:
        filters.append(PurchaseOrder.status.in_(status))
    if vendor_party_id is not None:
        filters.append(PurchaseOrder.vendor_party_id == vendor_party_id)
    if overdue_only:
        today = business_date(uow)
        filters.append(PurchaseOrder.status.in_(OPEN_VALUES))
        filters.append(
            PurchaseOrder.id.in_(
                select(PurchaseOrderLine.purchase_order_id).where(
                    PurchaseOrderLine.expected_date < today, PurchaseOrderLine.qty_outstanding > 0
                )
            )
        )
    if q and (f := repo.search_filter(q, ["search_text"])) is not None:
        filters.append(f)
    page = repo.list(
        *filters,
        order_by=[PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()],
        limit=limit,
        offset=offset,
    )
    items = [PoSummary(**d) for d in _summaries(uow, list(page.items))]
    return Page[PoSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def line_reads(uow: UnitOfWork, po: PurchaseOrder, lines: list[PurchaseOrderLine]) -> list[PoLineRead]:
    today = business_date(uow)
    products = product_briefs(uow, [ln.product_id for ln in lines])
    return [
        PoLineRead(
            id=ln.id,
            line_no=ln.line_no,
            product=products[ln.product_id],
            quantity=plain(ln.quantity),
            unit=ln.uom_code,
            unit_price=money4(ln.unit_price),
            price_override_reason=ln.price_override_reason,
            line_amount=money4(ln.line_amount),
            lead_time_days_assumed=ln.lead_time_days_assumed,
            expected_date=ln.expected_date,
            is_overdue=is_line_overdue(ln, po.status, today),
            over_receipt_tolerance_pct=Decimal(ln.over_receipt_tolerance_pct),
            qty_received=plain(ln.qty_received),
            qty_accepted=plain(ln.qty_accepted),
            qty_rejected=plain(ln.qty_rejected),
            qty_pending_qc=plain(
                Decimal(ln.qty_received) - Decimal(ln.qty_accepted) - Decimal(ln.qty_rejected)
            ),
            qty_cancelled=plain(ln.qty_cancelled),
            qty_billed=plain(ln.qty_billed),
            qty_outstanding=plain(ln.qty_outstanding),
            qty_receivable=plain(_receivable(ln)) if po.status in OPEN_VALUES else Decimal(0),
            requisition_line_id=ln.requisition_line_id,
            version=ln.version,
        )
        for ln in lines
    ]


def detail(uow: UnitOfWork, po: PurchaseOrder) -> PoDetail:
    lines = lines_of(uow, po.id)
    users = user_briefs(uow, [po.submitted_by, po.approved_by])
    receipts = uow.session.execute(
        select(GoodsReceipt.id, GoodsReceipt.grn_number, GoodsReceipt.status)
        .where(GoodsReceipt.purchase_order_id == po.id)
        .order_by(GoodsReceipt.grn_number)
    ).all()
    bills = uow.session.execute(
        select(VendorBill.id, VendorBill.bill_number, VendorBill.status)
        .where(VendorBill.purchase_order_id == po.id)
        .order_by(VendorBill.created_at)
    ).all()
    req = uow.session.get(Requisition, po.requisition_id) if po.requisition_id else None
    repo = uow.repo(PurchaseOrder)

    def scoped(action: str) -> bool:
        return (
            uow.session.scalar(select(PurchaseOrder.id).where(PurchaseOrder.id == po.id, repo.clause(action)))
            is not None
        )

    allowed = allowed_actions(po.status)
    caps = {}
    for a in A:
        t = TRANSITIONS.get((po.status, a.value))
        if t is None:
            caps[a.value] = cap(False, "invalid_status")
            continue
        ok = scoped(t[1])
        reason = "permission_denied"
        if ok and a in (A.APPROVE, A.REJECT) and po.submitted_by == uow.actor.user_id:
            ok, reason = False, "approver_is_submitter"
        if ok and a is A.CANCEL and any(Decimal(ln.qty_received) > 0 for ln in lines):
            ok, reason = False, "received_cannot_cancel"
        caps[a.value] = cap(ok, reason)
    caps["update"] = cap(
        scoped("update") and po.status == P.DRAFT.value,
        "invalid_status" if scoped("update") else "permission_denied",
    )
    caps["change_expected_date"] = cap(
        scoped("update") and po.status in OPEN_VALUES | {P.DRAFT.value, P.PENDING_APPROVAL.value},
        "invalid_status" if scoped("update") else "permission_denied",
    )
    caps["receive"] = cap(
        uow.actor.can("procurement.goods_receipt.post") and po.status in OPEN_VALUES,
        "invalid_status" if uow.actor.can("procurement.goods_receipt.post") else "permission_denied",
    )
    caps["bill"] = cap(
        uow.actor.can("procurement.vendor_bill.create") and any(Decimal(ln.qty_accepted) > 0 for ln in lines),
        "nothing_accepted" if uow.actor.can("procurement.vendor_bill.create") else "permission_denied",
    )
    base = _summaries(uow, [po])[0]
    return PoDetail(
        **base,
        vendor_reference=po.vendor_reference,
        notes=po.notes,
        requisition=DocLink(
            id=req.id,
            number=req.requisition_number,
            status=req.status,
            path=f"/operations/purchasing/requisitions/{req.id}",
        )
        if req
        else None,
        submitted_by=users.get(po.submitted_by) if po.submitted_by else None,
        submitted_at=po.submitted_at,
        approved_by=users.get(po.approved_by) if po.approved_by else None,
        approved_at=po.approved_at,
        issued_at=po.issued_at,
        closed_at=po.closed_at,
        cancelled_at=po.cancelled_at,
        status_reason_code=po.status_reason_code,
        status_reason=po.status_reason,
        lines=line_reads(uow, po, lines),
        receipts=[
            DocLink(id=i, number=n, status=s, path=f"/operations/purchasing/receipts/{i}")
            for i, n, s in receipts
        ],
        bills=[
            DocLink(id=i, number=n, status=s, path=f"/operations/purchasing/orders/{po.id}#bill-{i}")
            for i, n, s in bills
        ],
        allowed_transitions=allowed,
        capabilities=caps,
    )


def get_purchase_order(uow: UnitOfWork, po_id: uuid.UUID) -> PoDetail:
    po = uow.repo(PurchaseOrder).get(po_id)
    require_warehouse(uow, po.warehouse_id)
    return detail(uow, po)


def get_by_number(uow: UnitOfWork, po_number: str) -> PoDetail:
    po = uow.repo(PurchaseOrder).get_by_key(po_number)
    require_warehouse(uow, po.warehouse_id)
    return detail(uow, po)
