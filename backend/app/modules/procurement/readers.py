"""Source readers for tasks, briefings and the agent: ``procurement.purchase_order`` (number, vendor, status, the next
expected date, late lines) and ``procurement.goods_receipt``. Ids, numbers, names, dates and counts only (no prices
or amounts)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.procurement.common import business_date
from app.modules.procurement.enums import PO_OPEN_FOR_RECEIPT
from app.modules.procurement.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

OPEN = frozenset(s.value for s in PO_OPEN_FOR_RECEIPT)


def read_po_facts(uow: UnitOfWork, po_id: uuid.UUID) -> SourceFacts | None:
    try:
        po = uow.repo(PurchaseOrder).get(po_id)
    except NotFound:
        return None
    today = business_date(uow)
    lines = list(
        uow.session.scalars(
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.purchase_order_id == po.id)
            .order_by(PurchaseOrderLine.line_no)
        )
    )
    open_lines = [ln for ln in lines if Decimal(ln.qty_outstanding) > 0] if po.status in OPEN else []
    late = [ln for ln in open_lines if ln.expected_date < today]
    next_date: date | None = min((ln.expected_date for ln in open_lines), default=None)
    return SourceFacts(
        source_type="procurement.purchase_order",
        source_id=po.id,
        version=po.version,
        label=f"{po.po_number} · {po.vendor_name}",
        status=po.status,
        owner_user_id=po.owner_user_id,
        branch_id=po.branch_id,
        required_permission="procurement.purchase_order.read",
        canonical_path=f"/operations/purchasing/orders/{po.id}",
        is_closed=po.status not in OPEN,
        updated_at=po.updated_at,
        facts={
            "po_number": po.po_number,
            "vendor_name": po.vendor_name,
            "open_line_count": len(open_lines),
            "late_line_count": len(late),
            "late_line_ids": [str(ln.id) for ln in late],
            "late_line_nos": [ln.line_no for ln in late],
            "next_expected_date": next_date.isoformat() if next_date else None,
            "earliest_late_date": min((ln.expected_date for ln in late), default=None).isoformat()
            if late
            else None,  # type: ignore[union-attr]
        },
    )


def read_grn_facts(uow: UnitOfWork, grn_id: uuid.UUID) -> SourceFacts | None:
    try:
        grn = uow.repo(GoodsReceipt).get(grn_id)
    except NotFound:
        return None
    return SourceFacts(
        source_type="procurement.goods_receipt",
        source_id=grn.id,
        version=grn.version,
        label=grn.grn_number,
        status=grn.status,
        owner_user_id=None,
        branch_id=grn.branch_id,
        required_permission="procurement.goods_receipt.read",
        canonical_path=f"/operations/purchasing/receipts/{grn.id}",
        is_closed=grn.status != "draft",
        updated_at=grn.updated_at,
        facts={"grn_number": grn.grn_number, "received_on": grn.received_on.isoformat()},
    )


READERS = {"procurement.purchase_order": read_po_facts, "procurement.goods_receipt": read_grn_facts}
