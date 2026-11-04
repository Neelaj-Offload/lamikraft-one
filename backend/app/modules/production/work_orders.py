"""Work orders ``WO-YYYY-NNNN``: plan (from a sales order line or standalone), update while draft, release, complete,
close, cancel; material reservations through the inventory service and the blocked / unblocked state.

State machine (table-driven, ``TRANSITIONS``)::

    draft --release--> released --(first issue, output or operation)--> in_progress --complete--> completed
    completed --close--> closed            draft | released | in_progress --cancel(reason)--> cancelled

Release pins nothing new (the BOM and routing versions are pinned at creation), schedules the operations on the
planned start day, releases linked cut plans (``cutting.plan.released``; a plan that is stale or unverified refuses
the release with 409 ``cut_plan_not_ready``) and reserves every material as inventory demand ``wo_material``
(partial). A material that cannot be fully reserved leaves the work order **blocked** with ``caused_by`` = the
inventory shortage of that component at the warehouse (``production.work_order.blocked``). When stock arrives or is
freed (``inventory.stock.posted`` / ``.posting.reversed`` / ``.reservation.released``) the
``production.material_retry`` consumer reserves again and, once every material is covered, the work order is
**unblocked** (``production.work_order.unblocked``). Every event is handled once (``consumers.once``).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.inventory import service as inventory
from app.modules.inventory.enums import DemandType
from app.modules.inventory.policies import require_warehouse, require_warehouse_for
from app.modules.production import events as ev
from app.modules.production.capacity import pairs_for_work_order, refresh_overloads
from app.modules.production.common import ZERO, business_date, dec, problem, product
from app.modules.production.enums import MasterStatus, OperationStatus, RequirementSource, WorkOrderStatus
from app.modules.production.masters import approved_bom, approved_routing, bom_lines, routing_operations
from app.modules.production.models import Bom, Routing, WoMaterial, WoOperation, WorkOrder
from app.modules.production.schemas import WorkOrderCreate, WorkOrderTransition, WorkOrderUpdate
from app.platform.events.models import DomainEvent
from app.platform.events.service import once
from app.platform.org.reference import convert
from app.platform.uow import UnitOfWork

READ = "production.work_order.read"
CREATE = "production.work_order.create"
UPDATE = "production.work_order.update"
TRANSITION = "production.work_order.transition"
POST = "production.work_order.post"
DEMAND = DemandType.WO_MATERIAL.value
S = WorkOrderStatus

#: action -> (allowed from statuses, to status)
TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "release": (frozenset({S.DRAFT.value}), S.RELEASED.value),
    "complete": (frozenset({S.IN_PROGRESS.value}), S.COMPLETED.value),
    "close": (frozenset({S.COMPLETED.value}), S.CLOSED.value),
    "cancel": (frozenset({S.DRAFT.value, S.RELEASED.value, S.IN_PROGRESS.value}), S.CANCELLED.value),
}
ACTIVE = frozenset({S.RELEASED.value, S.IN_PROGRESS.value})


def wo_path(work_order_id: uuid.UUID) -> str:
    return f"/operations/production/work-orders/{work_order_id}"


# ---- loading ---------------------------------------------------------------------------------------------------------
def get_work_order(uow: UnitOfWork, work_order_id: uuid.UUID, action: str = "read", *, for_update: bool = False) -> WorkOrder:
    """Scoped: an invisible work order is a 404; visible without ``action`` in scope (or against its state) a 403."""
    wo = uow.repo(WorkOrder).get(work_order_id, action, for_update=for_update)
    if for_update:
        uow.session.refresh(wo)
    return wo


def materials_of(uow: UnitOfWork, work_order_id: uuid.UUID, *, lock: bool = False) -> list[WoMaterial]:
    stmt = select(WoMaterial).where(WoMaterial.company_id == uow.actor.company_id,
                                    WoMaterial.work_order_id == work_order_id).order_by(WoMaterial.id)
    rows = list(uow.session.scalars(stmt.with_for_update() if lock else stmt))
    return sorted(rows, key=lambda m: m.line_no)


def operations_of(uow: UnitOfWork, work_order_id: uuid.UUID) -> list[WoOperation]:
    return list(uow.session.scalars(
        select(WoOperation).where(WoOperation.company_id == uow.actor.company_id,
                                  WoOperation.work_order_id == work_order_id).order_by(WoOperation.seq)
    ))


def to_issue(m: WoMaterial) -> Decimal:
    return max(dec(m.qty_required) - (dec(m.qty_issued) - dec(m.qty_returned)), ZERO)


def in_wip(m: WoMaterial) -> Decimal:
    return dec(m.qty_issued) - dec(m.qty_consumed) - dec(m.qty_returned)


# ---- requirements ------------------------------------------------------------------------------------------------------
def _is_integer_uom(uow: UnitOfWork, code: str) -> bool:
    from app.platform.org.models import Uom

    return bool(uow.session.scalar(select(Uom.is_integer).where(Uom.company_id == uow.actor.company_id, Uom.code == code)))


def _requirement(uow: UnitOfWork, qty_planned: Decimal, qty_per: Decimal, scrap_pct: Decimal, uom: str,
                 component_id: uuid.UUID, stock_uom: str) -> Decimal:
    gross = qty_planned * qty_per * (1 + scrap_pct / Decimal(100))
    base = convert(uow, gross, uom, stock_uom, component_id)
    if _is_integer_uom(uow, stock_uom):
        return Decimal(math.ceil(base))
    return base.quantize(Decimal("0.000001"))


def _build_materials(uow: UnitOfWork, wo: WorkOrder, bom: Bom) -> None:
    from app.modules.catalogue.models import Product

    lines = [ln for ln in bom_lines(uow, bom.id) if ln.alternate_for_line_no is None]
    comps = {p.id: p for p in uow.session.scalars(select(Product).where(
        Product.company_id == uow.actor.company_id, Product.id.in_({ln.component_product_id for ln in lines})))}
    errors: list[dict[str, object]] = []
    for ln in lines:
        comp = comps[ln.component_product_id]
        if not comp.is_stock_tracked or not comp.stock_uom_code:
            errors.append({"loc": ["body", "bom_id"], "msg": f"{comp.product_key} is not stock-tracked",
                           "code": "component_not_stock_tracked"})
            continue
        qty = _requirement(uow, dec(wo.qty_planned), dec(ln.qty_per), dec(ln.scrap_pct), ln.uom_code, comp.id,
                           comp.stock_uom_code)
        uow.add(WoMaterial(id=uuid.uuid7(), company_id=uow.actor.company_id, work_order_id=wo.id, line_no=ln.line_no,
                           bom_line_id=ln.id, component_product_id=comp.id, uom_code=comp.stock_uom_code,
                           qty_required=qty, qty_required_bom=qty, requirement_source=RequirementSource.BOM.value,
                           is_sheet_material=ln.is_sheet_material))
    if errors:
        raise ValidationFailed("The BOM has components that cannot be stocked", errors=errors)
    uow.flush()


def _build_operations(uow: UnitOfWork, wo: WorkOrder, routing: Routing) -> None:
    for op in routing_operations(uow, routing.id):
        planned = dec(op.setup_minutes) + dec(op.run_minutes_per_unit) * dec(wo.qty_planned)
        uow.add(WoOperation(id=uuid.uuid7(), company_id=uow.actor.company_id, work_order_id=wo.id, seq=op.seq,
                            routing_operation_id=op.id, name=op.name, work_center_id=op.work_center_id,
                            setup_minutes=op.setup_minutes, run_minutes_per_unit=op.run_minutes_per_unit,
                            planned_minutes=planned.quantize(Decimal("0.0001")), planned_date=wo.planned_start_date,
                            status=OperationStatus.PENDING.value, is_board_cutting=op.is_board_cutting))
    uow.flush()


def _pin(uow: UnitOfWork, model: type[Bom] | type[Routing], given: uuid.UUID | None, product_id: uuid.UUID, field: str) -> Bom | Routing:
    label = "BOM" if model is Bom else "routing"
    if given is not None:
        row = uow.session.scalars(select(model).where(model.company_id == uow.actor.company_id, model.id == given)).first()
        if row is None or row.product_id != product_id:
            raise problem([field], f"not a {label} of this product", f"{field.removesuffix('_id')}_not_found")
        if row.status != MasterStatus.APPROVED.value:
            raise problem([field], f"the {label} version is {row.status}", f"{field.removesuffix('_id')}_not_approved")
        return row
    found = approved_bom(uow, product_id) if model is Bom else approved_routing(uow, product_id)
    if found is None:
        raise problem([field], f"the product has no approved {label}", f"{field.removesuffix('_id')}_not_approved",
                      f"Approve a {label} for the product before planning a work order")
    return found


def _order_line(uow: UnitOfWork, line_id: uuid.UUID):  # noqa: ANN202
    """The sales order line when its order is visible to the actor (404 otherwise: never confirms an invisible id)."""
    from app.modules.orders.models import SalesOrder, SalesOrderLine

    line = uow.session.scalars(select(SalesOrderLine).where(SalesOrderLine.company_id == uow.actor.company_id,
                                                            SalesOrderLine.id == line_id)).first()
    if line is None:
        raise NotFound(code="not_found", resource_type="orders.sales_order_line")
    order = uow.repo(SalesOrder).get(line.order_id)
    return order, line


def create_work_order(uow: UnitOfWork, data: WorkOrderCreate) -> WorkOrder:
    uow.actor.require(CREATE)
    order = line = None
    product_id, qty, uom, warehouse_id = data.product_id, data.quantity, data.uom_code, data.warehouse_id
    if data.sales_order_line_id is not None:
        order, line = _order_line(uow, data.sales_order_line_id)
        if line.product_id is None:
            raise problem(["sales_order_line_id"], "the line has no catalogue product", "line_not_producible")
        if order.status not in ("draft", "confirmed", "on_hold"):
            raise Conflict(f"Order {order.order_number} is {order.status}", code="order_closed")
        if product_id is not None and product_id != line.product_id:
            raise problem(["product_id"], "the order line is for another product", "product_mismatch")
        product_id = line.product_id
        if qty is None:
            qty, uom = dec(line.qty_remaining), line.uom_code
            if qty <= 0:
                raise problem(["sales_order_line_id"], "nothing remains to make on this line", "line_fulfilled")
        warehouse_id = warehouse_id or order.default_warehouse_id
    if product_id is None or qty is None:
        raise ValidationFailed("Choose the product and the quantity to make", errors=[
            {"loc": ["body", "product_id"], "msg": "required", "code": "required"},
            {"loc": ["body", "quantity"], "msg": "required", "code": "required"}])
    p = product(uow, product_id)
    if not p.is_stock_tracked or not p.stock_uom_code:
        raise problem(["product_id"], f"{p.product_key} is not stock-tracked", "product_not_stock_tracked",
                      "Finished goods must be stock-tracked to receive production output")
    wh = inventory.resolve_warehouse(uow, warehouse_id)
    require_warehouse(uow, wh.id)  # 404 for a warehouse the actor cannot see
    stock_qty, _ = inventory.stock_quantity(uow, p.id, qty, uom or p.stock_uom_code)
    bom = _pin(uow, Bom, data.bom_id, p.id, "bom_id")
    routing = _pin(uow, Routing, data.routing_id, p.id, "routing_id")
    wo_id = uuid.uuid7()
    number = uow.allocate_number(ev.WO_SEQUENCE.key, document_date=business_date(uow), resource_type=ev.WO_SEQUENCE.key,
                                 resource_id=wo_id, branch_id=wh.branch_id)
    wo = WorkOrder(
        id=wo_id, company_id=uow.actor.company_id, branch_id=wh.branch_id, wo_number=number, product_id=p.id,
        bom_id=bom.id, routing_id=routing.id, warehouse_id=wh.id, qty_planned=stock_qty, uom_code=p.stock_uom_code,
        status=S.DRAFT.value, sales_order_id=order.id if order else None, sales_order_line_id=line.id if line else None,
        owner_user_id=uow.actor.user_id, planned_start_date=data.planned_start_date, due_date=data.due_date
        or (order.requested_delivery_date if order else None), notes=data.notes,
        search_text=" ".join(x for x in (number, p.product_key, p.product_name, order.order_number if order else "") if x).lower(),
        blocked_causes=[],
    )
    uow.add(wo)
    uow.flush()
    _build_materials(uow, wo, bom)  # type: ignore[arg-type]
    _build_operations(uow, wo, routing)  # type: ignore[arg-type]
    uow.audit("production.work_order.created", resource_type="production.work_order", resource_id=wo.id,
              resource_label=wo.wo_number, details={"sales_order_line_id": str(line.id) if line else None})
    return wo


def update_work_order(uow: UnitOfWork, work_order_id: uuid.UUID, data: WorkOrderUpdate) -> WorkOrder:
    wo = get_work_order(uow, work_order_id, "update", for_update=True)
    uow.expect_version(wo, data.expected_version)
    changed: list[str] = []
    if data.quantity is not None:
        stock_qty, _ = inventory.stock_quantity(uow, wo.product_id, data.quantity, wo.uom_code)
        if stock_qty != dec(wo.qty_planned):
            wo.qty_planned = stock_qty
            for m in materials_of(uow, wo.id, lock=True):
                uow.session.delete(m)
            links = {o.seq: (o.cut_plan_id, o.cut_calculation_id) for o in operations_of(uow, wo.id)}
            for o in operations_of(uow, wo.id):
                uow.session.delete(o)
            uow.flush()
            _build_materials(uow, wo, uow.session.get(Bom, wo.bom_id))  # type: ignore[arg-type]
            _build_operations(uow, wo, uow.session.get(Routing, wo.routing_id))  # type: ignore[arg-type]
            if any(plan for plan, _c in links.values()):
                for o in operations_of(uow, wo.id):
                    if o.seq in links and links[o.seq][0]:
                        o.cut_plan_id, o.cut_calculation_id = links[o.seq]
                uow.flush()
                from app.modules.production.wip import apply_cut_plan_requirements

                apply_cut_plan_requirements(uow, wo)
            changed.append("quantity")
    for name in ("planned_start_date", "due_date", "notes"):
        if name in data.model_fields_set and getattr(wo, name) != getattr(data, name):
            setattr(wo, name, getattr(data, name))
            changed.append(name)
    if "planned_start_date" in changed:
        for o in operations_of(uow, wo.id):
            o.planned_date = wo.planned_start_date
    if changed:
        wo.updated_at = uow.now()
        uow.flush()
        uow.audit("production.work_order.updated", resource_type="production.work_order", resource_id=wo.id,
                  resource_label=wo.wo_number, details={"changed_fields": changed})
    return wo


# ---- reservations and the blocked state ------------------------------------------------------------------------------
def reserve_materials(uow: UnitOfWork, wo: WorkOrder) -> list[dict[str, str]]:
    """Reserve what is still unreserved of every material (lock order: work order -> materials -> stock summaries).
    Returns the ``caused_by`` refs of the materials still short (the inventory shortage of each component)."""
    mats = materials_of(uow, wo.id, lock=True)
    reserved = inventory.reserved_by_demand(uow, DEMAND, [m.id for m in mats])
    causes: dict[str, dict[str, str]] = {}
    for m in mats:
        need = to_issue(m)
        have = reserved.get(m.id, ZERO)
        if need > have:
            res = inventory.reserve(uow, demand_type=DEMAND, demand_id=m.id, demand_parent_id=wo.id,
                                    demand_label=f"{wo.wo_number} line {m.line_no}", product_id=m.component_product_id,
                                    warehouse_id=wo.warehouse_id, quantity=need - have, reason="work order materials")
            have += res.granted
        elif have > need and have > 0:
            _release_surplus(uow, m, have - need)
            have = need
        if need > have:
            state = inventory.refresh(uow, m.component_product_id, wo.warehouse_id)
            if state is not None:
                causes[str(state.id)] = {"type": "inventory.shortage", "id": str(state.id)}
    return [causes[k] for k in sorted(causes)]


def _release_surplus(uow: UnitOfWork, m: WoMaterial, surplus: Decimal) -> None:
    for res in sorted(inventory.active_for_demand(uow, DEMAND, m.id), key=lambda r: r.created_at, reverse=True):
        if surplus <= 0:
            break
        take = min(surplus, inventory.remaining(res))
        if take > 0:
            inventory.release(uow, res.id, reason_code="requirement_reduced", quantity=take)
            surplus -= take


def release_all(uow: UnitOfWork, wo: WorkOrder, reason_code: str) -> None:
    for m in materials_of(uow, wo.id, lock=True):
        inventory.release_for_demand(uow, DEMAND, m.id, reason_code=reason_code)


def _payload(wo: WorkOrder, causes: list[dict[str, str]] | None = None) -> dict[str, object]:
    return {"work_order_id": str(wo.id), "wo_number": wo.wo_number, "caused_by": causes or []}


def set_block_state(uow: UnitOfWork, wo: WorkOrder, causes: list[dict[str, str]]) -> None:
    if causes:
        if not wo.is_blocked or wo.blocked_causes != causes:
            first = not wo.is_blocked
            wo.is_blocked, wo.blocked_causes = True, causes
            wo.blocked_since = wo.blocked_since or uow.now()
            wo.updated_at = uow.now()
            uow.flush()
            if first:
                uow.emit(ev.WO_BLOCKED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo, causes))
    elif wo.is_blocked:
        previous = list(wo.blocked_causes or [])
        wo.is_blocked, wo.blocked_causes, wo.blocked_since, wo.updated_at = False, [], None, uow.now()
        uow.flush()
        uow.emit(ev.WO_UNBLOCKED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo, previous))


def recheck(uow: UnitOfWork, work_order_id: uuid.UUID) -> WorkOrder:
    """Reserve again now (the same thing the event consumer does when stock arrives)."""
    wo = get_work_order(uow, work_order_id, "transition", for_update=True)
    if wo.status not in ACTIVE:
        raise Conflict(f"{wo.wo_number} is {wo.status}", code=f"work_order_{wo.status}")
    require_warehouse_for(uow, wo.warehouse_id, "inventory.stock.reserve")
    set_block_state(uow, wo, reserve_materials(uow, wo))
    return wo


def _pairs(uow: UnitOfWork, event: DomainEvent) -> set[tuple[uuid.UUID, uuid.UUID]]:
    payload = event.payload or {}
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if event.event_type == "inventory.stock.posted":
        for p in payload.get("product_ids") or []:
            for w in payload.get("warehouse_ids") or []:
                pairs.add((uuid.UUID(str(p)), uuid.UUID(str(w))))
    elif event.event_type == "inventory.reservation.released":
        if payload.get("product_id") and payload.get("warehouse_id"):
            pairs.add((uuid.UUID(str(payload["product_id"])), uuid.UUID(str(payload["warehouse_id"]))))
    elif event.event_type == "inventory.posting.reversed":
        from app.modules.inventory.models import StockMovement

        pid = payload.get("reversal_posting_id")
        if pid:
            for m in uow.session.scalars(select(StockMovement).where(
                    StockMovement.company_id == uow.actor.company_id, StockMovement.posting_id == uuid.UUID(str(pid)))):
                for w in (m.from_warehouse_id, m.to_warehouse_id):
                    if w is not None:
                        pairs.add((m.product_id, w))
    return pairs


def handle_material_retry(uow: UnitOfWork, event: DomainEvent) -> None:
    """``production.material_retry``: blocked work orders needing a component that just became available reserve
    again (oldest planned first); fully covered ones are unblocked. Exactly once per event."""
    if not once(uow, ev.MATERIAL_RETRY, event.id):
        return
    pairs = _pairs(uow, event)
    if not pairs:
        return
    candidates = blocked_for(uow, pairs)
    for wo_id in candidates:
        wo = uow.session.scalars(select(WorkOrder).where(WorkOrder.id == wo_id).with_for_update()).first()
        if wo is None or not wo.is_blocked or wo.status not in ACTIVE:
            continue
        set_block_state(uow, wo, reserve_materials(uow, wo))


def blocked_for(uow: UnitOfWork, pairs: Iterable[tuple[uuid.UUID, uuid.UUID]]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for product_id, warehouse_id in sorted(set(pairs)):
        rows = uow.session.execute(
            select(WorkOrder.id, WorkOrder.planned_start_date, WorkOrder.wo_number)
            .join(WoMaterial, WoMaterial.work_order_id == WorkOrder.id)
            .where(WorkOrder.company_id == uow.actor.company_id, WorkOrder.is_blocked.is_(True),
                   WorkOrder.status.in_(ACTIVE), WorkOrder.warehouse_id == warehouse_id,
                   WoMaterial.component_product_id == product_id)
        ).all()
        for r in sorted(rows, key=lambda r: (r[1] is None, r[1], r[2])):
            if r[0] not in out:
                out.append(r[0])
    return out


# ---- the inventory demand provider and pair resolver ---------------------------------------------------------------
def open_demand(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> list[inventory.Demand]:
    """Unreserved remainder of released / in-progress work-order materials (``inventory.shortages`` provider)."""
    mats = list(uow.session.scalars(
        select(WoMaterial).join(WorkOrder, WorkOrder.id == WoMaterial.work_order_id).where(
            WoMaterial.company_id == uow.actor.company_id, WoMaterial.component_product_id == product_id,
            WorkOrder.warehouse_id == warehouse_id, WorkOrder.status.in_(ACTIVE))
    ))
    reserved = inventory.reserved_by_demand(uow, DEMAND, [m.id for m in mats])
    out = []
    for m in mats:
        left = to_issue(m) - reserved.get(m.id, ZERO)
        if left > 0:
            out.append(inventory.Demand(ref_type="production.wo_material", ref_id=m.id, unreserved=left))
    return out


def pairs_for_event(uow: UnitOfWork, event: DomainEvent) -> set[tuple[uuid.UUID, uuid.UUID]]:
    wo_id = (event.payload or {}).get("work_order_id") or event.aggregate_id
    if not wo_id:
        return set()
    wo = uow.session.get(WorkOrder, uuid.UUID(str(wo_id)))
    if wo is None:
        return set()
    return {(m.component_product_id, wo.warehouse_id) for m in materials_of(uow, wo.id)}


# ---- transitions ---------------------------------------------------------------------------------------------------------
def _check_transition(wo: WorkOrder, action: str) -> str:
    allowed, to = TRANSITIONS[action]
    if wo.status not in allowed:
        raise Conflict(f"{wo.wo_number} is {wo.status}; it cannot {action}", code="invalid_transition",
                       action=action, status=wo.status)
    return to


def transition(uow: UnitOfWork, work_order_id: uuid.UUID, data: WorkOrderTransition) -> WorkOrder:
    wo = get_work_order(uow, work_order_id, "transition", for_update=True)
    uow.expect_version(wo, data.expected_version)
    to = _check_transition(wo, data.action)
    pairs_before = pairs_for_work_order(uow, wo.id)
    if data.action == "release":
        _release(uow, wo)
    elif data.action == "complete":
        if dec(wo.qty_good) <= 0:
            raise Conflict("Record the good output before completing the work order", code="no_output")
        wo.status, wo.completed_at, wo.completed_by = to, uow.now(), uow.actor.user_id
        release_all(uow, wo, "work_order_completed")
        set_block_state(uow, wo, [])
        uow.flush()
        uow.emit(ev.WO_COMPLETED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo))
    elif data.action == "close":
        open_wip = [m.line_no for m in materials_of(uow, wo.id) if in_wip(m) > 0]
        if open_wip:
            raise Conflict("Consume or return the material still in work in progress before closing",
                           code="wip_not_cleared", lines=open_wip)
        wo.status, wo.closed_at, wo.closed_by = to, uow.now(), uow.actor.user_id
        uow.flush()
        uow.emit(ev.WO_CLOSED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo))
    elif data.action == "cancel":
        if data.reason_code is None:
            raise problem(["reason_code"], "a reason is required", "reason_required", "Say why the work order is cancelled")
        mats = materials_of(uow, wo.id)
        if dec(wo.qty_good) > 0 or any(dec(m.qty_consumed) > 0 for m in mats):
            raise Conflict("Output or consumption was posted: complete and close the work order instead",
                           code="work_order_has_postings")
        if any(in_wip(m) > 0 for m in mats):
            raise Conflict("Return the material in work in progress before cancelling", code="wip_not_cleared")
        release_all(uow, wo, "work_order_cancelled")
        wo.is_blocked, wo.blocked_causes, wo.blocked_since = False, [], None
        wo.status, wo.cancelled_at, wo.cancelled_by = to, uow.now(), uow.actor.user_id
        wo.cancel_reason_code, wo.cancel_reason = data.reason_code.value, data.reason
        uow.flush()
        uow.emit(ev.WO_CANCELLED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo))
    wo.updated_at = uow.now()
    uow.flush()
    refresh_overloads(uow, pairs_before | pairs_for_work_order(uow, wo.id))
    uow.audit(f"production.work_order.{data.action}", resource_type="production.work_order", resource_id=wo.id,
              resource_label=wo.wo_number, reason=data.reason,
              details={"reason_code": data.reason_code.value if data.reason_code else None})
    return wo


def _release(uow: UnitOfWork, wo: WorkOrder) -> None:
    from app.modules.cutting.models import Plan
    from app.modules.cutting.release import readiness, release_for_work_order

    require_warehouse_for(uow, wo.warehouse_id, "inventory.stock.reserve")
    ops = operations_of(uow, wo.id)
    blockers = []
    for o in ops:
        if o.cut_plan_id is None:
            continue
        plan = uow.session.get(Plan, o.cut_plan_id)
        state = readiness(uow, plan) if plan is not None else None
        if plan is None or state is None or not state.ready:
            blockers.append({"loc": ["operations", o.seq], "msg": state.reason_code if state else "plan missing",
                             "code": state.reason_code if state else "cut_plan_not_found"})
        elif plan.latest_calculation_id != o.cut_calculation_id:
            blockers.append({"loc": ["operations", o.seq], "msg": "the plan was recalculated after it was linked",
                             "code": "cut_plan_recalculated"})
    if blockers:
        raise Conflict("A linked cut plan is not ready for release", code="cut_plan_not_ready", errors=blockers)
    start = wo.planned_start_date or business_date(uow)
    wo.planned_start_date = start
    for o in ops:
        o.planned_date = o.planned_date or start
    wo.status, wo.released_at, wo.released_by = S.RELEASED.value, uow.now(), uow.actor.user_id
    uow.flush()
    for o in ops:
        if o.cut_plan_id is not None:
            release_for_work_order(uow, o.cut_plan_id, wo.id)
    uow.emit(ev.WO_RELEASED, aggregate_id=wo.id, aggregate_version=wo.version, payload=_payload(wo))
    set_block_state(uow, wo, reserve_materials(uow, wo))


def mark_started(uow: UnitOfWork, wo: WorkOrder) -> None:
    if wo.status == S.RELEASED.value:
        wo.status, wo.started_at = S.IN_PROGRESS.value, uow.now()
        uow.flush()
