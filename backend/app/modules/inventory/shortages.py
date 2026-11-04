"""Persisted shortage state (ADR-037) and the ``inventory.shortage_refresh`` consumer.

A shortage exists for (product, warehouse) when the unreserved open demand exceeds the free available stock
(``available_on_hand - reserved``). Demand comes from registered *demand providers* (orders registers open sales
order lines; the production lane registers work-order materials), so this module never imports its consumers.
``caused_by`` lists the demands (and, once procurement registers them, late supply) as ``{type, id}`` refs, sorted,
which the ``ops.shortages`` briefing family groups by. Each state change bumps ``version`` and emits exactly one of
``inventory.shortage.detected`` / ``.changed`` / ``.resolved``; recomputing an unchanged state emits nothing, so replays
and re-deliveries are harmless.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.modules.inventory import events as ev
from app.modules.inventory.models import Reservation, ShortageState, StockSummary
from app.platform.events.models import DomainEvent
from app.platform.events.service import once
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


@dataclass(frozen=True)
class Demand:
    ref_type: str
    ref_id: uuid.UUID
    #: quantity still needed and not reserved, in the product's stock unit
    unreserved: Decimal


DemandProvider = Callable[[UnitOfWork, uuid.UUID, uuid.UUID], list[Demand]]
#: (product, warehouse) pairs a module's event touches (orders events name an order, not products)
PairResolver = Callable[[UnitOfWork, DomainEvent], set[tuple[uuid.UUID, uuid.UUID]]]

_PROVIDERS: dict[str, DemandProvider] = {}
_RESOLVERS: dict[str, PairResolver] = {}
#: supply-side causes (e.g. a late purchase-order line) registered by procurement: (product, warehouse) -> refs
_CAUSES: dict[str, Callable[[UnitOfWork, uuid.UUID, uuid.UUID], list[dict[str, str]]]] = {}


def register_demand_provider(name: str, provider: DemandProvider) -> None:
    _PROVIDERS[name] = provider


def register_pair_resolver(event_prefix: str, resolver: PairResolver) -> None:
    _RESOLVERS[event_prefix] = resolver


def register_cause_provider(
    name: str, provider: Callable[[UnitOfWork, uuid.UUID, uuid.UUID], list[dict[str, str]]]
) -> None:
    _CAUSES[name] = provider


def _free(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Decimal:
    s = uow.session.scalars(
        select(StockSummary).where(
            StockSummary.company_id == uow.actor.company_id,
            StockSummary.product_id == product_id,
            StockSummary.warehouse_id == warehouse_id,
        )
    ).first()
    if s is None:
        return ZERO
    return max(Decimal(s.available_on_hand) - Decimal(s.reserved), ZERO)


def refresh(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> ShortageState | None:
    """Recompute one (product, warehouse) shortage; emits one event per real state change."""
    uow.advisory_xact_lock("inventory.shortage", f"{product_id}:{warehouse_id}")
    demands: list[Demand] = []
    for provider in _PROVIDERS.values():
        demands.extend(d for d in provider(uow, product_id, warehouse_id) if d.unreserved > 0)
    demand_qty = sum((d.unreserved for d in demands), ZERO)
    free = _free(uow, product_id, warehouse_id)
    shortfall = max(demand_qty - free, ZERO)
    causes = {(d.ref_type, str(d.ref_id)) for d in demands}
    if shortfall > 0:
        for provider in _CAUSES.values():
            causes |= {(c["type"], c["id"]) for c in provider(uow, product_id, warehouse_id)}
    caused_by = [{"type": t, "id": i} for t, i in sorted(causes)] if shortfall > 0 else []
    row = uow.session.scalars(
        select(ShortageState)
        .where(
            ShortageState.company_id == uow.actor.company_id,
            ShortageState.product_id == product_id,
            ShortageState.warehouse_id == warehouse_id,
        )
        .with_for_update()
    ).first()
    now = uow.now()
    event: str | None = None
    if row is None:
        if shortfall <= 0:
            return None
        row = ShortageState(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            status="open",
            demand_qty=demand_qty,
            free_qty=free,
            shortfall_qty=shortfall,
            caused_by=caused_by,
            version=1,
            detected_at=now,
            updated_at=now,
        )
        uow.add(row)
        event = ev.SHORTAGE_DETECTED
    elif shortfall > 0:
        changed = (
            row.status != "open" or Decimal(row.shortfall_qty) != shortfall or row.caused_by != caused_by
        )
        if changed:
            event = ev.SHORTAGE_DETECTED if row.status != "open" else ev.SHORTAGE_CHANGED
            if row.status != "open":
                row.detected_at = now
                row.resolved_at = None
            row.status = "open"
            row.version = int(row.version) + 1
        row.demand_qty, row.free_qty, row.shortfall_qty, row.caused_by = (
            demand_qty,
            free,
            shortfall,
            caused_by,
        )
        row.updated_at = now
    elif row.status == "open":
        row.status = "resolved"
        row.version = int(row.version) + 1
        row.demand_qty, row.free_qty, row.shortfall_qty, row.caused_by = demand_qty, free, ZERO, []
        row.resolved_at = now
        row.updated_at = now
        event = ev.SHORTAGE_RESOLVED
    uow.flush()
    if event is not None:
        uow.emit(
            event,
            aggregate_id=row.id,
            aggregate_version=row.version,
            payload={
                "shortage_id": str(row.id),
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
                "version": row.version,
                "caused_by": row.caused_by,
            },
        )
    return row


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def pairs_for_event(uow: UnitOfWork, event: DomainEvent) -> set[tuple[uuid.UUID, uuid.UUID]]:
    payload = event.payload or {}
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if event.event_type in (ev.STOCK_POSTED,):
        for p in payload.get("product_ids") or []:
            for w in payload.get("warehouse_ids") or []:
                pairs.add((uuid.UUID(str(p)), uuid.UUID(str(w))))
    elif event.event_type == ev.POSTING_REVERSED:
        from app.modules.inventory.models import StockMovement

        pid = _uuid(payload.get("reversal_posting_id"))
        if pid is not None:
            for m in uow.session.scalars(
                select(StockMovement).where(
                    StockMovement.company_id == uow.actor.company_id, StockMovement.posting_id == pid
                )
            ):
                for w in (m.from_warehouse_id, m.to_warehouse_id):
                    if w is not None:
                        pairs.add((m.product_id, w))
    elif event.event_type.startswith("inventory.reservation."):
        p, w = _uuid(payload.get("product_id")), _uuid(payload.get("warehouse_id"))
        if p and w:
            pairs.add((p, w))
    else:
        for prefix, resolver in _RESOLVERS.items():
            if event.event_type.startswith(prefix):
                pairs |= resolver(uow, event)
    return pairs


def handle_refresh(uow: UnitOfWork, event: DomainEvent) -> None:
    """``inventory.shortage_refresh``: recompute the pairs the event touches (exactly once per event)."""
    if not once(uow, ev.SHORTAGE_REFRESH, event.id):
        return
    for product_id, warehouse_id in sorted(pairs_for_event(uow, event)):
        refresh(uow, product_id, warehouse_id)


def refresh_all(uow: UnitOfWork, pairs: Iterable[tuple[uuid.UUID, uuid.UUID]] | None = None) -> int:
    """Recompute every pair with demand, reservations or an open shortage (seed and repair)."""
    if pairs is None:
        rows = set(
            uow.session.execute(
                select(StockSummary.product_id, StockSummary.warehouse_id).where(
                    StockSummary.company_id == uow.actor.company_id
                )
            ).all()
        )
        rows |= set(
            uow.session.execute(
                select(ShortageState.product_id, ShortageState.warehouse_id).where(
                    ShortageState.company_id == uow.actor.company_id
                )
            ).all()
        )
        rows |= set(
            uow.session.execute(
                select(Reservation.product_id, Reservation.warehouse_id).where(
                    Reservation.company_id == uow.actor.company_id
                )
            ).all()
        )
        pairs = {(r[0], r[1]) for r in rows}
    n = 0
    for p, w in sorted(pairs):
        refresh(uow, p, w)
        n += 1
    return n


def open_shortages(uow: UnitOfWork) -> list[ShortageState]:
    return list(
        uow.session.scalars(
            select(ShortageState)
            .where(ShortageState.company_id == uow.actor.company_id, ShortageState.status == "open")
            .order_by(ShortageState.detected_at, ShortageState.id)
        )
    )
