"""Deterministic cost rollups (operations.md §6 "Cost rollup").

For a product, as of a date and in a currency:
1. Explode the approved BOM recursively (primary lines; a component with an approved BOM of its own is exploded too,
   with its own routing). Quantity per unit = ``qty_per x (1 + scrap_pct / 100)`` along the path.
2. Material: the component's **cost of record** (``pricing_product_cost``, the latest version effective on the date),
   its unit converted with master-data conversions, its currency with an approved FX rate dated on or before the date.
3. Operations: ``(setup_minutes / standard_batch_qty + run_minutes_per_unit) / 60 x work-centre hourly rate`` per unit
   (``batch_qty`` overrides the routing's standard batch).
4. Anything missing (no cost of record, no conversion, no approved FX rate, no work-centre rate, no BOM, no routing) is
   listed in ``missing_inputs`` and excluded: the status is ``incomplete`` and the UI says the total is partial.
5. Decimal throughout; each line rounds to 4 dp ROUND_HALF_UP; totals are sums of the rounded lines.
6. The input hash covers every input (versions, quantities, cost-record ids and amounts, rates and FX ids): the same
   hash returns the stored rollup (``reused``) and emits nothing, a new hash stores a new rollup and emits
   ``production.cost_rollup.computed`` (ids and status only).
Figures are guarded (``pricing.cost.read``, never model-exposed); the rollup's status and missing inputs are not.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.http.pagination import Page
from app.core.money import Money
from app.modules.catalogue.models import Product
from app.modules.pricing.models import ProductCost
from app.modules.production import events as ev
from app.modules.production.common import (
    ZERO,
    business_date,
    company_currency,
    dec,
    fmt,
    product,
    product_refs,
    user_refs,
)
from app.modules.production.masters import approved_bom, approved_routing, bom_lines, routing_operations
from app.modules.production.models import CostRollup, WorkCenter
from app.modules.production.schemas import CostLine, CostRollupRead, CostRollupRequest, MissingInput
from app.platform.org.reference import convert
from app.platform.uow import UnitOfWork

RUN = "production.cost_rollup.run"
READ_KEYS = ("production.bom.read", RUN)
PLACES = Decimal("0.0001")
MAX_DEPTH = 12


@dataclass
class _Acc:
    currency: str
    as_of: date
    batch_qty: Decimal | None
    lines: list[CostLine] = field(default_factory=list)
    missing: list[MissingInput] = field(default_factory=list)
    inputs: list[Any] = field(default_factory=list)
    bom_id: uuid.UUID | None = None
    routing_id: uuid.UUID | None = None


def _q(v: Decimal) -> Decimal:
    return v.quantize(PLACES, rounding=ROUND_HALF_UP)


def _miss(acc: _Acc, m: MissingInput) -> None:
    if not any(x.kind == m.kind and x.ref_id == m.ref_id and x.reason_code == m.reason_code for x in acc.missing):
        acc.missing.append(m)


def _fx(uow: UnitOfWork, acc: _Acc, amount: Decimal, currency: str, ref_type: str, ref_id: uuid.UUID, label: str) -> Decimal | None:
    if currency == acc.currency:
        return amount
    from app.modules.pricing.fx import find_approved_rate

    rate = find_approved_rate(uow, currency, acc.currency, acc.as_of)
    if rate is None:
        _miss(acc, MissingInput(kind="fx_rate", ref_type=ref_type, ref_id=ref_id,
                                label=f"{label}: no approved {currency}->{acc.currency} rate on or before {acc.as_of}",
                                reason_code="fx_rate_missing"))
        return None
    acc.inputs.append(["fx", str(rate.id), fmt(dec(rate.rate))])
    return amount * dec(rate.rate)


def cost_of_record(uow: UnitOfWork, product_id: uuid.UUID, on: date) -> ProductCost | None:
    return uow.session.scalars(
        select(ProductCost).where(ProductCost.company_id == uow.actor.company_id, ProductCost.product_id == product_id,
                                  ProductCost.effective_from <= on)
        .order_by(ProductCost.effective_from.desc(), ProductCost.cost_version.desc())
    ).first()


def _material(uow: UnitOfWork, acc: _Acc, comp: Product, qty: Decimal, uom: str, path: str) -> None:
    cost = cost_of_record(uow, comp.id, acc.as_of)
    label = f"{comp.product_key} · {comp.product_name}"
    if cost is None:
        _miss(acc, MissingInput(kind="material_cost", ref_type="catalogue.product", ref_id=comp.id,
                                label=f"{comp.product_key}: no cost of record on {acc.as_of}", reason_code="cost_missing"))
        acc.inputs.append(["cost_missing", str(comp.id)])
        return
    acc.inputs.append(["cost", str(cost.id), cost.cost_version, fmt(dec(cost.unit_cost_amount)), cost.unit_cost_currency,
                       cost.unit_code])
    try:
        in_cost_unit = convert(uow, qty, uom, cost.unit_code, comp.id)
    except ValidationFailed:
        _miss(acc, MissingInput(kind="uom_conversion", ref_type="catalogue.product", ref_id=comp.id,
                                label=f"{comp.product_key}: no conversion from {uom} to {cost.unit_code}",
                                reason_code="uom_conversion_missing"))
        return
    unit = _fx(uow, acc, dec(cost.unit_cost_amount), cost.unit_cost_currency, "catalogue.product", comp.id, comp.product_key)
    if unit is None:
        return
    acc.lines.append(CostLine(kind="material", path=path, label=label, quantity=_q(in_cost_unit), uom_code=cost.unit_code,
                              unit_cost=Money(amount=_q(unit), currency=acc.currency),  # type: ignore[arg-type]
                              amount=Money(amount=_q(in_cost_unit * unit), currency=acc.currency),  # type: ignore[arg-type]
                              source=f"cost of record v{cost.cost_version}"))


def _operations(uow: UnitOfWork, acc: _Acc, p: Product, qty: Decimal, path: str, top: bool) -> None:
    routing = approved_routing(uow, p.id)
    if routing is None:
        if top:
            _miss(acc, MissingInput(kind="routing", ref_type="catalogue.product", ref_id=p.id,
                                    label=f"{p.product_key}: no approved routing", reason_code="routing_missing"))
        acc.inputs.append(["routing_missing", str(p.id)])
        return
    if top:
        acc.routing_id = routing.id
    batch = acc.batch_qty if (top and acc.batch_qty) else dec(routing.standard_batch_qty)
    acc.inputs.append(["routing", str(routing.id), routing.version_no, fmt(batch)])
    for op in routing_operations(uow, routing.id):
        wc = uow.session.get(WorkCenter, op.work_center_id)
        assert wc is not None
        per_unit = dec(op.setup_minutes) / batch + dec(op.run_minutes_per_unit)
        minutes = per_unit * qty
        acc.inputs.append(["op", str(op.id), fmt(dec(op.setup_minutes)), fmt(dec(op.run_minutes_per_unit)),
                           str(wc.id), fmt(dec(wc.rate_per_hour_amount)) if wc.rate_per_hour_amount is not None else None,
                           wc.rate_per_hour_currency])
        if wc.rate_per_hour_amount is None or wc.rate_per_hour_currency is None:
            _miss(acc, MissingInput(kind="work_centre_rate", ref_type="production.work_center", ref_id=wc.id,
                                    label=f"{wc.code}: no hourly rate", reason_code="rate_missing"))
            continue
        rate = _fx(uow, acc, dec(wc.rate_per_hour_amount), wc.rate_per_hour_currency, "production.work_center", wc.id, wc.code)
        if rate is None:
            continue
        per_minute = rate / Decimal(60)
        acc.lines.append(CostLine(kind="operation", path=path, label=f"{op.seq} {op.name} at {wc.code}",
                                  quantity=_q(minutes), uom_code="min",
                                  unit_cost=Money(amount=_q(per_minute), currency=acc.currency),  # type: ignore[arg-type]
                                  amount=Money(amount=_q(minutes * per_minute), currency=acc.currency),  # type: ignore[arg-type]
                                  source=f"routing v{routing.version_no}"))


def _explode(uow: UnitOfWork, acc: _Acc, p: Product, qty: Decimal, path: str, depth: int, top: bool) -> None:
    bom = approved_bom(uow, p.id)
    if bom is None:
        if top:
            _miss(acc, MissingInput(kind="bom", ref_type="catalogue.product", ref_id=p.id,
                                    label=f"{p.product_key}: no approved BOM", reason_code="bom_missing"))
        return
    if top:
        acc.bom_id = bom.id
    acc.inputs.append(["bom", str(bom.id), bom.version_no])
    for ln in bom_lines(uow, bom.id):
        if ln.alternate_for_line_no is not None:
            continue
        comp = uow.session.get(Product, ln.component_product_id)
        assert comp is not None
        line_qty = qty * dec(ln.qty_per) * (1 + dec(ln.scrap_pct) / Decimal(100))
        acc.inputs.append(["line", str(ln.id), fmt(dec(ln.qty_per)), ln.uom_code, fmt(dec(ln.scrap_pct))])
        sub_path = f"{path} > {comp.product_key}"
        if depth < MAX_DEPTH and approved_bom(uow, comp.id) is not None and comp.stock_uom_code:
            try:
                in_stock = convert(uow, line_qty, ln.uom_code, comp.stock_uom_code, comp.id)
            except ValidationFailed:
                _miss(acc, MissingInput(kind="uom_conversion", ref_type="catalogue.product", ref_id=comp.id,
                                        label=f"{comp.product_key}: no conversion from {ln.uom_code} to {comp.stock_uom_code}",
                                        reason_code="uom_conversion_missing"))
                continue
            _explode(uow, acc, comp, in_stock, sub_path, depth + 1, False)
            _operations(uow, acc, comp, in_stock, sub_path, False)
        else:
            _material(uow, acc, comp, line_qty, ln.uom_code, sub_path)


def compute(uow: UnitOfWork, req: CostRollupRequest) -> tuple[_Acc, str, Product]:
    """Pure computation (reads only): the accumulated lines, missing inputs and the input hash."""
    p = product(uow, req.product_id)
    acc = _Acc(currency=req.currency or company_currency(uow), as_of=req.as_of or business_date(uow),
               batch_qty=req.batch_qty)
    _explode(uow, acc, p, Decimal(1), p.product_key, 0, True)
    _operations(uow, acc, p, Decimal(1), p.product_key, True)
    body = {"product": str(p.id), "as_of": acc.as_of.isoformat(), "currency": acc.currency,
            "batch_qty": fmt(acc.batch_qty) if acc.batch_qty else None, "inputs": acc.inputs}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return acc, digest, p


def _read(uow: UnitOfWork, row: CostRollup, *, reused: bool = False) -> CostRollupRead:
    refs = product_refs(uow, [row.product_id])
    users = user_refs(uow, [row.created_by])
    cur = row.currency
    return CostRollupRead(
        id=row.id, product=refs[row.product_id], bom_id=row.bom_id, routing_id=row.routing_id, as_of=row.as_of,
        currency=cur, batch_qty=row.batch_qty, input_hash=row.input_hash, status=row.status,  # type: ignore[arg-type]
        missing_inputs=[MissingInput.model_validate(m) for m in row.missing_inputs],
        material_total=Money(amount=row.material_amount, currency=cur),  # type: ignore[arg-type]
        operation_total=Money(amount=row.operation_amount, currency=cur),  # type: ignore[arg-type]
        total=Money(amount=row.total_amount, currency=cur),  # type: ignore[arg-type]
        lines=[CostLine.model_validate(x) for x in row.breakdown],
        computed_at=row.created_at, computed_by=users.get(row.created_by) if row.created_by else None, reused=reused,
    )


def run_rollup(uow: UnitOfWork, req: CostRollupRequest) -> CostRollupRead:
    uow.actor.require(RUN)
    acc, digest, p = compute(uow, req)
    uow.advisory_xact_lock("production.cost_rollup", digest)
    existing = uow.session.scalars(select(CostRollup).where(CostRollup.company_id == uow.actor.company_id,
                                                            CostRollup.input_hash == digest)).first()
    if existing is not None:
        return _read(uow, existing, reused=True)
    material = sum((dec(x.amount.amount) for x in acc.lines if x.kind == "material"), ZERO)
    operation = sum((dec(x.amount.amount) for x in acc.lines if x.kind == "operation"), ZERO)
    row = CostRollup(
        id=uuid.uuid7(), company_id=uow.actor.company_id, product_id=p.id, bom_id=acc.bom_id, routing_id=acc.routing_id,
        as_of=acc.as_of, currency=acc.currency, batch_qty=acc.batch_qty or Decimal(1), input_hash=digest,
        status="complete" if not acc.missing else "incomplete", material_amount=material, operation_amount=operation,
        total_amount=material + operation, breakdown=[x.model_dump(mode="json") for x in acc.lines],
        missing_inputs=[m.model_dump(mode="json") for m in acc.missing],
    )
    uow.add(row)
    uow.flush()
    uow.emit(ev.COST_ROLLUP_COMPUTED, aggregate_id=row.id, aggregate_version=1,
             payload={"rollup_id": str(row.id), "product_id": str(p.id), "status": row.status})
    uow.audit("production.cost_rollup.computed", resource_type="production.cost_rollup", resource_id=row.id,
              resource_label=p.product_key, restricted_fields=["total_amount", "breakdown"],
              details={"status": row.status, "missing": len(acc.missing)})
    return _read(uow, row)


def _require_read(uow: UnitOfWork) -> None:
    if not any(uow.actor.can(k) for k in READ_KEYS):
        raise Forbidden(code="permission_denied", permission=READ_KEYS[0])


def list_rollups(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0) -> Page[CostRollupRead]:
    _require_read(uow)
    stmt = select(CostRollup).where(CostRollup.company_id == uow.actor.company_id)
    if product_id:
        stmt = stmt.where(CostRollup.product_id == product_id)
    total = int(uow.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(uow.session.scalars(stmt.order_by(CostRollup.created_at.desc(), CostRollup.id.desc()).limit(limit).offset(offset)))
    return Page[CostRollupRead](items=[_read(uow, r) for r in rows], total=total, limit=limit, offset=offset)


def get_rollup(uow: UnitOfWork, rollup_id: uuid.UUID) -> CostRollupRead:
    _require_read(uow)
    row = uow.session.scalars(select(CostRollup).where(CostRollup.company_id == uow.actor.company_id,
                                                       CostRollup.id == rollup_id)).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="production.cost_rollup")
    return _read(uow, row)
