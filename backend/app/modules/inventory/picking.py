"""Pick lists (ADR-037): picking instructions from a confirmed order's active reservations. Picking itself posts
nothing; the picked quantities feed a draft challan, and the challan's issue is the one movement. A short pick
releases the unpicked part of the reservation (``inventory.reservation.released`` -> shortage refresh) so the shortage
is visible instead of silently stranded."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.inventory import events as ev
from app.modules.inventory.enums import PickLineStatus, PickListStatus, ReservationStatus
from app.modules.inventory.locations import default_location
from app.modules.inventory.models import PickList, PickListLine, Reservation
from app.modules.inventory.policies import can_on_warehouse, require_warehouse
from app.modules.inventory.reads import location_refs, lot_refs, product_refs, user_refs, warehouse_refs
from app.modules.inventory.reservations import release, remaining
from app.modules.inventory.schemas import PickConfirm, PickLineRead, PickListCreate, PickListRead, Versioned
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


def _lines(uow: UnitOfWork, pl: PickList) -> list[PickListLine]:
    return list(
        uow.session.scalars(
            select(PickListLine).where(PickListLine.pick_list_id == pl.id).order_by(PickListLine.line_no)
        )
    )


def pick_list_read(uow: UnitOfWork, pl: PickList) -> PickListRead:
    from app.modules.challans.models import Challan
    from app.modules.orders.models import SalesOrder

    lines = _lines(uow, pl)
    products = product_refs(uow, [ln.product_id for ln in lines])
    locs = location_refs(uow, [ln.location_id for ln in lines])
    lots = lot_refs(uow, [ln.lot_id for ln in lines])
    users = user_refs(uow, [pl.assignee_user_id])
    order_number = (
        uow.session.scalar(select(SalesOrder.order_number).where(SalesOrder.id == pl.order_id)) or ""
    )
    challan_number = (
        uow.session.scalar(select(Challan.challan_number).where(Challan.id == pl.challan_id))
        if pl.challan_id
        else None
    )
    creator = can_on_warehouse(uow, pl.warehouse_id, "inventory.pick_list.create")
    picker = can_on_warehouse(uow, pl.warehouse_id, "inventory.pick_list.update")
    st = pl.status

    def cap(ok: bool, reason: str) -> Capability:
        return Capability(allowed=ok, reason_code=None if ok else reason)

    challan_ok = (
        st == PickListStatus.PICKED.value
        and pl.challan_id is None
        and uow.actor.can("challans.challan.create")
    )
    return PickListRead(
        id=pl.id,
        number=pl.number,
        status=PickListStatus(st),
        warehouse=warehouse_refs(uow, [pl.warehouse_id])[pl.warehouse_id],
        order_id=pl.order_id,
        order_number=order_number,
        assignee=users.get(pl.assignee_user_id) if pl.assignee_user_id else None,
        released_at=pl.released_at,
        picked_at=pl.picked_at,
        challan_id=pl.challan_id,
        challan_number=challan_number,
        lines=[
            PickLineRead(
                id=ln.id,
                line_no=ln.line_no,
                order_line_id=ln.order_line_id,
                reservation_id=ln.reservation_id,
                product=products[ln.product_id],
                location=locs[ln.location_id],
                lot=lots.get(ln.lot_id) if ln.lot_id else None,
                requested=Decimal(ln.qty_requested),
                picked=Decimal(ln.qty_picked) if ln.qty_picked is not None else None,
                unit=ln.uom_code,
                status=ln.status,
            )
            for ln in lines
        ],
        created_at=pl.created_at,
        version=pl.version,
        capabilities={
            "release": cap(
                creator and st == PickListStatus.DRAFT.value,
                "invalid_status" if creator else "permission_denied",
            ),
            "pick": cap(
                picker and st == PickListStatus.RELEASED.value,
                "invalid_status" if picker else "permission_denied",
            ),
            "cancel": cap(
                creator and st in (PickListStatus.DRAFT.value, PickListStatus.RELEASED.value),
                "invalid_status" if creator else "permission_denied",
            ),
            "create_challan": cap(
                challan_ok,
                "invalid_status" if uow.actor.can("challans.challan.create") else "permission_denied",
            ),
        },
    )


def create_pick_list(uow: UnitOfWork, data: PickListCreate) -> PickList:
    from app.modules.inventory.documents import _number
    from app.modules.orders.models import SalesOrder

    order = uow.repo(SalesOrder).get(data.order_id)
    if order.status != "confirmed":
        raise Conflict(
            "Pick lists are made for confirmed orders",
            code="order_not_confirmed",
            current_status=order.status,
        )
    if order.default_warehouse_id is None:
        raise ValidationFailed(
            "The order has no warehouse",
            errors=[{"loc": ["body", "order_id"], "msg": "no warehouse", "code": "warehouse_required"}],
        )
    wh = require_warehouse(uow, order.default_warehouse_id, "inventory.pick_list.create")
    reservations = list(
        uow.session.scalars(
            select(Reservation)
            .where(
                Reservation.company_id == uow.actor.company_id,
                Reservation.demand_type == "so_line",
                Reservation.demand_parent_id == order.id,
                Reservation.warehouse_id == wh.id,
                Reservation.status == ReservationStatus.ACTIVE.value,
            )
            .order_by(Reservation.created_at, Reservation.id)
        )
    )
    open_lines = set(
        uow.session.scalars(
            select(PickListLine.reservation_id)
            .join(PickList, PickList.id == PickListLine.pick_list_id)
            .where(
                PickList.order_id == order.id,
                PickList.status.in_([PickListStatus.DRAFT.value, PickListStatus.RELEASED.value]),
            )
        )
    )
    reservations = [r for r in reservations if r.id not in open_lines and remaining(r) > 0]
    if not reservations:
        raise Conflict("Nothing reserved is waiting to be picked", code="nothing_to_pick")
    pl = PickList(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        number="PL",
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        order_id=order.id,
        status=PickListStatus.DRAFT.value,
        assignee_user_id=data.assignee_user_id,
    )
    pl.number = _number(uow, "inventory.pick_list", pl.id, wh.branch_id)
    uow.add(pl)
    uow.flush()
    location = default_location(uow, wh.id).id
    for i, r in enumerate(reservations, start=1):
        uow.add(
            PickListLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                pick_list_id=pl.id,
                line_no=i,
                order_line_id=r.demand_id,
                reservation_id=r.id,
                product_id=r.product_id,
                location_id=r.location_id or location,
                lot_id=r.lot_id,
                qty_requested=remaining(r),
                uom_code=r.uom_code,
                status=PickLineStatus.OPEN.value,
            )
        )
    uow.flush()
    return pl


def _locked(uow: UnitOfWork, pick_list_id: uuid.UUID, key: str) -> PickList:
    pl = uow.session.scalars(
        select(PickList)
        .where(PickList.company_id == uow.actor.company_id, PickList.id == pick_list_id)
        .with_for_update()
    ).first()
    if pl is None:
        raise NotFound(code="not_found", resource_type="inventory.pick_list")
    require_warehouse(uow, pl.warehouse_id, key)
    return pl


def release_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID, data: Versioned) -> PickList:
    pl = _locked(uow, pick_list_id, "inventory.pick_list.create")
    uow.expect_version(pl, data.expected_version)
    if pl.status != PickListStatus.DRAFT.value:
        raise Conflict("Only a draft pick list is released", code="invalid_status", current_status=pl.status)
    pl.status, pl.released_at, pl.released_by = PickListStatus.RELEASED.value, uow.now(), uow.actor.user_id
    uow.flush()
    uow.emit(
        ev.PICK_RELEASED,
        aggregate_id=pl.id,
        aggregate_version=pl.version,
        payload={"pick_list_id": str(pl.id), "order_id": str(pl.order_id)},
    )
    return pl


def confirm_pick(uow: UnitOfWork, pick_list_id: uuid.UUID, data: PickConfirm) -> PickList:
    """Record picked quantities; when every line is picked the list is ``picked`` and short lines release the rest."""
    pl = _locked(uow, pick_list_id, "inventory.pick_list.update")
    uow.expect_version(pl, data.expected_version)
    if pl.status != PickListStatus.RELEASED.value:
        raise Conflict("Only a released pick list is picked", code="invalid_status", current_status=pl.status)
    lines = {ln.id: ln for ln in _lines(uow, pl)}
    for e in data.entries:
        ln = lines.get(e.line_id)
        if ln is None:
            raise ValidationFailed(
                "Unknown pick line",
                errors=[
                    {"loc": ["body", "entries"], "msg": "not a line of this list", "code": "unknown_line"}
                ],
            )
        if Decimal(e.picked_quantity) > Decimal(ln.qty_requested):
            raise ValidationFailed(
                "More picked than requested",
                errors=[
                    {"loc": ["body", "entries"], "msg": "exceeds the requested quantity", "code": "over_pick"}
                ],
            )
        ln.qty_picked = e.picked_quantity
        ln.status = (
            PickLineStatus.PICKED.value
            if Decimal(e.picked_quantity) == Decimal(ln.qty_requested)
            else PickLineStatus.SHORT.value
        )
    uow.flush()
    if all(ln.qty_picked is not None for ln in lines.values()):
        for ln in sorted(lines.values(), key=lambda x: x.line_no):
            short = Decimal(ln.qty_requested) - Decimal(ln.qty_picked)  # type: ignore[arg-type]
            if short > 0:
                res = uow.session.get(Reservation, ln.reservation_id)
                if res is not None and res.status == ReservationStatus.ACTIVE.value:
                    release(uow, res.id, reason_code="short_pick", quantity=min(short, remaining(res)))
        pl.status, pl.picked_at, pl.picked_by = PickListStatus.PICKED.value, uow.now(), uow.actor.user_id
        uow.flush()
        uow.emit(
            ev.PICK_PICKED,
            aggregate_id=pl.id,
            aggregate_version=pl.version,
            payload={"pick_list_id": str(pl.id), "order_id": str(pl.order_id)},
        )
    return pl


def cancel_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID, data: Versioned) -> PickList:
    pl = _locked(uow, pick_list_id, "inventory.pick_list.create")
    uow.expect_version(pl, data.expected_version)
    if pl.status not in (PickListStatus.DRAFT.value, PickListStatus.RELEASED.value):
        raise Conflict("A picked list is not cancelled", code="invalid_status", current_status=pl.status)
    pl.status = PickListStatus.CANCELLED.value
    uow.flush()
    return pl


def challan_from_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID) -> uuid.UUID:
    """A draft Outward challan with the picked quantities, linked to the order lines (the issue is the movement)."""
    from app.modules.orders import service as orders
    from app.modules.orders.schemas import ChallanFromOrder
    from app.platform.org.reference import convert

    pl = _locked(uow, pick_list_id, "inventory.stock.read")
    if pl.status != PickListStatus.PICKED.value or pl.challan_id is not None:
        raise Conflict(
            "A challan is made once from a picked list", code="invalid_status", current_status=pl.status
        )
    from app.modules.orders.models import SalesOrderLine

    quantities: dict[uuid.UUID, Decimal] = {}
    for ln in _lines(uow, pl):
        if not ln.qty_picked:
            continue
        order_line = uow.session.get(SalesOrderLine, ln.order_line_id)
        assert order_line is not None
        qty = Decimal(ln.qty_picked)
        if ln.uom_code != order_line.uom_code:
            qty = convert(uow, qty, ln.uom_code, order_line.uom_code, order_line.product_id)
        quantities[ln.order_line_id] = quantities.get(ln.order_line_id, ZERO) + qty
    challan_id = orders.create_challan_for_order(
        uow, pl.order_id, ChallanFromOrder(quantities=quantities, warehouse_id=pl.warehouse_id)
    )
    pl.challan_id = challan_id
    uow.flush()
    return challan_id
