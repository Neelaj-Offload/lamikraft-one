"""Delivery feasibility and the what-if simulation (operations.md §6). Both are **read-only**: they run inside
``common.read_only``, which makes any flush, event, job, audit row or number allocation raise, and nothing they
compute is stored.

``assess``: "can we deliver N of product by date" with evidence, in order:
1. free stock now at the warehouse (available on hand minus reservations) and the time of its last movement (older
   than ``STALE_DAYS`` is stale);
2. when stock does not cover it and the product has no approved BOM: supply from registered supply providers
   (procurement registers open purchase-order lines with their expected dates and lead-time sources);
3. otherwise make the rest: each component's free stock, short components covered by registered supply (production
   starts once the latest needed supply arrives);
4. the routing minutes scheduled first-fit into the work centres' remaining capacity after the released load.
Outcome: ``feasible`` | ``at_risk`` (finishes within one day of the date or relies on supply arriving within a day of
the start) | ``not_feasible`` | ``estimate``. A missing input (no supply source or lead time for a short purchased
component, no routing times, stale stock, no approved routing) forces ``estimate`` and is listed.

``simulate``: the same assessments over an in-memory overlay (free-stock deltas, machine counts, extra minutes per
day), next to the unchanged baseline, labelled as a simulation.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.catalogue.models import Product
from app.modules.inventory import service as inventory
from app.modules.inventory.models import StockMovement
from app.modules.inventory.policies import require_warehouse
from app.modules.production.capacity import CenterCalendar, center_calendar, schedule_forward
from app.modules.production.common import (
    ZERO,
    business_date,
    dec,
    fmt,
    product,
    product_refs,
    read_only,
    warehouse_refs,
)
from app.modules.production.enums import FeasibilityOutcome
from app.modules.production.masters import approved_bom, approved_routing, bom_lines, routing_operations
from app.modules.production.models import WorkCenter
from app.modules.production.schemas import (
    EvidenceItem,
    FeasibilityRead,
    FeasibilityRequest,
    SimulationRead,
    SimulationRequest,
)
from app.platform.org.reference import convert
from app.platform.uow import UnitOfWork

RUN = "production.feasibility.run"
SIMULATE = "production.simulation.run"
STALE_DAYS = 30


@dataclass(frozen=True)
class Supply:
    """Incoming supply for (product, warehouse): an open purchase-order line, say. ``lead_time_source`` names where the
    expected date comes from (the vendor item, a confirmed date); None when the date is only assumed."""

    ref_type: str
    ref_id: uuid.UUID
    label: str
    quantity: Decimal
    expected_date: date | None
    lead_time_source: str | None = None


SupplyProvider = Callable[[UnitOfWork, uuid.UUID, uuid.UUID], list[Supply]]
_SUPPLY: dict[str, SupplyProvider] = {}


def register_supply_provider(name: str, provider: SupplyProvider) -> None:
    """Procurement registers open purchase-order supply here (manifest ``on_load``); production never imports it."""
    _SUPPLY[name] = provider


def supply_providers() -> dict[str, SupplyProvider]:
    return dict(_SUPPLY)


@dataclass
class Overlay:
    stock: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = field(default_factory=dict)
    machines: dict[uuid.UUID, int] = field(default_factory=dict)
    extra_minutes: dict[uuid.UUID, int] = field(default_factory=dict)


def _free(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID, overlay: Overlay | None) -> Decimal:
    s = inventory.summary_of(uow, product_id, warehouse_id)
    free = max(dec(s.available_on_hand) - dec(s.reserved), ZERO) if s is not None else ZERO
    if overlay is not None:
        free = max(free + overlay.stock.get((product_id, warehouse_id), ZERO), ZERO)
    return free


def _last_movement(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID):  # noqa: ANN202
    return uow.session.scalar(
        select(func.max(StockMovement.created_at)).where(
            StockMovement.company_id == uow.actor.company_id, StockMovement.product_id == product_id,
            (StockMovement.from_warehouse_id == warehouse_id) | (StockMovement.to_warehouse_id == warehouse_id))
    )


def _supply(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID, by: date) -> tuple[list[Supply], bool]:
    """Supply due by ``by`` (sorted by date) and whether any provider is registered at all."""
    if not _SUPPLY:
        return [], False
    found: list[Supply] = []
    for provider in _SUPPLY.values():
        found.extend(s for s in provider(uow, product_id, warehouse_id) if s.expected_date is None or s.expected_date <= by)
    return sorted(found, key=lambda s: (s.expected_date or by, s.label)), True


def _cover(supplies: list[Supply], need: Decimal) -> tuple[Decimal, date | None, bool]:
    """(covered quantity, date the cover completes, every date has a lead-time source)."""
    got, when, sourced = ZERO, None, True
    for s in supplies:
        if got >= need:
            break
        got += s.quantity
        when = s.expected_date or when
        sourced = sourced and s.lead_time_source is not None and s.expected_date is not None
    return min(got, need), when, sourced


def _is_integer(uow: UnitOfWork, code: str) -> bool:
    from app.platform.org.models import Uom

    return bool(uow.session.scalar(select(Uom.is_integer).where(Uom.company_id == uow.actor.company_id, Uom.code == code)))


def _calendars(uow: UnitOfWork, ops: list[tuple[uuid.UUID, Decimal]], start: date, overlay: Overlay | None) -> dict[uuid.UUID, CenterCalendar]:
    out: dict[uuid.UUID, CenterCalendar] = {}
    for wc_id, _m in ops:
        wc = uow.session.get(WorkCenter, wc_id)
        if wc is None or wc_id in out:
            continue
        cc = center_calendar(uow, wc, exceptions_from=start)
        if overlay is not None:
            cc.machine_count = overlay.machines.get(wc_id)
            cc.extra_minutes_per_day = overlay.extra_minutes.get(wc_id, 0)
        out[wc_id] = cc
    return out


def _assess(uow: UnitOfWork, req: FeasibilityRequest, overlay: Overlay | None) -> FeasibilityRead:
    p = product(uow, req.product_id)
    wh = inventory.resolve_warehouse(uow, req.warehouse_id)
    require_warehouse(uow, wh.id)  # 404: never assess (or confirm) a warehouse the actor cannot see
    today = business_date(uow)
    qty, uom = inventory.stock_quantity(uow, p.id, req.quantity, p.stock_uom_code or "")
    evidence: list[EvidenceItem] = []
    missing: list[str] = []
    free = _free(uow, p.id, wh.id, overlay)
    last = _last_movement(uow, p.id, wh.id)
    stale = last is None or (uow.now() - last).days > STALE_DAYS
    from_stock = min(free, qty)
    to_make = qty - from_stock
    evidence.append(EvidenceItem(kind="stock", status="ok" if to_make <= 0 else "short",
                                 label=f"{fmt(free)} {uom} free at {wh.code}",
                                 facts={"free": fmt(free), "needed": fmt(qty), "uom": uom,
                                        "last_movement_at": last.isoformat() if last else "",
                                        "stale": "true" if stale and to_make > 0 else "false"}))
    if stale and to_make > 0 and free > 0:
        missing.append("stock_stale")
    finish: date | None = today
    risk = False
    if to_make > 0:
        bom = approved_bom(uow, p.id)
        if bom is None:
            supplies, any_provider = _supply(uow, p.id, wh.id, req.need_by)
            got, when, sourced = _cover(supplies, to_make)
            if not any_provider:
                missing.append("purchase_supply_source")
                evidence.append(EvidenceItem(kind="purchase_supply", status="missing",
                                             label="No purchase-order source is connected; supply cannot be checked"))
                finish = None
            else:
                evidence.append(EvidenceItem(kind="purchase_supply", status="ok" if got >= to_make else "short",
                                             label=f"{fmt(got)} {uom} due by {req.need_by.isoformat()}",
                                             facts={"due": fmt(got), "short": fmt(to_make - got), "last_date": when.isoformat() if when else ""}))
                if not sourced and got > 0:
                    missing.append("lead_time")
                finish = when if got >= to_make else None
            evidence.append(EvidenceItem(kind="bom", status="info", label="No approved BOM: the product is bought, not made"))
        else:
            finish, risk = _make(uow, req, p, wh.id, to_make, bom, today, overlay, evidence, missing)
    if missing:
        outcome = FeasibilityOutcome.ESTIMATE
    elif finish is None or finish > req.need_by:
        outcome = FeasibilityOutcome.NOT_FEASIBLE
    elif risk or (to_make > 0 and (req.need_by - finish).days <= 1):
        outcome = FeasibilityOutcome.AT_RISK
    else:
        outcome = FeasibilityOutcome.FEASIBLE
    return FeasibilityRead(
        outcome=outcome, product=product_refs(uow, [p.id])[p.id], quantity=qty, uom_code=uom,
        warehouse=warehouse_refs(uow, [wh.id])[wh.id], need_by=req.need_by, from_stock=from_stock, to_make=to_make,
        earliest_completion=finish if to_make > 0 else today, evidence=evidence, missing_inputs=sorted(set(missing)),
        computed_at=uow.now(),
    )


def _make(uow: UnitOfWork, req: FeasibilityRequest, p: Product, warehouse_id: uuid.UUID, to_make: Decimal, bom, today: date,  # noqa: ANN001
          overlay: Overlay | None, evidence: list[EvidenceItem], missing: list[str]) -> tuple[date | None, bool]:
    start = today
    risk = False
    blocked = False
    for ln in bom_lines(uow, bom.id):
        if ln.alternate_for_line_no is not None:
            continue
        comp = uow.session.get(Product, ln.component_product_id)
        assert comp is not None
        if not comp.stock_uom_code:
            missing.append(f"stock_unit:{comp.product_key}")
            continue
        need = convert(uow, to_make * dec(ln.qty_per) * (1 + dec(ln.scrap_pct) / Decimal(100)), ln.uom_code,
                       comp.stock_uom_code, comp.id)
        if _is_integer(uow, comp.stock_uom_code):
            need = Decimal(math.ceil(need))
        free = _free(uow, comp.id, warehouse_id, overlay)
        short = max(need - free, ZERO)
        facts = {"needed": fmt(need), "free": fmt(free), "short": fmt(short), "uom": comp.stock_uom_code}
        if short <= 0:
            evidence.append(EvidenceItem(kind="components", status="ok", label=f"{comp.product_key}: {fmt(need)} {comp.stock_uom_code} available", facts=facts))
            continue
        supplies, any_provider = _supply(uow, comp.id, warehouse_id, req.need_by)
        if not any_provider:
            missing.append(f"lead_time:{comp.product_key}")
            evidence.append(EvidenceItem(kind="components", status="missing",
                                         label=f"{comp.product_key}: short {fmt(short)} {comp.stock_uom_code}; no purchase-order source to tell when more arrives",
                                         facts=facts))
            continue
        got, when, sourced = _cover(supplies, short)
        facts.update({"due": fmt(got), "due_date": when.isoformat() if when else ""})
        if got < short:
            blocked = True
            evidence.append(EvidenceItem(kind="components", status="short",
                                         label=f"{comp.product_key}: short {fmt(short - got)} {comp.stock_uom_code} even with open supply", facts=facts))
            continue
        if not sourced:
            missing.append(f"lead_time:{comp.product_key}")
        evidence.append(EvidenceItem(kind="components", status="late", label=f"{comp.product_key}: short {fmt(short)}, covered by supply due {when}", facts=facts))
        if when is not None and when > start:
            start = when
            risk = risk or (when - today).days <= 1
    routing = approved_routing(uow, p.id)
    if routing is None:
        missing.append("routing")
        evidence.append(EvidenceItem(kind="routing", status="missing", label="No approved routing: production time unknown"))
        return None, risk
    ops = [(o.work_center_id, dec(o.setup_minutes) + dec(o.run_minutes_per_unit) * to_make) for o in routing_operations(uow, routing.id)]
    if not ops or all(m <= 0 for _w, m in ops):
        missing.append("routing_times")
        evidence.append(EvidenceItem(kind="routing", status="missing", label="The routing has no standard times"))
        return None, risk
    if blocked:
        return None, risk
    result = schedule_forward(uow, ops, start, calendars=_calendars(uow, ops, start, overlay))
    total = sum((m for _w, m in ops), ZERO)
    if result.finish is None:
        evidence.append(EvidenceItem(kind="capacity", status="short", label="Not enough capacity within a year after the released load",
                                     facts={"minutes": fmt(total)}))
        return None, risk
    status = "ok" if result.finish <= req.need_by else "late"
    evidence.append(EvidenceItem(kind="capacity", status=status,  # type: ignore[arg-type]
                                 label=f"{fmt(total)} min of routing time fits by {result.finish.isoformat()}",
                                 facts={"minutes": fmt(total), "start": start.isoformat(), "finish": result.finish.isoformat()}))
    return result.finish, risk


def assess(uow: UnitOfWork, req: FeasibilityRequest) -> FeasibilityRead:
    uow.actor.require(RUN)
    with read_only(uow):
        return _assess(uow, req, None)


def assess_order_line(uow: UnitOfWork, line_id: uuid.UUID, need_by: date | None = None) -> FeasibilityRead:
    """Feasibility of an order line's remaining quantity by its requested (or promised) date."""
    from app.core.errors import NotFound, ValidationFailed
    from app.modules.orders.models import SalesOrder, SalesOrderLine

    uow.actor.require(RUN)
    with read_only(uow):
        line = uow.session.scalars(select(SalesOrderLine).where(SalesOrderLine.company_id == uow.actor.company_id,
                                                                SalesOrderLine.id == line_id)).first()
        if line is None:
            raise NotFound(code="not_found", resource_type="orders.sales_order_line")
        order = uow.repo(SalesOrder).get(line.order_id)  # 404 when the order is not visible
        if line.product_id is None:
            raise ValidationFailed("The line has no catalogue product", errors=[
                {"loc": ["path", "line_id"], "msg": "no product", "code": "line_not_producible"}])
        due = need_by or order.requested_delivery_date or order.promised_date
        if due is None:
            raise ValidationFailed("Give the date the customer needs it", errors=[
                {"loc": ["query", "need_by"], "msg": "the order has no requested date", "code": "need_by_required"}])
        remaining = dec(line.qty_remaining)
        if remaining <= 0:
            raise ValidationFailed("Nothing remains to deliver on this line", errors=[
                {"loc": ["path", "line_id"], "msg": "fulfilled", "code": "line_fulfilled"}])
        p = uow.session.get(Product, line.product_id)
        assert p is not None
        qty, _ = inventory.stock_quantity(uow, p.id, remaining, line.uom_code)
        return _assess(uow, FeasibilityRequest(product_id=p.id, quantity=qty, need_by=due,
                                               warehouse_id=order.default_warehouse_id), None)


def simulate(uow: UnitOfWork, req: SimulationRequest) -> SimulationRead:
    uow.actor.require(SIMULATE)
    with read_only(uow):
        overlay = Overlay()
        for ch in req.stock_changes:
            wh = inventory.resolve_warehouse(uow, ch.warehouse_id)
            require_warehouse(uow, wh.id)
            key = (ch.product_id, wh.id)
            overlay.stock[key] = overlay.stock.get(key, ZERO) + ch.delta
        for cap in req.capacity_changes:
            from app.modules.production.common import require_work_center

            require_work_center(uow, cap.work_center_id)
            if cap.machine_count is not None:
                overlay.machines[cap.work_center_id] = cap.machine_count
            if cap.extra_minutes_per_day is not None:
                overlay.extra_minutes[cap.work_center_id] = cap.extra_minutes_per_day
        baseline = [_assess(uow, c, None) for c in req.checks]
        scenario = [_assess(uow, c, overlay) for c in req.checks]
        return SimulationRead(baseline=baseline, scenario=scenario, computed_at=uow.now())


ONE_DAY = timedelta(days=1)
