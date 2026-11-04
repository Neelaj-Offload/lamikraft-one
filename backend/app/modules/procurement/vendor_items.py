"""Vendor items: what a vendor sells (vendor code, lead time, price with currency). Saving a vendor item for a
(vendor, product) that already has an active row creates a new version and supersedes the old one, so price history
is kept and purchase-order lines keep pointing at the version they were priced from."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.procurement.common import (
    business_date,
    money4,
    party_briefs,
    product_briefs,
    require_vendor,
    stock_product,
)
from app.modules.procurement.models import VendorItem
from app.modules.procurement.policies import VI_MANAGE, VI_READ
from app.modules.procurement.schemas import VendorItemIn, VendorItemRead
from app.platform.uow import UnitOfWork


def reads(uow: UnitOfWork, rows: list[VendorItem]) -> list[VendorItemRead]:
    parties = party_briefs(uow, [r.vendor_party_id for r in rows])
    products = product_briefs(uow, [r.product_id for r in rows])
    return [
        VendorItemRead(
            id=r.id,
            vendor=parties[r.vendor_party_id],
            product=products[r.product_id],
            vendor_code=r.vendor_code,
            lead_time_days=r.lead_time_days,
            unit_price=money4(r.unit_price),
            currency=r.currency,
            price_uom=r.price_uom,
            min_order_qty=Decimal(r.min_order_qty) if r.min_order_qty is not None else None,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            is_active=r.is_active,
            superseded_by_id=r.superseded_by_id,
            notes=r.notes,
            version=r.version,
        )
        for r in rows
    ]


def list_vendor_items(
    uow: UnitOfWork,
    *,
    vendor_party_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    include_history: bool = False,
) -> list[VendorItemRead]:
    """Vendor items (``procurement.vendor_item.read``); a vendor filter needs the vendor to be visible (404)."""
    uow.actor.require(VI_READ)
    stmt = select(VendorItem).where(VendorItem.company_id == uow.actor.company_id)
    if vendor_party_id is not None:
        require_vendor(uow, vendor_party_id)
        stmt = stmt.where(VendorItem.vendor_party_id == vendor_party_id)
    if product_id is not None:
        stmt = stmt.where(VendorItem.product_id == product_id)
    if not include_history:
        stmt = stmt.where(VendorItem.is_active.is_(True))
    rows = list(uow.session.scalars(stmt.order_by(VendorItem.created_at.desc(), VendorItem.id).limit(500)))
    return reads(uow, rows)


def active_item(uow: UnitOfWork, vendor_party_id: uuid.UUID, product_id: uuid.UUID) -> VendorItem | None:
    return uow.session.scalars(
        select(VendorItem).where(
            VendorItem.company_id == uow.actor.company_id,
            VendorItem.vendor_party_id == vendor_party_id,
            VendorItem.product_id == product_id,
            VendorItem.is_active.is_(True),
        )
    ).first()


def save_vendor_item(uow: UnitOfWork, data: VendorItemIn, *, origin: str = "user") -> VendorItem:
    """Create the vendor item, or a new version superseding the active one for the same vendor and product."""
    uow.actor.require(VI_MANAGE)
    vendor = require_vendor(uow, data.vendor_party_id)
    product = stock_product(uow, data.product_id, [])
    uow.advisory_xact_lock("procurement.vendor_item", f"{vendor.id}:{product.id}")
    current = active_item(uow, vendor.id, product.id)
    row = VendorItem(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        vendor_party_id=vendor.id,
        product_id=product.id,
        vendor_code=data.vendor_code,
        lead_time_days=data.lead_time_days,
        unit_price=data.unit_price,
        currency=data.currency,
        price_uom=data.price_uom or product.stock_uom_code or "pcs",
        min_order_qty=data.min_order_qty,
        valid_from=data.valid_from or business_date(uow),
        is_active=True,
        notes=data.notes,
        origin=origin,
    )
    if current is not None:
        current.is_active = False
        current.valid_to = max(current.valid_from, row.valid_from)
        uow.flush()
    uow.add(row)
    uow.flush()
    if current is not None:
        current.superseded_by_id = row.id
        uow.flush()
    uow.audit(
        "procurement.vendor_item.manage",
        resource_type="procurement.vendor_item",
        resource_id=row.id,
        resource_label=f"{vendor.display_name} · {product.product_key}",
        details={"supersedes": str(current.id) if current else None},
    )
    return row


def get_vendor_item(uow: UnitOfWork, item_id: uuid.UUID) -> VendorItem:
    uow.actor.require(VI_READ)
    row = uow.session.scalars(
        select(VendorItem).where(VendorItem.company_id == uow.actor.company_id, VendorItem.id == item_id)
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="procurement.vendor_item")
    return row
