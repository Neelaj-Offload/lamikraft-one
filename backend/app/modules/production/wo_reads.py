"""Work-order read models: list rows and the detail (materials with reserved / free quantities, operations with the
linked cut plan and its predicted offcuts, the stock transactions, capabilities and allowed transitions)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.http.capabilities import Capability, TransitionRead
from app.core.http.pagination import Page
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.inventory import service as inventory
from app.modules.inventory.policies import can_on_warehouse
from app.modules.production.common import (
    ZERO,
    dec,
    product_refs,
    user_refs,
    warehouse_refs,
    work_center_refs,
)
from app.modules.production.masters import _summary, bom_lines
from app.modules.production.models import Bom, Routing, WoMaterial, WorkOrder, WoTransaction
from app.modules.production.schemas import (
    CauseRef,
    CutPlanRef,
    MaterialRead,
    OperationRead,
    OrderLineRef,
    PredictedOffcut,
    TransactionLineRead,
    TransactionRead,
    WorkOrderFilters,
    WorkOrderRead,
    WorkOrderSummary,
)
from app.modules.production.work_orders import (
    DEMAND,
    TRANSITIONS,
    in_wip,
    materials_of,
    operations_of,
    to_issue,
)
from app.platform.uow import UnitOfWork

#: actions shown as transitions (with the reason rule) when the state machine and the scope allow them
_TRANSITION_UI = {"release": False, "complete": False, "close": False, "cancel": True}


def _order_refs(uow: UnitOfWork, rows: list[WorkOrder]) -> dict[uuid.UUID, OrderLineRef]:
    from app.modules.orders.models import SalesOrder, SalesOrderLine

    order_ids = {w.sales_order_id for w in rows if w.sales_order_id}
    if not order_ids:
        return {}
    visible = {o.id: o for o in uow.session.scalars(uow.repo(SalesOrder).select().where(SalesOrder.id.in_(order_ids)))}
    lines = {ln.id: ln for ln in uow.session.scalars(select(SalesOrderLine).where(
        SalesOrderLine.id.in_({w.sales_order_line_id for w in rows if w.sales_order_line_id})))}
    out = {}
    for w in rows:
        o = visible.get(w.sales_order_id) if w.sales_order_id else None
        if o is None:
            continue
        ln = lines.get(w.sales_order_line_id) if w.sales_order_line_id else None
        out[w.id] = OrderLineRef(order_id=o.id, order_number=o.order_number, line_id=ln.id if ln else None,
                                 line_no=ln.line_no if ln else None, path=f"/sales/orders/{o.id}")
    return out


def _summary_rows(uow: UnitOfWork, rows: list[WorkOrder]) -> list[WorkOrderSummary]:
    products = product_refs(uow, [w.product_id for w in rows])
    whs = warehouse_refs(uow, [w.warehouse_id for w in rows])
    users = user_refs(uow, [w.owner_user_id for w in rows])
    orders = _order_refs(uow, rows)
    return [
        WorkOrderSummary(id=w.id, wo_number=w.wo_number, product=products[w.product_id], qty_planned=w.qty_planned,
                         uom_code=w.uom_code, qty_good=w.qty_good, status=w.status, is_blocked=w.is_blocked,  # type: ignore[arg-type]
                         warehouse=whs[w.warehouse_id], owner=users.get(w.owner_user_id),
                         planned_start_date=w.planned_start_date, due_date=w.due_date, sales_order=orders.get(w.id),
                         updated_at=w.updated_at)
        for w in rows
    ]


def list_work_orders(uow: UnitOfWork, f: WorkOrderFilters, *, limit: int = 50, offset: int = 0) -> Page[WorkOrderSummary]:
    conds = []
    for tok in tokens(f.q or ""):
        conds.append(WorkOrder.search_text.ilike(contains_pattern(tok.lower()), escape=LIKE_ESCAPE))
    if f.status:
        conds.append(WorkOrder.status.in_([s.value for s in f.status]))
    if f.blocked is not None:
        conds.append(WorkOrder.is_blocked.is_(f.blocked))
    if f.product_id:
        conds.append(WorkOrder.product_id == f.product_id)
    if f.sales_order_id:
        conds.append(WorkOrder.sales_order_id == f.sales_order_id)
    if f.scope == "mine" and uow.actor.user_id:
        conds.append(WorkOrder.owner_user_id == uow.actor.user_id)
    page = uow.repo(WorkOrder).list(*conds, order_by=[WorkOrder.created_at.desc(), WorkOrder.wo_number.desc()],
                                    limit=limit, offset=offset)
    return Page[WorkOrderSummary](items=_summary_rows(uow, page.items), total=page.total, limit=page.limit,
                                  offset=page.offset)


def _cut_plan_ref(uow: UnitOfWork, plan_id: uuid.UUID, calc_id: uuid.UUID | None) -> CutPlanRef | None:
    from app.modules.cutting.models import Plan
    from app.modules.cutting.release import readiness

    plan = uow.session.get(Plan, plan_id)
    if plan is None:
        return None
    state = readiness(uow, plan)
    recalculated = calc_id is not None and plan.latest_calculation_id != calc_id
    return CutPlanRef(id=plan.id, plan_number=plan.plan_number, name=plan.name, status=plan.status,
                      calculation_id=calc_id, boards=state.boards, stale=bool(plan.inputs_changed_since_calc) or recalculated,
                      requires_verification=plan.requires_physical_verification, verified=plan.verified_at is not None,
                      ready=state.ready and not recalculated,
                      reason_code="cut_plan_recalculated" if recalculated else state.reason_code,
                      path=f"/operations/cutting/{plan.id}")


def _causes(uow: UnitOfWork, wo: WorkOrder) -> list[CauseRef]:
    from app.modules.inventory.models import ShortageState

    out = []
    for c in wo.blocked_causes or []:
        cid = uuid.UUID(c["id"])
        label = None
        if c["type"] == "inventory.shortage":
            s = uow.session.get(ShortageState, cid)
            if s is not None:
                p = product_refs(uow, [s.product_id]).get(s.product_id)
                label = f"Short of {p.product_key if p else 'a component'}"
        out.append(CauseRef(type=c["type"], id=cid, label=label,
                            path="/operations/reservations" if c["type"] == "inventory.shortage" else None))
    return out


def _cap(ok: bool, reason: str | None) -> Capability:
    return Capability(allowed=ok, reason_code=None if ok else (reason or "not_allowed"))


def work_order_read(uow: UnitOfWork, wo: WorkOrder) -> WorkOrderRead:
    from app.modules.cutting.release import predicted_offcuts
    from app.modules.inventory.models import Location

    base = _summary_rows(uow, [wo])[0]
    mats = materials_of(uow, wo.id)
    ops = operations_of(uow, wo.id)
    reserved = inventory.reserved_by_demand(uow, DEMAND, [m.id for m in mats])
    bom = uow.session.get(Bom, wo.bom_id)
    routing = uow.session.get(Routing, wo.routing_id)
    assert bom is not None and routing is not None
    lines = bom_lines(uow, bom.id)
    alt_by_primary: dict[int, list[uuid.UUID]] = {}
    for ln in lines:
        if ln.alternate_for_line_no is not None:
            alt_by_primary.setdefault(ln.alternate_for_line_no, []).append(ln.component_product_id)
    txns = list(uow.session.scalars(select(WoTransaction).where(
        WoTransaction.company_id == uow.actor.company_id, WoTransaction.work_order_id == wo.id)
        .order_by(WoTransaction.created_at.desc(), WoTransaction.id.desc())))
    txn_products = {uuid.UUID(ln["product_id"]) for t in txns for ln in t.lines}
    products = product_refs(uow, [m.component_product_id for m in mats] + [x for v in alt_by_primary.values() for x in v]
                            + list(txn_products))
    centers = work_center_refs(uow, [o.work_center_id for o in ops])
    users = user_refs(uow, [o.completed_by for o in ops] + [t.created_by for t in txns])
    loc_ids = {uuid.UUID(ln[k]) for t in txns for ln in t.lines for k in ("from_location_id", "to_location_id") if ln.get(k)}
    locs = {loc.id: loc.code for loc in uow.session.scalars(select(Location).where(Location.id.in_(loc_ids)))} if loc_ids else {}
    from app.modules.inventory.models import Lot

    lot_ids = {uuid.UUID(ln["lot_id"]) for t in txns for ln in t.lines if ln.get("lot_id")}
    lots = dict(uow.session.execute(select(Lot.id, Lot.lot_code).where(Lot.id.in_(lot_ids))).all()) if lot_ids else {}
    material_reads = []
    for m in mats:
        s = inventory.summary_of(uow, m.component_product_id, wo.warehouse_id)
        free = max(dec(s.available_on_hand) - dec(s.reserved), ZERO) if s is not None else ZERO
        have = reserved.get(m.id, ZERO)
        need = to_issue(m)
        material_reads.append(MaterialRead(
            id=m.id, line_no=m.line_no, component=products[m.component_product_id], uom_code=m.uom_code,
            qty_required=m.qty_required, qty_required_bom=m.qty_required_bom, qty_reserved=have, qty_issued=m.qty_issued,
            qty_consumed=m.qty_consumed, qty_returned=m.qty_returned, qty_in_wip=in_wip(m), qty_to_issue=need,
            qty_free=free, short=wo.status in ("released", "in_progress") and need > have,
            requirement_source=m.requirement_source, is_sheet_material=m.is_sheet_material,  # type: ignore[arg-type]
            cut_plan_id=m.cut_plan_id, alternates=[products[p] for p in alt_by_primary.get(m.line_no, []) if p in products],
            version=m.version))
    op_reads = []
    for o in ops:
        plan = _cut_plan_ref(uow, o.cut_plan_id, o.cut_calculation_id) if o.cut_plan_id else None
        offcuts = [PredictedOffcut(id=c.id, board_no=c.board_no, length_mm=c.length_mm, width_mm=c.width_mm)
                   for c in predicted_offcuts(uow, o.cut_calculation_id)] if o.cut_calculation_id else []
        op_reads.append(OperationRead(
            id=o.id, seq=o.seq, name=o.name, work_center=centers[o.work_center_id], setup_minutes=o.setup_minutes,
            run_minutes_per_unit=o.run_minutes_per_unit, planned_minutes=o.planned_minutes, planned_date=o.planned_date,
            actual_minutes=o.actual_minutes, status=o.status, is_board_cutting=o.is_board_cutting, cut_plan=plan,  # type: ignore[arg-type]
            predicted_offcuts=offcuts, completed_at=o.completed_at,
            completed_by=users.get(o.completed_by) if o.completed_by else None, version=o.version))
    txn_reads = [
        TransactionRead(
            id=t.id, kind=t.kind, posting_id=t.posting_id, lot_id=t.lot_id, qty_good=t.qty_good,  # type: ignore[arg-type]
            qty_scrap=t.qty_scrap, reason=t.reason, created_at=t.created_at,
            created_by=users.get(t.created_by) if t.created_by else None,
            lines=[TransactionLineRead(
                material_id=uuid.UUID(ln["material_id"]) if ln.get("material_id") else None,
                product=products[uuid.UUID(ln["product_id"])], quantity=Decimal(ln["quantity"]), uom_code=ln["uom_code"],
                lot_code=lots.get(uuid.UUID(ln["lot_id"])) if ln.get("lot_id") else None,
                from_location=locs.get(uuid.UUID(ln["from_location_id"])) if ln.get("from_location_id") else None,
                to_location=locs.get(uuid.UUID(ln["to_location_id"])) if ln.get("to_location_id") else None)
                for ln in t.lines])
        for t in txns
    ]
    caps, transitions = _capabilities(uow, wo, mats)
    return WorkOrderRead(
        **base.model_dump(),
        bom=_summary(uow, bom, len(lines)), routing=_summary(uow, routing, len(ops)), qty_scrap=wo.qty_scrap,
        blocked_causes=_causes(uow, wo), blocked_since=wo.blocked_since, notes=wo.notes, materials=material_reads,
        operations=op_reads, transactions=txn_reads, released_at=wo.released_at, completed_at=wo.completed_at,
        closed_at=wo.closed_at, cancelled_at=wo.cancelled_at, cancel_reason_code=wo.cancel_reason_code,
        cancel_reason=wo.cancel_reason, version=wo.version, capabilities=caps, allowed_transitions=transitions,
    )


def _capabilities(uow: UnitOfWork, wo: WorkOrder, mats: list[WoMaterial]) -> tuple[dict[str, Capability], list[TransitionRead]]:
    repo = uow.repo(WorkOrder)
    base = {k: Capability(**v) for k, v in repo.capabilities(wo, ["update", "transition", "post"]).items()}
    stock_ok = can_on_warehouse(uow, wo.warehouse_id, "inventory.stock.post")
    post = base["post"]
    posting = _cap(post.allowed and stock_ok, post.reason_code if not post.allowed else "permission_denied")
    has_wip = any(in_wip(m) > 0 for m in mats)
    caps: dict[str, Capability] = {
        "update": base["update"],
        "issue": _cap(posting.allowed and any(to_issue(m) > 0 for m in mats), posting.reason_code or "nothing_to_issue"),
        "consume": _cap(posting.allowed and has_wip, posting.reason_code or "nothing_in_wip"),
        "return": _cap(posting.allowed and has_wip, posting.reason_code or "nothing_in_wip"),
        "output": _cap(posting.allowed and dec(wo.qty_good) < dec(wo.qty_planned), posting.reason_code or "output_complete"),
        "record_offcut": _cap(posting.allowed and any(m.is_sheet_material for m in mats),
                              posting.reason_code or "no_sheet_material"),
        "complete_operation": _cap(base["post"].allowed, base["post"].reason_code),
        "schedule_operation": _cap(base["transition"].allowed and wo.status in ("draft", "released", "in_progress"),
                                   base["transition"].reason_code or f"work_order_{wo.status}"),
        "link_cut_plan": _cap(base["transition"].allowed and wo.status in ("draft", "released"),
                              base["transition"].reason_code or f"work_order_{wo.status}"),
        "recheck": _cap(base["transition"].allowed and wo.status in ("released", "in_progress"),
                        base["transition"].reason_code or f"work_order_{wo.status}"),
    }
    transitions: list[TransitionRead] = []
    for action, (allowed_from, to) in TRANSITIONS.items():
        ok = base["transition"].allowed and wo.status in allowed_from
        reason = base["transition"].reason_code if not base["transition"].allowed else f"work_order_{wo.status}"
        if ok and action == "complete" and dec(wo.qty_good) <= 0:
            ok, reason = False, "no_output"
        if ok and action == "close" and has_wip:
            ok, reason = False, "wip_not_cleared"
        if ok and action == "cancel" and (dec(wo.qty_good) > 0 or any(dec(m.qty_consumed) > 0 for m in mats) or has_wip):
            ok, reason = False, "work_order_has_postings"
        caps[action] = _cap(ok, reason)
        if ok:
            transitions.append(TransitionRead(action=action, to_status=to, requires_reason=_TRANSITION_UI[action]))
    return caps, transitions
