"""Work-order stock events and shop-floor actions. Every stock event is one ``production_wo_transaction`` whose id is
the posting source: ``inventory.post_movement(source_type="work_order", source_id=<transaction id>, purpose=...)``, so
one event = one posting (the ledger's UNIQUE(company, source_type, source_id, purpose)).

| Action | Movement (inventory location types) | Purpose |
|---|---|---|
| issue | internal (a bin of the work order's warehouse) -> WIP of that warehouse; consumes the material's reservations first | issue |
| consume | WIP -> production (virtual) | consume |
| return | WIP -> internal (the warehouse's stock location) | return |
| output | production -> internal, or QC hold when the product requires QC | output |
| offcut | production -> internal, a new ``offcut`` lot with its measured dimensions (``inventory.lot.measured``) | output |

Quantities are in the component's (or product's) stock unit. Lots: issue names the lot of a lot-tracked component;
consume/return default to the lots issued to that material, oldest first, from this work order's own transactions.
Every action needs ``production.work_order.post`` over the work order and ``inventory.stock.post`` over its warehouse.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.inventory import service as inventory
from app.modules.inventory.enums import LocationType
from app.modules.inventory.policies import require_warehouse, require_warehouse_for
from app.modules.production.capacity import refresh_overloads
from app.modules.production.common import ZERO, dec, problem
from app.modules.production.enums import POSTING_PURPOSE, OperationStatus, RequirementSource, TransactionKind
from app.modules.production.models import WoMaterial, WoOperation, WorkOrder, WoTransaction
from app.modules.production.schemas import (
    CutPlanLink,
    IssueRequest,
    OffcutRecord,
    OperationComplete,
    OperationSchedule,
    OutputRequest,
    WipRequest,
)
from app.modules.production.work_orders import (
    DEMAND,
    get_work_order,
    in_wip,
    mark_started,
    materials_of,
    operations_of,
    reserve_materials,
    set_block_state,
    to_issue,
)
from app.platform.uow import UnitOfWork

STOCK_POST = "inventory.stock.post"


def _post(uow: UnitOfWork, wo: WorkOrder, kind: TransactionKind, lines: list[inventory.PostingLine],
          snapshot: list[dict[str, Any]], *, operation_id: uuid.UUID | None = None, lot_id: uuid.UUID | None = None,
          qty_good: Decimal | None = None, qty_scrap: Decimal | None = None, reason: str | None = None) -> WoTransaction:
    txn_id = uuid.uuid7()
    receipt = inventory.post_movement(uow, inventory.PostingRequest(
        source_type="work_order", source_id=txn_id, purpose=POSTING_PURPOSE[kind], lines=tuple(lines),
        source_label=f"{wo.wo_number} {kind.value}", reason=reason, idempotency_key=f"production:{txn_id}",
    ))
    txn = WoTransaction(id=txn_id, company_id=uow.actor.company_id, work_order_id=wo.id, kind=kind.value,
                        posting_id=receipt.posting.id, operation_id=operation_id, lot_id=lot_id, lines=snapshot,
                        qty_good=qty_good, qty_scrap=qty_scrap, reason=reason)
    uow.add(txn)
    uow.flush()
    return txn


def _for_posting(uow: UnitOfWork, work_order_id: uuid.UUID, expected_version: int) -> WorkOrder:
    wo = get_work_order(uow, work_order_id, "post", for_update=True)
    uow.expect_version(wo, expected_version)
    require_warehouse(uow, wo.warehouse_id, STOCK_POST)
    return wo


def _materials(uow: UnitOfWork, wo: WorkOrder, ids: list[uuid.UUID]) -> dict[uuid.UUID, WoMaterial]:
    mats = {m.id: m for m in materials_of(uow, wo.id, lock=True)}
    missing = [i for i in ids if i not in mats]
    if missing:
        raise ValidationFailed("A line names a material of another work order", errors=[
            {"loc": ["body", "lines", ids.index(i), "material_id"], "msg": "not a material of this work order",
             "code": "material_not_found"} for i in missing])
    return mats


def _warehouse_location(uow: UnitOfWork, wo: WorkOrder, location_id: uuid.UUID | None, loc: list[str | int]) -> Any:
    if location_id is None:
        return inventory.default_location(uow, wo.warehouse_id)
    try:
        location = inventory.get_location(uow, location_id)
    except NotFound:
        location = None
    if location is None or location.warehouse_id != wo.warehouse_id or location.location_type != LocationType.INTERNAL.value:
        # never confirm a location of another warehouse: the same answer as an unknown id
        raise problem(loc, "not a stock location of the work order's warehouse", "location_not_in_warehouse")
    return location


def _snap(m_id: uuid.UUID | None, product_id: uuid.UUID, qty: Decimal, uom: str, lot_id: uuid.UUID | None,
          frm: uuid.UUID, to: uuid.UUID) -> dict[str, Any]:
    return {"material_id": str(m_id) if m_id else None, "product_id": str(product_id), "quantity": format(qty, "f"),
            "uom_code": uom, "lot_id": str(lot_id) if lot_id else None, "from_location_id": str(frm),
            "to_location_id": str(to)}


# ---- issue ----------------------------------------------------------------------------------------------------------------
def issue(uow: UnitOfWork, work_order_id: uuid.UUID, data: IssueRequest) -> WorkOrder:
    wo = _for_posting(uow, work_order_id, data.expected_version)
    mats = _materials(uow, wo, [ln.material_id for ln in data.lines])
    wip = inventory.wip_location(uow, wo.warehouse_id)
    requested: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for ln in data.lines:
        requested[ln.material_id] += ln.quantity
    errors = [
        {"loc": ["body", "lines"], "msg": f"line {mats[mid].line_no}: at most {to_issue(mats[mid])} {mats[mid].uom_code} remain to issue",
         "code": "over_issue"}
        for mid, qty in requested.items() if qty > to_issue(mats[mid])
    ]
    if errors:
        raise ValidationFailed("More than the work order still needs", errors=errors)
    lines: list[inventory.PostingLine] = []
    snapshot: list[dict[str, Any]] = []
    reservations = {mid: sorted(inventory.active_for_demand(uow, DEMAND, mid), key=lambda r: r.created_at) for mid in requested}
    for i, ln in enumerate(data.lines):
        m = mats[ln.material_id]
        src = _warehouse_location(uow, wo, ln.from_location_id, ["lines", i, "from_location_id"])
        left = ln.quantity
        for res in reservations[m.id]:
            if left <= 0:
                break
            take = min(left, inventory.remaining(res) - _used(lines, res.id))
            if take <= 0:
                continue
            lines.append(inventory.PostingLine(product_id=m.component_product_id, quantity=take, uom_code=m.uom_code,
                                               from_location_id=src.id, to_location_id=wip.id, lot_id=ln.lot_id,
                                               reservation_id=res.id, source_line_type="production.wo_material",
                                               source_line_id=m.id))
            left -= take
        if left > 0:
            lines.append(inventory.PostingLine(product_id=m.component_product_id, quantity=left, uom_code=m.uom_code,
                                               from_location_id=src.id, to_location_id=wip.id, lot_id=ln.lot_id,
                                               source_line_type="production.wo_material", source_line_id=m.id))
        snapshot.append(_snap(m.id, m.component_product_id, ln.quantity, m.uom_code, ln.lot_id, src.id, wip.id))
    _post(uow, wo, TransactionKind.ISSUE, lines, snapshot, reason=data.reason)
    for mid, qty in requested.items():
        mats[mid].qty_issued = dec(mats[mid].qty_issued) + qty
    mark_started(uow, wo)
    wo.updated_at = uow.now()
    uow.flush()
    return wo


def _used(lines: list[inventory.PostingLine], reservation_id: uuid.UUID) -> Decimal:
    return sum((ln.quantity for ln in lines if ln.reservation_id == reservation_id), ZERO)


# ---- consume / return --------------------------------------------------------------------------------------------------
def wip_lots(uow: UnitOfWork, wo: WorkOrder) -> dict[uuid.UUID, dict[uuid.UUID | None, Decimal]]:
    """Per material, the quantity of each lot still in WIP for this work order (from its own transactions)."""
    out: dict[uuid.UUID, dict[uuid.UUID | None, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    txns = uow.session.scalars(select(WoTransaction).where(
        WoTransaction.company_id == uow.actor.company_id, WoTransaction.work_order_id == wo.id,
        WoTransaction.kind.in_([TransactionKind.ISSUE.value, TransactionKind.CONSUME.value, TransactionKind.RETURN.value]),
    ).order_by(WoTransaction.created_at, WoTransaction.id))
    for t in txns:
        sign = 1 if t.kind == TransactionKind.ISSUE.value else -1
        for ln in t.lines:
            if not ln.get("material_id"):
                continue
            lot = uuid.UUID(ln["lot_id"]) if ln.get("lot_id") else None
            out[uuid.UUID(ln["material_id"])][lot] += sign * Decimal(ln["quantity"])
    return out


def _lot_codes(uow: UnitOfWork, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from app.modules.inventory.models import Lot

    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    return dict(uow.session.execute(select(Lot.id, Lot.lot_code).where(Lot.id.in_(wanted))).all())


def _from_wip(uow: UnitOfWork, wo: WorkOrder, kind: TransactionKind, data: WipRequest) -> WorkOrder:
    mats = _materials(uow, wo, [ln.material_id for ln in data.lines])
    wip = inventory.wip_location(uow, wo.warehouse_id)
    dest = (inventory.company_location(uow, LocationType.PRODUCTION) if kind == TransactionKind.CONSUME
            else inventory.default_location(uow, wo.warehouse_id))
    lots = wip_lots(uow, wo)
    requested: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for ln in data.lines:
        requested[ln.material_id] += ln.quantity
    errors = [{"loc": ["body", "lines"], "msg": f"line {mats[mid].line_no}: only {in_wip(mats[mid])} {mats[mid].uom_code} are in WIP",
               "code": "exceeds_wip"} for mid, qty in requested.items() if qty > in_wip(mats[mid])]
    if errors:
        raise ValidationFailed("More than is in work in progress", errors=errors)
    lines: list[inventory.PostingLine] = []
    snapshot: list[dict[str, Any]] = []
    codes = _lot_codes(uow, [lot for per in lots.values() for lot in per])
    for i, ln in enumerate(data.lines):
        m = mats[ln.material_id]
        per = lots[m.id]
        if ln.lot_id is not None:
            if per.get(ln.lot_id, ZERO) < ln.quantity:
                raise problem(["lines", i, "lot_id"], "not that much of this lot is in WIP for this work order", "exceeds_wip_lot")
            alloc = [(ln.lot_id, ln.quantity)]
        else:
            alloc, left = [], ln.quantity
            for lot, qty in sorted(per.items(), key=lambda kv: (kv[0] is not None, codes.get(kv[0], "") if kv[0] else "")):
                if left <= 0:
                    break
                take = min(left, qty)
                if take > 0:
                    alloc.append((lot, take))
                    per[lot] -= take
                    left -= take
            if left > 0:
                raise problem(["lines", i, "quantity"], "the lots in WIP do not cover the quantity", "exceeds_wip_lot")
        for lot, qty in alloc:
            lines.append(inventory.PostingLine(product_id=m.component_product_id, quantity=qty, uom_code=m.uom_code,
                                               from_location_id=wip.id, to_location_id=dest.id, lot_id=lot,
                                               source_line_type="production.wo_material", source_line_id=m.id))
            snapshot.append(_snap(m.id, m.component_product_id, qty, m.uom_code, lot, wip.id, dest.id))
    _post(uow, wo, kind, lines, snapshot, reason=data.reason)
    for mid, qty in requested.items():
        if kind == TransactionKind.CONSUME:
            mats[mid].qty_consumed = dec(mats[mid].qty_consumed) + qty
        else:
            mats[mid].qty_returned = dec(mats[mid].qty_returned) + qty
    mark_started(uow, wo)
    wo.updated_at = uow.now()
    uow.flush()
    if kind == TransactionKind.RETURN and wo.status in ("released", "in_progress"):
        # returned material is needed again: reserve it back (or block on it)
        set_block_state(uow, wo, reserve_materials(uow, wo))
    return wo


def consume(uow: UnitOfWork, work_order_id: uuid.UUID, data: WipRequest) -> WorkOrder:
    return _from_wip(uow, _for_posting(uow, work_order_id, data.expected_version), TransactionKind.CONSUME, data)


def return_material(uow: UnitOfWork, work_order_id: uuid.UUID, data: WipRequest) -> WorkOrder:
    return _from_wip(uow, _for_posting(uow, work_order_id, data.expected_version), TransactionKind.RETURN, data)


# ---- output ---------------------------------------------------------------------------------------------------------------
def output(uow: UnitOfWork, work_order_id: uuid.UUID, data: OutputRequest) -> WorkOrder:
    """Post good finished goods production -> stock (or QC hold); scrap is recorded on the work order only."""
    from app.modules.catalogue.models import Product
    from app.modules.inventory.documents import ensure_lot

    wo = _for_posting(uow, work_order_id, data.expected_version)
    if dec(wo.qty_good) + data.qty_good > dec(wo.qty_planned):
        raise problem(["qty_good"], f"at most {dec(wo.qty_planned) - dec(wo.qty_good)} {wo.uom_code} remain to make",
                      "over_output", "More output than the work order plans")
    p = uow.session.get(Product, wo.product_id)
    assert p is not None
    lot_id = None
    if p.track_lots:
        lot_id = ensure_lot(uow, p.id, data.lot_code or wo.wo_number).id
    src = inventory.company_location(uow, LocationType.PRODUCTION)
    dest = (inventory.warehouse_location(uow, wo.warehouse_id, LocationType.QC_HOLD) if p.qc_required
            else inventory.default_location(uow, wo.warehouse_id))
    line = inventory.PostingLine(product_id=p.id, quantity=data.qty_good, uom_code=wo.uom_code, from_location_id=src.id,
                                 to_location_id=dest.id, lot_id=lot_id, source_line_type="production.work_order",
                                 source_line_id=wo.id)
    _post(uow, wo, TransactionKind.OUTPUT, [line],
          [_snap(None, p.id, data.qty_good, wo.uom_code, lot_id, src.id, dest.id)], lot_id=lot_id,
          qty_good=data.qty_good, qty_scrap=data.qty_scrap, reason=data.reason)
    wo.qty_good = dec(wo.qty_good) + data.qty_good
    wo.qty_scrap = dec(wo.qty_scrap) + data.qty_scrap
    mark_started(uow, wo)
    wo.updated_at = uow.now()
    uow.flush()
    return wo


# ---- operations -------------------------------------------------------------------------------------------------------------
def _operation(uow: UnitOfWork, wo: WorkOrder, operation_id: uuid.UUID) -> WoOperation:
    op = uow.session.scalars(select(WoOperation).where(
        WoOperation.company_id == uow.actor.company_id, WoOperation.work_order_id == wo.id,
        WoOperation.id == operation_id).with_for_update()).first()
    if op is None:
        raise NotFound(code="not_found", resource_type="production.wo_operation")
    return op


def complete_operation(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: OperationComplete) -> WorkOrder:
    wo = get_work_order(uow, work_order_id, "post", for_update=True)
    uow.expect_version(wo, data.expected_version)
    op = _operation(uow, wo, operation_id)
    if op.status != OperationStatus.PENDING.value:
        raise Conflict(f"Operation {op.seq} is already done", code="operation_done")
    op.status, op.actual_minutes = OperationStatus.DONE.value, data.actual_minutes
    op.completed_at, op.completed_by = uow.now(), uow.actor.user_id
    mark_started(uow, wo)
    wo.updated_at = uow.now()
    uow.flush()
    if op.planned_date is not None:
        refresh_overloads(uow, [(op.work_center_id, op.planned_date)])
    uow.audit("production.wo_operation.completed", resource_type="production.work_order", resource_id=wo.id,
              resource_label=wo.wo_number, details={"seq": op.seq})
    return wo


def schedule_operation(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: OperationSchedule) -> WorkOrder:
    wo = get_work_order(uow, work_order_id, "transition", for_update=True)
    uow.expect_version(wo, data.expected_version)
    if wo.status not in ("draft", "released", "in_progress"):
        raise Conflict(f"{wo.wo_number} is {wo.status}", code=f"work_order_{wo.status}")
    op = _operation(uow, wo, operation_id)
    if op.status != OperationStatus.PENDING.value:
        raise Conflict(f"Operation {op.seq} is already done", code="operation_done")
    before = op.planned_date
    op.planned_date = data.planned_date
    wo.updated_at = uow.now()
    uow.flush()
    refresh_overloads(uow, [(op.work_center_id, d) for d in (before, data.planned_date) if d is not None])
    return wo


# ---- cut plans and offcuts ----------------------------------------------------------------------------------------------------
def apply_cut_plan_requirements(uow: UnitOfWork, wo: WorkOrder) -> None:
    """Sheet materials linked to a plan require the plan's boards (requirement_source=cut_plan)."""
    from app.modules.cutting.models import Plan
    from app.modules.cutting.release import readiness

    for m in materials_of(uow, wo.id, lock=True):
        if m.cut_plan_id is None:
            continue
        plan = uow.session.get(Plan, m.cut_plan_id)
        boards = readiness(uow, plan).boards if plan is not None else None
        if boards:
            m.qty_required = Decimal(boards)
            m.requirement_source = RequirementSource.CUT_PLAN.value
    uow.flush()


