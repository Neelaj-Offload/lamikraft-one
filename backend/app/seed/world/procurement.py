"""Fixture purchasing (docs/architecture/fixtures.md §8, Slice 4), created through the procurement services:

- vendor item: Kaveri Timber Supplies sells LK-WB-1800 (vendor code KTS-WB18, lead time 10 days, INR 4,850.0000 per
  sheet; Priya, D-30 10:00);
- purchase order **PO-2026-0001**: Kaveri, line 1 LK-WB-1800 x 60 sheets into WH-MAIN, expected D0; created and
  submitted by Priya (D-9 10:00), approved by Sahil (D-9 11:30), issued by Priya (D-9 12:00); the expected date moved
  from D0 to D0+3 at D-1 11:03 (the vendor's confirmation slipped).
Re-running is idempotent (``origin = 'seed'``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.modules.procurement import purchase_orders, vendor_items
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderLine
from app.modules.procurement.schemas import ExpectedDateChange, PoCreate, PoLineIn, PoTransition, VendorItemIn
from app.platform.authz.actors import actor_for_member
from app.platform.uow import UnitOfWork
from app.seed.context import D0, SeedContext
from app.seed.world import keys
from app.seed.world.parties import at_ist

PO_REF = "PO_KAVERI"


def _uow(ctx: SeedContext, person: str) -> UnitOfWork:
    return UnitOfWork(actor_for_member(ctx.company_id, ctx.ref(person), channel="cli"), clock=ctx.clock)


def seed_procurement(ctx: SeedContext) -> None:
    vendor, board = ctx.ref("KAVERI"), ctx.ref("WALNUT_BOARD")
    with _uow(ctx, keys.USERS.PRIYA) as uow:
        existing = uow.session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.company_id == ctx.company_id, PurchaseOrder.origin == "seed"
            )
        ).first()
        if existing is not None:
            ctx.refs[PO_REF] = existing.id
            return
    ctx.at(at_ist(-30, 10, 0))
    with _uow(ctx, keys.USERS.PRIYA) as uow:
        vendor_items.save_vendor_item(
            uow,
            VendorItemIn(
                vendor_party_id=vendor,
                product_id=board,
                vendor_code="KTS-WB18",
                lead_time_days=10,
                unit_price=Decimal("4850.0000"),
                currency="INR",
                price_uom="sheets",
            ),
            origin="seed",
        )
    ctx.at(at_ist(-9, 10, 0))
    d0 = D0.date()
    with _uow(ctx, keys.USERS.PRIYA) as uow:
        po = purchase_orders.create_purchase_order(
            uow,
            PoCreate(
                vendor_party_id=vendor,
                warehouse_id=ctx.ref(keys.WAREHOUSE_REFS.MAIN),
                lines=[PoLineIn(product_id=board, quantity=Decimal(60), expected_date=d0)],
            ),
            origin="seed",
        )
        po = purchase_orders.transition(
            uow, po.id, PoTransition(action="submit", expected_version=po.version)
        )
        po_id = po.id
    ctx.refs[PO_REF] = po_id
    ctx.at(at_ist(-9, 11, 30))
    with _uow(ctx, keys.USERS.SAHIL) as uow:
        po = uow.session.get(PurchaseOrder, po_id)
        assert po is not None
        purchase_orders.transition(uow, po_id, PoTransition(action="approve", expected_version=po.version))
    ctx.at(at_ist(-9, 12, 0))
    with _uow(ctx, keys.USERS.PRIYA) as uow:
        po = uow.session.get(PurchaseOrder, po_id)
        assert po is not None
        purchase_orders.transition(uow, po_id, PoTransition(action="issue", expected_version=po.version))
    ctx.at(at_ist(-1, 11, 3))
    with _uow(ctx, keys.USERS.PRIYA) as uow:
        line = uow.session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po_id)
        ).one()
        ctx.refs["PO_KAVERI_LINE1"] = line.id
        purchase_orders.change_expected_date(
            uow,
            po_id,
            line.id,
            ExpectedDateChange(
                expected_version=line.version,
                expected_date=d0 + timedelta(days=3),
                reason="Vendor confirmed dispatch on Thursday",
            ),
        )
