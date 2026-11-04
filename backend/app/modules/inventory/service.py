"""Inventory public service: the only entry point for routers, tools, jobs and other modules (challans, orders,
and the later procurement / production / logistics lanes).

Posting and reservations
- ``post_movement(uow, PostingRequest) -> PostingReceipt`` and ``reverse_posting(uow, posting_id, ...)``: the ledger.
- ``reserve(uow, ...) -> ReserveResult``, ``release(uow, reservation_id, ...)``, ``release_for_demand``,
  ``active_for_demand``, ``reserved_by_demand``: reservations (the caller locks its demand line first).
- ``stock_quantity(uow, product_id, qty, uom)``: a quantity in the product's stock unit.
Locations and policy
- ``resolve_warehouse(uow, warehouse_id | None)``, ``default_location``, ``warehouse_location``, ``holding_location``,
  ``office_location``, ``company_location``: where stock sits; ``challan_postings_enabled(uow)``: go-live switch.
Extension points (register in a manifest ``on_load``)
- ``register_demand_provider(name, fn)``: open demand per (product, warehouse) for the shortage state.
- ``register_pair_resolver(event_prefix, fn)``: which (product, warehouse) pairs a module's event touches.
- ``register_cause_provider(name, fn)``: supply-side causes (late PO lines) for ``caused_by``.
Production (Slice-4 production lane)
- ``wip_location(uow, warehouse_id)``: the warehouse's WIP location (issue internal -> WIP, consume WIP -> production).
- ``record_measured_lot(uow, ...)``: a new lot with measured dimensions (offcuts, board lots), ``inventory.lot.measured``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.inventory.events import InventoryPolicy
from app.modules.inventory.locations import (
    company_location,
    default_location,
    ensure_company_locations,
    get_location,
    holding_location,
    office_location,
    warehouse_location,
    wip_location,
)
from app.modules.inventory.models import StockMovement, StockPosting, Warehouse
from app.modules.inventory.posting import (
    NegativeStockError,
    PostingConflict,
    PostingLine,
    PostingReceipt,
    PostingRequest,
    ReservedStockConflict,
    find_posting,
    movements_of,
    post_movement,
    reverse_posting,
)
from app.modules.inventory.reservations import (
    ReserveResult,
    active_for_demand,
    release,
    release_for_demand,
    remaining,
    reserve,
    reserved_by_demand,
    stock_quantity,
    summary_of,
)
from app.modules.inventory.shortages import (
    Demand,
    refresh,
    register_cause_provider,
    register_demand_provider,
    register_pair_resolver,
)
from app.platform.uow import UnitOfWork

__all__ = [
    "Demand",
    "NegativeStockError",
    "PostingConflict",
    "PostingLine",
    "PostingReceipt",
    "PostingRequest",
    "ReserveResult",
    "ReservedStockConflict",
    "active_for_demand",
    "challan_postings_enabled",
    "company_location",
    "default_location",
    "ensure_company_locations",
    "find_posting",
    "get_location",
    "holding_location",
    "movements_by_source_line",
    "movements_of",
    "office_location",
    "policy",
    "post_movement",
    "refresh",
    "register_cause_provider",
    "register_demand_provider",
    "register_pair_resolver",
    "release",
    "release_for_demand",
    "remaining",
    "reserve",
    "reserved_by_demand",
    "resolve_warehouse",
    "reverse_posting",
    "stock_quantity",
    "summary_of",
    "warehouse_location",
    "wip_location",
    "record_measured_lot",
]


def policy(uow: UnitOfWork) -> InventoryPolicy:
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "inventory_policy")
    assert isinstance(value, InventoryPolicy)
    return value


def challan_postings_enabled(uow: UnitOfWork) -> bool:
    return policy(uow).challan_postings_enabled


def default_warehouse(uow: UnitOfWork) -> Warehouse | None:
    code = policy(uow).default_warehouse_code
    stmt = select(Warehouse).where(
        Warehouse.company_id == uow.actor.company_id, Warehouse.is_active.is_(True)
    )
    if code:
        return uow.session.scalars(stmt.where(Warehouse.code == code)).first()
    rows = list(uow.session.scalars(stmt.limit(2)))
    return rows[0] if len(rows) == 1 else None


def resolve_warehouse(uow: UnitOfWork, warehouse_id: uuid.UUID | None) -> Warehouse:
    """``warehouse_id`` when given (active, this company), else the policy's default warehouse; 422 otherwise."""
    if warehouse_id is not None:
        wh = uow.session.scalars(
            select(Warehouse).where(
                Warehouse.company_id == uow.actor.company_id, Warehouse.id == warehouse_id
            )
        ).first()
        if wh is not None and wh.is_active:
            return wh
    else:
        wh = default_warehouse(uow)
        if wh is not None:
            return wh
    raise ValidationFailed(
        "Choose the warehouse the stock moves from",
        errors=[
            {"loc": ["body", "warehouse_id"], "msg": "no (active) warehouse", "code": "warehouse_required"}
        ],
    )


def movements_by_source_line(
    uow: UnitOfWork, posting_id: uuid.UUID, source_line_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[StockMovement]]:
    out: dict[uuid.UUID, list[StockMovement]] = {}
    if not source_line_ids:
        return out
    rows = uow.session.scalars(
        select(StockMovement)
        .where(
            StockMovement.company_id == uow.actor.company_id,
            StockMovement.posting_id == posting_id,
            StockMovement.source_line_id.in_(source_line_ids),
        )
        .order_by(StockMovement.line_no)
    )
    for m in rows:
        assert m.source_line_id is not None
        out.setdefault(m.source_line_id, []).append(m)
    return out


def posting_by_id(uow: UnitOfWork, posting_id: uuid.UUID) -> StockPosting | None:
    return uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.id == posting_id
        )
    ).first()


ZERO = Decimal(0)


def record_measured_lot(
    uow: UnitOfWork,
    *,
    product_id: uuid.UUID,
    lot_code: str,
    lot_kind: str,
    length_mm: Decimal,
    width_mm: Decimal,
    thickness_mm: Decimal | None,
    grain_axis: str | None,
    parent_lot_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create a lot (``offcut`` / ``board_lot``) and record its measured dimensions in one step (``inventory.lot.manage``;
    emits ``inventory.lot.measured``). Returns the lot id. ``parent_lot_id`` must be a lot of the same product."""
    from app.modules.inventory.documents import create_lot, measure_lot
    from app.modules.inventory.enums import LotKind
    from app.modules.inventory.models import Lot
    from app.modules.inventory.schemas import LotCreate, LotMeasure

    if parent_lot_id is not None:
        parent = uow.session.scalars(
            select(Lot).where(Lot.company_id == uow.actor.company_id, Lot.id == parent_lot_id)
        ).first()
        if parent is None or parent.product_id != product_id:
            raise ValidationFailed(
                "The parent lot belongs to another product",
                errors=[{"loc": ["body", "parent_lot_id"], "msg": "lot of another product", "code": "lot_mismatch"}],
            )
    lot = create_lot(uow, LotCreate(product_id=product_id, lot_code=lot_code, lot_kind=LotKind(lot_kind)))
    if parent_lot_id is not None:
        lot.parent_lot_id = parent_lot_id
        uow.flush()
    measure_lot(
        uow,
        lot.id,
        LotMeasure(length_mm=length_mm, width_mm=width_mm,
                   thickness_mm=thickness_mm, grain_axis=grain_axis),
    )
    return lot.id
