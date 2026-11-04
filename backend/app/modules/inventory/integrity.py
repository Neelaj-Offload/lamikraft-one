"""Ledger integrity: projections against the immutable ledger (the nightly ``inventory.projection_check`` job and the
tests' ``assert_ledger_consistent``).

Checks, per company:
1. every balance equals SUM(movements into its key) - SUM(movements out of it);
2. every summary's ``available_on_hand`` equals the company-owned, non-offcut balance in its warehouse's available
   locations, and ``reserved`` equals the remaining quantity of its active reservations;
3. no stock-bearing balance is below zero.
Mismatches emit ``inventory.projection.mismatch_detected`` (product, warehouse) once per run; the job never repairs.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.modules.inventory import events as ev
from app.modules.inventory.models import (
    Location,
    Lot,
    Reservation,
    StockBalance,
    StockMovement,
    StockSummary,
)
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)
JOB = "inventory.projection_check"


@dataclass(frozen=True)
class Mismatch:
    kind: str  # balance | summary_available | summary_reserved | negative
    product_id: uuid.UUID
    warehouse_id: uuid.UUID | None
    expected: Decimal
    actual: Decimal


def check(uow: UnitOfWork) -> list[Mismatch]:
    company = uow.actor.company_id
    ledger: dict[tuple[Any, ...], Decimal] = defaultdict(lambda: ZERO)
    for col, sign in ((StockMovement.to_location_id, 1), (StockMovement.from_location_id, -1)):
        rows = uow.session.execute(
            select(
                StockMovement.product_id,
                col,
                StockMovement.lot_id,
                StockMovement.owner_party_id,
                func.sum(StockMovement.quantity),
            )
            .where(StockMovement.company_id == company)
            .group_by(StockMovement.product_id, col, StockMovement.lot_id, StockMovement.owner_party_id)
        ).all()
        for p, loc, lot, owner, qty in rows:
            ledger[(p, loc, lot, owner)] += sign * Decimal(qty)
    out: list[Mismatch] = []
    balances = list(uow.session.scalars(select(StockBalance).where(StockBalance.company_id == company)))
    seen = set()
    for b in balances:
        key = (b.product_id, b.location_id, b.lot_id, b.owner_party_id)
        seen.add(key)
        expected = ledger.get(key, ZERO)
        if Decimal(b.quantity) != expected:
            out.append(Mismatch("balance", b.product_id, b.warehouse_id, expected, Decimal(b.quantity)))
        if b.enforce_non_negative and Decimal(b.quantity) < 0:
            out.append(Mismatch("negative", b.product_id, b.warehouse_id, ZERO, Decimal(b.quantity)))
    locs = {
        loc.id: loc for loc in uow.session.scalars(select(Location).where(Location.company_id == company))
    }
    for key, qty in ledger.items():
        if key not in seen and qty != 0:
            out.append(
                Mismatch("balance", key[0], locs[key[1]].warehouse_id if key[1] in locs else None, qty, ZERO)
            )
    offcuts = set(
        uow.session.scalars(select(Lot.id).where(Lot.company_id == company, Lot.lot_kind == "offcut"))
    )
    available: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    for b in balances:
        loc = locs.get(b.location_id)
        if (
            loc is None
            or not loc.counts_available
            or loc.warehouse_id is None
            or b.owner_party_id is not None
        ):
            continue
        if b.lot_id in offcuts:
            continue
        available[(b.product_id, loc.warehouse_id)] += Decimal(b.quantity)
    reserved: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    for p, w, qty in uow.session.execute(
        select(
            Reservation.product_id,
            Reservation.warehouse_id,
            func.sum(Reservation.quantity - Reservation.consumed_qty - Reservation.released_qty),
        )
        .where(Reservation.company_id == company, Reservation.status == "active")
        .group_by(Reservation.product_id, Reservation.warehouse_id)
    ).all():
        reserved[(p, w)] = Decimal(qty)
    summaries = {
        (s.product_id, s.warehouse_id): s
        for s in uow.session.scalars(select(StockSummary).where(StockSummary.company_id == company))
    }
    for key in set(summaries) | set(available) | set(reserved):
        s = summaries.get(key)
        got_a = Decimal(s.available_on_hand) if s else ZERO
        got_r = Decimal(s.reserved) if s else ZERO
        if got_a != available.get(key, ZERO):
            out.append(Mismatch("summary_available", key[0], key[1], available.get(key, ZERO), got_a))
        if got_r != reserved.get(key, ZERO):
            out.append(Mismatch("summary_reserved", key[0], key[1], reserved.get(key, ZERO), got_r))
    return out


def detect_mismatches(uow: UnitOfWork) -> int:
    found = check(uow)
    pairs = sorted({(m.product_id, m.warehouse_id) for m in found}, key=lambda t: (str(t[0]), str(t[1])))
    for product_id, warehouse_id in pairs:
        uow.emit(
            ev.PROJECTION_MISMATCH,
            aggregate_id=product_id,
            payload={
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id) if warehouse_id else None,
            },
        )
    return len(pairs)


def projection_check(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks.jobs import for_each_company

    return for_each_company(ctx, JOB, detect_mismatches)


JOBS = [JobDef(JOB, projection_check, queue="default", max_attempts=3, lease_seconds=900)]
SCHEDULES = [ScheduleDef(JOB, JOB, "daily", daily_time=time(2, 30))]
