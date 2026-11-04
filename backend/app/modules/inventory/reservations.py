"""Reservations (operations.md §3): reserving waits for the same summary row lock as posting, so two requests can never
both take the same units. Shortfalls are never silent: ``inventory.reservation.shortfall_detected`` names the demand,
and ``inventory.reservation.conflict_detected`` names every demand competing for the short stock.

The caller locks its demand line first (lock order: document header -> lines -> summary -> balances -> reservation) and
passes how much of the demand is still unreserved; inventory grants ``min(requested, available)`` (``partial``) or
nothing when short (``all_or_nothing``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.catalogue.models import Product
from app.modules.inventory import events as ev
from app.modules.inventory.enums import ReservationStatus, ReservePolicy
from app.modules.inventory.models import Reservation, StockSummary
from app.modules.inventory.posting import lock_summaries
from app.platform.org.reference import convert
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


@dataclass(frozen=True)
class ReserveResult:
    requested: Decimal
    granted: Decimal
    shortfall: Decimal
    reservation: Reservation | None
    uom_code: str


def remaining(res: Reservation) -> Decimal:
    return Decimal(res.quantity) - Decimal(res.consumed_qty) - Decimal(res.released_qty)


def active_for_demand(uow: UnitOfWork, demand_type: str, demand_id: uuid.UUID) -> list[Reservation]:
    return list(
        uow.session.scalars(
            select(Reservation)
            .where(
                Reservation.company_id == uow.actor.company_id,
                Reservation.demand_type == demand_type,
                Reservation.demand_id == demand_id,
                Reservation.status == ReservationStatus.ACTIVE.value,
            )
            .order_by(Reservation.created_at, Reservation.id)
        )
    )


def reserved_by_demand(
    uow: UnitOfWork, demand_type: str, demand_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Active reserved quantity (stock unit) per demand id."""
    if not demand_ids:
        return {}
    rows = uow.session.execute(
        select(
            Reservation.demand_id,
            func.sum(Reservation.quantity - Reservation.consumed_qty - Reservation.released_qty),
        )
        .where(
            Reservation.company_id == uow.actor.company_id,
            Reservation.demand_type == demand_type,
            Reservation.demand_id.in_(demand_ids),
            Reservation.status == ReservationStatus.ACTIVE.value,
        )
        .group_by(Reservation.demand_id)
    ).all()
    return {r[0]: Decimal(r[1] or 0) for r in rows}


def stock_quantity(
    uow: UnitOfWork, product_id: uuid.UUID, qty: Decimal, uom_code: str
) -> tuple[Decimal, str]:
    """``qty`` in ``uom_code`` converted to the product's stock unit (422 when the product is not stock-ready)."""
    product = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id == product_id)
    ).first()
    if product is None:
        raise NotFound("product not found", code="product_not_found")
    if not product.is_stock_tracked or not product.stock_uom_code:
        raise ValidationFailed(
            f"{product.product_key} is not stock-tracked",
            errors=[
                {
                    "loc": ["body", "product_id"],
                    "msg": "not stock-tracked",
                    "code": "product_not_stock_tracked",
                }
            ],
        )
    return convert(uow, Decimal(qty), uom_code, product.stock_uom_code, product.id), product.stock_uom_code


