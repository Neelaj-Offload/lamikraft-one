"""Procurement public service: the entry point for routers, jobs, the inventory shortage state and other modules.

Commands live in ``vendor_items``, ``requisitions``, ``purchase_orders``, ``receiving`` and ``matching``; this module
re-exports them and adds the cross-module hooks registered in the manifest:
- ``late_supply_causes``: inventory cause provider (late PO lines appear in a shortage's ``caused_by``);
- ``pairs_for_event``: inventory pair resolver for ``procurement.*`` events (which product x warehouse they touch);
- ``open_supply``: outstanding approved supply per product and warehouse (for feasibility and planners).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.procurement import matching, purchase_orders, receiving, requisitions, vendor_items
from app.modules.procurement.enums import PO_OPEN_FOR_RECEIPT
from app.modules.procurement.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

OPEN = tuple(s.value for s in PO_OPEN_FOR_RECEIPT)
PO_LINE = "procurement.purchase_order_line"

save_vendor_item = vendor_items.save_vendor_item
list_vendor_items = vendor_items.list_vendor_items
create_requisition = requisitions.create_requisition
decide_requisition = requisitions.decide
get_requisition = requisitions.get_requisition
list_requisitions = requisitions.list_requisitions
create_purchase_order = purchase_orders.create_purchase_order
update_purchase_order = purchase_orders.update_purchase_order
transition_purchase_order = purchase_orders.transition
change_expected_date = purchase_orders.change_expected_date
cancel_line_quantity = purchase_orders.cancel_line_quantity
convert_requisition = purchase_orders.convert_requisition
get_purchase_order = purchase_orders.get_purchase_order
list_purchase_orders = purchase_orders.list_purchase_orders
create_receipt = receiving.create_receipt
post_receipt = receiving.post_receipt
get_receipt = receiving.get_receipt
list_receipts = receiving.list_receipts
create_bill = matching.create_bill
match_bill = matching.match_bill
hand_off_bill = matching.hand_off
get_bill = matching.get_bill
list_bills = matching.list_bills


def late_supply_causes(
    uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID
) -> list[dict[str, str]]:
    """Supply that has not arrived while a shortage exists: open PO lines for the product into the warehouse with goods
    outstanding (``{type, id}`` refs; the shortage only asks while it is short, so these lines are late for it)."""
    rows = uow.session.scalars(
        select(PurchaseOrderLine.id)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrder.company_id == uow.actor.company_id,
            PurchaseOrder.status.in_(OPEN),
            PurchaseOrder.warehouse_id == warehouse_id,
            PurchaseOrderLine.product_id == product_id,
            PurchaseOrderLine.qty_outstanding > 0,
        )
    )
    return [{"type": PO_LINE, "id": str(i)} for i in rows]


def open_supply(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
    """Outstanding quantity on approved / issued / partially received POs (in the PO lines' units)."""
    return Decimal(
        uow.session.scalar(
            select(func.coalesce(func.sum(PurchaseOrderLine.qty_outstanding), 0))
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(
                PurchaseOrder.company_id == uow.actor.company_id,
                PurchaseOrder.status.in_(OPEN),
                PurchaseOrder.warehouse_id == warehouse_id,
                PurchaseOrderLine.product_id == product_id,
            )
        )
        or 0
    )


def _uuid(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def pairs_for_event(uow: UnitOfWork, event: DomainEvent) -> set[tuple[uuid.UUID, uuid.UUID]]:
    payload = event.payload or {}
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if event.event_type == "procurement.goods_receipt.posted":
        grn = uow.session.get(GoodsReceipt, _uuid(payload.get("goods_receipt_id")))
        if grn is not None:
            for pid in uow.session.scalars(
                select(GoodsReceiptLine.product_id).where(GoodsReceiptLine.goods_receipt_id == grn.id)
            ):
                pairs.add((pid, grn.warehouse_id))
        return pairs
    po = uow.session.get(PurchaseOrder, _uuid(payload.get("purchase_order_id")))
    if po is None:
        return pairs
    stmt = select(PurchaseOrderLine.product_id).where(PurchaseOrderLine.purchase_order_id == po.id)
    if (line_id := _uuid(payload.get("po_line_id"))) is not None:
        stmt = stmt.where(PurchaseOrderLine.id == line_id)
    for pid in uow.session.scalars(stmt):
        pairs.add((pid, po.warehouse_id))
    return pairs