def link_cut_plan(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: CutPlanLink) -> WorkOrder:
    """Link a cut plan to the board operation; the chosen sheet material then requires the plan's boards. On a released
    work order the plan must be ready and is released immediately; reservations follow the new requirement."""
    from app.modules.cutting.models import Plan
    from app.modules.cutting.release import readiness, release_for_work_order, visible_plan

    wo = get_work_order(uow, work_order_id, "transition", for_update=True)
    uow.expect_version(wo, data.expected_version)
    if wo.status not in ("draft", "released"):
        raise Conflict(f"{wo.wo_number} is {wo.status}; cut plans are linked before work starts", code=f"work_order_{wo.status}")
    op = _operation(uow, wo, operation_id)
    if not op.is_board_cutting or op.status != OperationStatus.PENDING.value:
        raise Conflict("Only a pending board-cutting operation takes a cut plan", code="not_board_operation")
    plan = visible_plan(uow, data.cut_plan_id)  # 404 for a plan the actor cannot see
    state = readiness(uow, plan)
    if plan.latest_calculation_id is None or state.reason_code in ("plan_archived", "plan_not_calculated"):
        raise Conflict(f"Cut plan {plan.plan_number} has no current calculation", code=state.reason_code or "plan_not_calculated")
    other = uow.session.scalar(select(WoOperation.work_order_id).where(
        WoOperation.company_id == uow.actor.company_id, WoOperation.cut_plan_id == plan.id, WoOperation.id != op.id))
    if other is not None or (plan.status == "released" and op.cut_plan_id != plan.id):
        raise Conflict(f"Cut plan {plan.plan_number} already backs another work order", code="cut_plan_linked_elsewhere")
    if wo.status == "released" and not state.ready:
        raise Conflict(f"Cut plan {plan.plan_number} is not ready ({state.reason_code})", code="cut_plan_not_ready",
                       reason_code=state.reason_code)
    sheets = [m for m in materials_of(uow, wo.id, lock=True) if m.is_sheet_material]
    if data.material_id is not None:
        target = next((m for m in sheets if m.id == data.material_id), None)
        if target is None:
            raise problem(["material_id"], "not a sheet material of this work order", "material_not_sheet")
    elif len(sheets) == 1:
        target = sheets[0]
    else:
        raise problem(["material_id"], "choose which sheet material the plan's boards replace",
                      "material_required" if sheets else "no_sheet_material")
    for m in sheets:
        if m.cut_plan_id == op.cut_plan_id and m.cut_plan_id is not None and m.id != target.id:
            m.cut_plan_id, m.requirement_source, m.qty_required = None, RequirementSource.BOM.value, m.qty_required_bom
    op.cut_plan_id, op.cut_calculation_id = plan.id, plan.latest_calculation_id
    target.cut_plan_id = plan.id
    uow.flush()
    apply_cut_plan_requirements(uow, wo)
    _ = Plan
    if wo.status == "released":
        release_for_work_order(uow, plan.id, wo.id)
        set_block_state(uow, wo, reserve_materials(uow, wo))
    wo.updated_at = uow.now()
    uow.flush()
    uow.audit("production.work_order.cut_plan_linked", resource_type="production.work_order", resource_id=wo.id,
              resource_label=wo.wo_number, details={"cut_plan_id": str(plan.id), "operation_seq": op.seq})
    return wo