def _holders(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> list[dict[str, str]]:
    rows = uow.session.execute(
        select(Reservation.demand_type, Reservation.demand_id)
        .where(
            Reservation.company_id == uow.actor.company_id,
            Reservation.product_id == product_id,
            Reservation.warehouse_id == warehouse_id,
            Reservation.status == ReservationStatus.ACTIVE.value,
        )
        .distinct()
        .order_by(Reservation.demand_type, Reservation.demand_id)
    ).all()
    return [{"type": r[0], "id": str(r[1])} for r in rows]


def _emit_shortfall(
    uow: UnitOfWork, demand_type: str, demand_id: uuid.UUID, product_id: uuid.UUID, warehouse_id: uuid.UUID
) -> None:
    uow.emit(
        ev.RESERVATION_SHORTFALL,
        aggregate_id=demand_id,
        payload={
            "demand_type": demand_type,
            "demand_id": str(demand_id),
            "product_id": str(product_id),
            "warehouse_id": str(warehouse_id),
        },
    )
    holders = [h for h in _holders(uow, product_id, warehouse_id) if h["id"] != str(demand_id)]
    if holders:
        refs = sorted(
            [{"type": demand_type, "id": str(demand_id)}, *holders], key=lambda r: (r["type"], r["id"])
        )
        uow.emit(
            ev.RESERVATION_CONFLICT,
            aggregate_id=product_id,
            payload={"product_id": str(product_id), "warehouse_id": str(warehouse_id), "demand_refs": refs},
        )


def emit_shortfall_for_holders(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> None:
    """An approved loss ate into reserved stock: every holder is now short (posting step 6 exception)."""
    holders = _holders(uow, product_id, warehouse_id)
    for h in holders:
        uow.emit(
            ev.RESERVATION_SHORTFALL,
            aggregate_id=uuid.UUID(h["id"]),
            payload={
                "demand_type": h["type"],
                "demand_id": h["id"],
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
            },
        )
    if len(holders) > 1:
        uow.emit(
            ev.RESERVATION_CONFLICT,
            aggregate_id=product_id,
            payload={
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
                "demand_refs": holders,
            },
        )


def reserve(
    uow: UnitOfWork,
    *,
    demand_type: str,
    demand_id: uuid.UUID,
    demand_parent_id: uuid.UUID | None,
    demand_label: str | None,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    quantity: Decimal,
    policy: ReservePolicy = ReservePolicy.PARTIAL,
    reason: str | None = None,
    priority: int = 100,
) -> ReserveResult:
    """Reserve up to ``quantity`` (stock unit) of ``product_id`` at ``warehouse_id`` for one demand.

    The caller holds the demand line lock and passes at most the demand's unreserved remainder."""
    if quantity <= 0:
        raise ValidationFailed(
            "Nothing to reserve",
            errors=[
                {"loc": ["body", "quantity"], "msg": "must be greater than zero", "code": "not_positive"}
            ],
        )
    product = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id == product_id)
    ).first()
    if product is None or not product.is_stock_tracked or not product.stock_uom_code:
        raise ValidationFailed(
            "The product is not stock-tracked",
            errors=[
                {
                    "loc": ["body", "product_id"],
                    "msg": "not stock-tracked",
                    "code": "product_not_stock_tracked",
                }
            ],
        )
    summary = lock_summaries(uow, {(product_id, warehouse_id)})[(product_id, warehouse_id)]
    available = max(Decimal(summary.available_on_hand) - Decimal(summary.reserved), ZERO)
    if policy == ReservePolicy.ALL_OR_NOTHING:
        granted = quantity if available >= quantity else ZERO
    else:
        granted = min(quantity, available)
    shortfall = quantity - granted
    reservation: Reservation | None = None
    if granted > 0:
        reservation = Reservation(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=granted,
            consumed_qty=ZERO,
            released_qty=ZERO,
            uom_code=product.stock_uom_code,
            status=ReservationStatus.ACTIVE.value,
            demand_type=demand_type,
            demand_id=demand_id,
            demand_parent_id=demand_parent_id,
            demand_label=demand_label,
            priority=priority,
            reason=reason,
        )
        uow.add(reservation)
        summary.reserved = Decimal(summary.reserved) + granted
        summary.version = int(summary.version) + 1
        summary.updated_at = uow.now()
        uow.flush()
        uow.emit(
            ev.RESERVATION_CREATED,
            aggregate_id=reservation.id,
            aggregate_version=reservation.version,
            payload={
                "reservation_id": str(reservation.id),
                "demand_type": demand_type,
                "demand_id": str(demand_id),
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
            },
        )
    if shortfall > 0:
        _emit_shortfall(uow, demand_type, demand_id, product_id, warehouse_id)
    return ReserveResult(quantity, granted, shortfall, reservation, product.stock_uom_code)


def release(
    uow: UnitOfWork, reservation_id: uuid.UUID, *, reason_code: str, quantity: Decimal | None = None
) -> Reservation:
    """Release the remainder (or ``quantity`` of it). Locks the summary before the reservation (lock order)."""
    peek = uow.session.scalars(
        select(Reservation).where(
            Reservation.company_id == uow.actor.company_id, Reservation.id == reservation_id
        )
    ).first()
    if peek is None:
        raise NotFound("reservation not found", code="reservation_not_found")
    summary = lock_summaries(uow, {(peek.product_id, peek.warehouse_id)})[
        (peek.product_id, peek.warehouse_id)
    ]
    [res] = uow.lock(Reservation, [reservation_id])
    uow.session.refresh(res)
    if res.status != ReservationStatus.ACTIVE.value:
        raise Conflict("The reservation is no longer active", code="reservation_not_active")
    left = remaining(res)
    qty = left if quantity is None else min(Decimal(quantity), left)
    if qty <= 0:
        raise ValidationFailed(
            "Nothing to release",
            errors=[
                {"loc": ["body", "quantity"], "msg": "must be greater than zero", "code": "not_positive"}
            ],
        )
    res.released_qty = Decimal(res.released_qty) + qty
    res.release_reason_code = reason_code
    res.released_at = uow.now()
    res.released_by = uow.actor.user_id
    if remaining(res) <= 0:
        res.status = (
            ReservationStatus.RELEASED.value
            if Decimal(res.consumed_qty) == 0
            else ReservationStatus.FULFILLED.value
        )
    summary.reserved = max(Decimal(summary.reserved) - qty, ZERO)
    summary.version = int(summary.version) + 1
    summary.updated_at = uow.now()
    uow.flush()
    uow.emit(
        ev.RESERVATION_RELEASED,
        aggregate_id=res.id,
        aggregate_version=res.version,
        payload={
            "reservation_id": str(res.id),
            "demand_type": res.demand_type,
            "demand_id": str(res.demand_id),
            "product_id": str(res.product_id),
            "warehouse_id": str(res.warehouse_id),
        },
    )
    return res


def release_for_demand(
    uow: UnitOfWork, demand_type: str, demand_id: uuid.UUID, *, reason_code: str
) -> list[Reservation]:
    return [
        release(uow, r.id, reason_code=reason_code) for r in active_for_demand(uow, demand_type, demand_id)
    ]


def summary_of(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> StockSummary | None:
    return uow.session.scalars(
        select(StockSummary).where(
            StockSummary.company_id == uow.actor.company_id,
            StockSummary.product_id == product_id,
            StockSummary.warehouse_id == warehouse_id,
        )
    ).first()
