"""Measured offcut lots on hand (Slice 5 offcut reuse; read-only, additive to the Slice-4 inventory module).

Offcut lots (``lot_kind = 'offcut'``) are recorded by production with their measured size and never count as available
stock (``posting._counts_available``), so planners and the cutting optimiser read them here explicitly: a lot is on
hand when it is measured (``verification_status = 'verified'`` with length and width) and holds a positive balance in
an internal (stock) location of a warehouse the actor may read (``inventory.stock.read``). WIP, QC hold, rejected and
virtual locations never offer an offcut. Lots of invisible warehouses are simply absent (never confirmed).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.modules.inventory.enums import LocationType, LotKind, LotVerification
from app.modules.inventory.models import Location, Lot, StockBalance, Warehouse
from app.modules.inventory.policies import warehouse_clause
from app.platform.uow import UnitOfWork


@dataclass(frozen=True)
class OffcutLot:
    lot_id: uuid.UUID
    lot_code: str
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    warehouse_code: str
    location_id: uuid.UUID
    location_code: str
    #: the balance in that location (one measured piece is 1 in the product's stock unit)
    quantity: Decimal
    length_mm: Decimal
    width_mm: Decimal
    thickness_mm: Decimal | None
    #: ``length`` | ``width`` | ``none`` (or ``None`` when not recorded)
    grain_axis: str | None
    parent_lot_id: uuid.UUID | None


def offcut_lots(
    uow: UnitOfWork,
    *,
    lot_ids: Iterable[uuid.UUID] | None = None,
    product_ids: Iterable[uuid.UUID] | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[OffcutLot]:
    """Measured offcut lots on hand in visible warehouses, ordered by product, lot code and location.

    ``lot_ids`` / ``product_ids`` / ``warehouse_id`` narrow the result; an id that is not on hand (consumed, unmeasured,
    another warehouse, invisible) is simply missing from the answer, so callers compare what they asked for."""
    if not uow.actor.can("inventory.stock.read"):
        return []
    stmt = (
        select(Lot, StockBalance.quantity, Location.id, Location.code, Warehouse.id, Warehouse.code)
        .join(StockBalance, (StockBalance.lot_id == Lot.id) & (StockBalance.company_id == Lot.company_id))
        .join(Location, Location.id == StockBalance.location_id)
        .join(Warehouse, Warehouse.id == Location.warehouse_id)
        .where(
            Lot.company_id == uow.actor.company_id,
            Lot.lot_kind == LotKind.OFFCUT.value,
            Lot.verification_status == LotVerification.VERIFIED.value,
            Lot.length_mm.is_not(None),
            Lot.width_mm.is_not(None),
            StockBalance.quantity > 0,
            StockBalance.owner_party_id.is_(None),
            Location.location_type == LocationType.INTERNAL.value,
            Location.is_stock_bearing.is_(True),
            warehouse_clause(uow),
        )
        .order_by(Lot.product_id, Lot.lot_code, Location.code)
        .limit(max(1, min(limit, 500)))
    )
    if lot_ids is not None:
        ids = list(set(lot_ids))
        if not ids:
            return []
        stmt = stmt.where(Lot.id.in_(ids))
    if product_ids is not None:
        pids = list(set(product_ids))
        if not pids:
            return []
        stmt = stmt.where(Lot.product_id.in_(pids))
    if warehouse_id is not None:
        stmt = stmt.where(Warehouse.id == warehouse_id)
    out: list[OffcutLot] = []
    for lot, quantity, loc_id, loc_code, wh_id, wh_code in uow.session.execute(stmt).all():
        assert lot.length_mm is not None and lot.width_mm is not None
        out.append(OffcutLot(
            lot_id=lot.id, lot_code=lot.lot_code, product_id=lot.product_id, warehouse_id=wh_id, warehouse_code=wh_code,
            location_id=loc_id, location_code=loc_code, quantity=Decimal(quantity), length_mm=Decimal(lot.length_mm),
            width_mm=Decimal(lot.width_mm), thickness_mm=Decimal(lot.thickness_mm) if lot.thickness_mm is not None else None,
            grain_axis=lot.grain_axis, parent_lot_id=lot.parent_lot_id,
        ))
    return out