def record_offcut(uow: UnitOfWork, work_order_id: uuid.UUID, data: OffcutRecord) -> WorkOrder:
    """A measured offcut becomes stock: a new lot of kind ``offcut`` with its dimensions and grain (the Slice-5 offcut
    reuse reads these lots), posted production -> the warehouse's stock location (offcut lots never count as available)."""
    from app.modules.cutting.models import CalcOffcut

    wo = _for_posting(uow, work_order_id, data.expected_version)
    require_warehouse_for(uow, wo.warehouse_id, "inventory.lot.manage")
    mats = {m.id: m for m in materials_of(uow, wo.id)}
    m = mats.get(data.material_id)
    if m is None or not m.is_sheet_material:
        raise problem(["material_id"], "not a sheet material of this work order", "material_not_sheet")
    op = _operation(uow, wo, data.operation_id) if data.operation_id else None
    if data.predicted_offcut_id is not None:
        calc_ids = [o.cut_calculation_id for o in operations_of(uow, wo.id) if o.cut_calculation_id]
        hit = uow.session.scalar(select(CalcOffcut.id).where(CalcOffcut.id == data.predicted_offcut_id,
                                                             CalcOffcut.calculation_id.in_(calc_ids))) if calc_ids else None
        if hit is None:
            raise problem(["predicted_offcut_id"], "not a predicted offcut of this work order's cut plan", "offcut_not_in_plan")
    n = len(list(uow.session.scalars(select(WoTransaction.id).where(
        WoTransaction.company_id == uow.actor.company_id, WoTransaction.work_order_id == wo.id,
        WoTransaction.kind == TransactionKind.OFFCUT.value)))) + 1
    lot_id = inventory.record_measured_lot(
        uow, product_id=m.component_product_id, lot_code=data.lot_code or f"{wo.wo_number}-OC{n:02d}", lot_kind="offcut",
        length_mm=data.length_mm, width_mm=data.width_mm, thickness_mm=data.thickness_mm, grain_axis=data.grain_axis,
        parent_lot_id=data.parent_lot_id)
    src = inventory.company_location(uow, LocationType.PRODUCTION)
    dest = inventory.default_location(uow, wo.warehouse_id)
    one = Decimal(1)
    line = inventory.PostingLine(product_id=m.component_product_id, quantity=one, uom_code=m.uom_code, from_location_id=src.id,
                                 to_location_id=dest.id, lot_id=lot_id, source_line_type="production.wo_material",
                                 source_line_id=m.id)
    snap = _snap(None, m.component_product_id, one, m.uom_code, lot_id, src.id, dest.id)
    snap["offcut"] = {"length_mm": format(data.length_mm, "f"), "width_mm": format(data.width_mm, "f"),
                      "predicted_offcut_id": str(data.predicted_offcut_id) if data.predicted_offcut_id else None}
    _post(uow, wo, TransactionKind.OFFCUT, [line], [snap], operation_id=op.id if op else None, lot_id=lot_id)
    mark_started(uow, wo)
    wo.updated_at = uow.now()
    uow.flush()
    return wo
