"""Factory orders as stock work in progress (module 4).

Lamikraft orders finished pieces from its factories (Crown, Stonecraft) as purchase orders. What is still to come in is
"work in progress" for the stock screens: the outstanding quantity of open purchase-order lines (approved, issued or
partly received) for finished products. ``on_order`` feeds the stock-by-category view through the inventory
provider hook; ``factory_orders`` lists the lines with vendor, status and expected date.
Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.catalogue.models import Product
from app.modules.procurement.enums import PO_OPEN_FOR_RECEIPT
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from app.platform.service import query
from app.platform.uow import UnitOfWork

OPEN = [s.value for s in PO_OPEN_FOR_RECEIPT]


def on_order(uow: UnitOfWork, product_ids: Iterable[uuid.UUID]) -> dict[tuple[uuid.UUID, uuid.UUID | None], Decimal]:
    ids = list(set(product_ids))
    if not ids:
        return {}
    rows = uow.session.execute(
        select(PurchaseOrderLine.product_id, PurchaseOrder.warehouse_id, func.sum(PurchaseOrderLine.qty_outstanding))
        .join(PurchaseOrder, and_(PurchaseOrder.id == PurchaseOrderLine.purchase_order_id,
                                  PurchaseOrder.company_id == PurchaseOrderLine.company_id))
        .where(PurchaseOrderLine.company_id == uow.actor.company_id, PurchaseOrderLine.product_id.in_(ids),
               PurchaseOrder.status.in_(OPEN), PurchaseOrderLine.qty_outstanding > 0)
        .group_by(PurchaseOrderLine.product_id, PurchaseOrder.warehouse_id)
    ).all()
    return {(p, w): Decimal(q) for p, w, q in rows}


class FactoryOrderLine(BaseModel):
    purchase_order_id: uuid.UUID
    po_number: str
    status: str
    vendor_party_id: uuid.UUID
    vendor_name: str
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    product_key: str
    product_name: str
    quantity: str
    outstanding: str
    uom_code: str
    order_date: date
    expected_date: date
    path: str


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


@query("procurement.purchase_order.read")
def factory_orders(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0) -> Page[FactoryOrderLine]:
    """Open purchase-order lines for finished products, soonest expected first (scoped like purchase orders)."""
    from app.modules.parties.models import Party

    repo = uow.repo(PurchaseOrder)
    conds = [PurchaseOrder.status.in_(OPEN), PurchaseOrderLine.qty_outstanding > 0, Product.item_class == "finished",
             repo.clause("read")]
    if product_id:
        conds.append(PurchaseOrderLine.product_id == product_id)
    stmt = (
        select(PurchaseOrder, PurchaseOrderLine, Product.product_key, Product.product_name, Party.display_name)
        .join(PurchaseOrderLine, and_(PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
                                      PurchaseOrderLine.company_id == PurchaseOrder.company_id))
        .join(Product, and_(Product.id == PurchaseOrderLine.product_id, Product.company_id == PurchaseOrderLine.company_id))
        .join(Party, Party.id == PurchaseOrder.vendor_party_id)
        .where(PurchaseOrder.company_id == uow.actor.company_id, *conds)
    )
    total = uow.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = uow.session.execute(
        stmt.order_by(PurchaseOrderLine.expected_date, PurchaseOrder.po_number, PurchaseOrderLine.line_no)
        .limit(max(1, min(limit, MAX_LIMIT))).offset(max(0, offset))
    ).all()
    items = [
        FactoryOrderLine(
            purchase_order_id=po.id, po_number=po.po_number, status=po.status, vendor_party_id=po.vendor_party_id,
            vendor_name=vendor, warehouse_id=po.warehouse_id, product_id=line.product_id, product_key=key,
            product_name=name, quantity=_fmt(line.quantity), outstanding=_fmt(line.qty_outstanding), uom_code=line.uom_code,
            order_date=po.order_date, expected_date=line.expected_date, path=f"/operations/purchasing/orders/{po.id}",
        )
        for po, line, key, name, vendor in rows
    ]
    return Page[FactoryOrderLine](items=items, total=int(total), limit=limit, offset=offset)
