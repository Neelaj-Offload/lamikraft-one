"""Shipments (``SH-YYYY-NNNN``) with dispatch cutoffs, and container profiles / load suggestions.

- A shipment names its order, challan, packing list and transporter; each must be visible to the actor (404).
- The cutoff is entered in company time (date, optional time; default the end of that day's shift in the company
  calendar) and stored as an instant; setting or moving it emits ``logistics.shipment.scheduled`` (the
  ``ops.dispatch_cutoffs`` family turns it into a hard-due task at the cutoff).
- **Dispatch never posts stock.** ``dispatch`` issues the linked draft challan through the challan transition (the
  one stock movement; replay-safe) or accepts an already issued one; the ``logistics.shipment_status`` consumer marks
  the shipment dispatched when the challan is issued elsewhere. Either way the shipment only references the posting.
- ``deliver`` needs evidence (kind, and a file or a note); ``record_exception`` / ``resolve_exception``; ``cancel``
  only before dispatch.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.http.pagination import Page
from app.modules.logistics import events as ev
from app.modules.logistics.enums import ShipmentAction, ShipmentStatus
from app.modules.logistics.load_planner import CartonLine, Container, plan
from app.modules.logistics.models import (
    ContainerProfile,
    PackingList,
    PackingListLine,
    Shipment,
    ShipmentTrackingRef,
)
from app.modules.logistics.schemas import (
    ContainerProfileIn,
    ContainerProfileRead,
    DocRef,
    LoadAllocation,
    LoadSuggestion,
    LoadSuggestionRequest,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentSummary,
    ShipmentTransition,
    ShipmentUpdate,
    SuggestedLoad,
    TrackingRefIn,
    TrackingRefRead,
    UnplannedLine,
)
from app.modules.procurement.common import business_date, cap, invalid, require_scope
from app.platform.events.models import DomainEvent
from app.platform.events.service import once
from app.platform.uow import UnitOfWork

S = ShipmentStatus
A = ShipmentAction
CREATE = "logistics.shipment.create"
PRE_DISPATCH = frozenset({S.PLANNED.value, S.BOOKED.value})

#: (status, action) -> (to status, permission action)
TRANSITIONS: dict[tuple[str, str], tuple[str, str]] = {
    (S.PLANNED.value, A.BOOK.value): (S.BOOKED.value, "transition"),
    (S.PLANNED.value, A.DISPATCH.value): (S.DISPATCHED.value, "transition"),
    (S.BOOKED.value, A.DISPATCH.value): (S.DISPATCHED.value, "transition"),
    (S.DISPATCHED.value, A.IN_TRANSIT.value): (S.IN_TRANSIT.value, "transition"),
    (S.DISPATCHED.value, A.DELIVER.value): (S.DELIVERED.value, "transition"),
    (S.IN_TRANSIT.value, A.DELIVER.value): (S.DELIVERED.value, "transition"),
    (S.EXCEPTION.value, A.DELIVER.value): (S.DELIVERED.value, "transition"),
    (S.DISPATCHED.value, A.RECORD_EXCEPTION.value): (S.EXCEPTION.value, "transition"),
    (S.IN_TRANSIT.value, A.RECORD_EXCEPTION.value): (S.EXCEPTION.value, "transition"),
    (S.EXCEPTION.value, A.RESOLVE_EXCEPTION.value): (S.IN_TRANSIT.value, "transition"),
    (S.PLANNED.value, A.CANCEL.value): (S.CANCELLED.value, "transition"),
    (S.BOOKED.value, A.CANCEL.value): (S.CANCELLED.value, "transition"),
}


def path(shipment_id: uuid.UUID) -> str:
    return f"/operations/dispatch/shipments/{shipment_id}"


def allowed_actions(status: str) -> list[A]:
    return [A(a) for (s, a) in TRANSITIONS if s == status]


def _calendar(uow: UnitOfWork):  # noqa: ANN202
    from app.platform.org.workcal import resolve_view

    return resolve_view(uow, None)


def cutoff_instant(uow: UnitOfWork, d: date, t: time | None) -> datetime:
    """A company-local cutoff as an instant: the given time on that date, else the end of that day's shift."""
    cal = _calendar(uow)
    if t is None:
        return cal.end_of_day_due(d)
    from zoneinfo import ZoneInfo

    return datetime.combine(d, t, tzinfo=cal.tz).astimezone(ZoneInfo("UTC"))


def _visible_order(uow: UnitOfWork, order_id: uuid.UUID):  # noqa: ANN202
    from app.modules.orders.models import SalesOrder

    return uow.repo(SalesOrder).get(order_id)


def _visible_challan(uow: UnitOfWork, challan_id: uuid.UUID):  # noqa: ANN202
    from app.modules.challans.models import Challan

    return uow.repo(Challan).get(challan_id, include_archived=False)


def _visible_packing_list(uow: UnitOfWork, pl_id: uuid.UUID) -> PackingList:
    return uow.repo(PackingList).get(pl_id)


def _transporter(uow: UnitOfWork, party_id: uuid.UUID) -> str:
    from app.modules.parties.models import Party

    return uow.repo(Party).get(party_id).display_name


def _link(
    uow: UnitOfWork, sh: Shipment, *, challan_id: uuid.UUID | None, packing_list_id: uuid.UUID | None
) -> None:
    if challan_id is not None:
        c = _visible_challan(uow, challan_id)
        if sh.sales_order_id is not None and c.sales_order_id not in (None, sh.sales_order_id):
            raise invalid("The challan belongs to another order", ["challan_id"], "challan_order_mismatch")
        if c.status in ("cancelled",):
            raise invalid("The challan is cancelled", ["challan_id"], "challan_cancelled")
        clash = uow.session.scalar(
            select(Shipment.id).where(
                Shipment.company_id == uow.actor.company_id,
                Shipment.challan_id == c.id,
                Shipment.id != sh.id,
                Shipment.status != S.CANCELLED.value,
            )
        )
        if clash is not None:
            raise Conflict("Another shipment already carries this challan", code="challan_already_shipped")
        sh.challan_id = c.id
        if sh.sales_order_id is None and c.sales_order_id is not None:
            sh.sales_order_id = c.sales_order_id
    if packing_list_id is not None:
        pl = _visible_packing_list(uow, packing_list_id)
        if sh.sales_order_id is not None and pl.sales_order_id != sh.sales_order_id:
            raise invalid(
                "The packing list belongs to another order",
                ["packing_list_id"],
                "packing_list_order_mismatch",
            )
        sh.packing_list_id = pl.id


def _schedule(uow: UnitOfWork, sh: Shipment, d: date | None, t: time | None) -> bool:
    """Set the cutoff; True when it changed."""
    if d is None:
        return False
    at = cutoff_instant(uow, d, t)
    if sh.cutoff_at == at:
        return False
    sh.cutoff_date, sh.cutoff_time, sh.cutoff_at = d, t, at
    return True


def _emit_scheduled(uow: UnitOfWork, sh: Shipment) -> None:
    assert sh.cutoff_at is not None
    uow.emit(
        ev.SHIPMENT_SCHEDULED,
        aggregate_id=sh.id,
        aggregate_version=sh.version,
        payload={
            "shipment_id": str(sh.id),
            "shipment_number": sh.shipment_number,
            "cutoff_at": sh.cutoff_at.isoformat(),
        },
    )


def create_shipment(uow: UnitOfWork, data: ShipmentCreate) -> Shipment:
    uow.actor.require(CREATE)
    order = _visible_order(uow, data.sales_order_id) if data.sales_order_id else None
    challan = _visible_challan(uow, data.challan_id) if data.challan_id else None
    if order is None and challan is None:
        raise invalid(
            "Name the order or the challan this shipment carries", ["sales_order_id"], "subject_required"
        )
    if order is None and challan is not None and challan.sales_order_id is not None:
        order = _visible_order(uow, challan.sales_order_id)
    party_id = order.party_id if order is not None else challan.party_id  # type: ignore[union-attr]
    if party_id is None:
        raise invalid("The challan has no party", ["challan_id"], "party_required")
    from app.modules.procurement.common import party_briefs

    party = party_briefs(uow, [party_id])[party_id]
    sh = Shipment(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        shipment_number="SH",
        status=S.PLANNED.value,
        mode=data.mode.value,
        sales_order_id=order.id if order is not None else None,
        party_id=party_id,
        party_name=party.display_name,
        owner_user_id=order.owner_user_id if order is not None else challan.owner_user_id,  # type: ignore[union-attr]
        branch_id=order.branch_id if order is not None else challan.branch_id,  # type: ignore[union-attr]
        transporter_party_id=data.transporter_party_id,
        transporter_name=_transporter(uow, data.transporter_party_id)
        if data.transporter_party_id
        else data.transporter_name,
        planned_dispatch_date=data.planned_dispatch_date,
        notes=data.notes,
    )
    sh.shipment_number = uow.allocate_number(
        "logistics.shipment",
        document_date=business_date(uow),
        resource_type="logistics.shipment",
        resource_id=sh.id,
        branch_id=sh.branch_id,
    )
    sh.search_text = f"{sh.shipment_number} {sh.party_name}".lower()
    uow.add(sh)
    uow.flush()
    _link(uow, sh, challan_id=data.challan_id, packing_list_id=data.packing_list_id)
    scheduled = _schedule(uow, sh, data.cutoff_date, data.cutoff_time)
    uow.flush()
    if scheduled:
        _emit_scheduled(uow, sh)
    uow.audit(
        "logistics.shipment.create",
        resource_type="logistics.shipment",
        resource_id=sh.id,
        resource_label=sh.shipment_number,
    )
    return sh


def _locked(uow: UnitOfWork, shipment_id: uuid.UUID) -> Shipment:
    return uow.repo(Shipment).get(shipment_id, for_update=True)


def update_shipment(uow: UnitOfWork, shipment_id: uuid.UUID, data: ShipmentUpdate) -> Shipment:
    sh = _locked(uow, shipment_id)
    require_scope(uow, Shipment, sh.id, "update")
    uow.expect_version(sh, data.expected_version)
    if sh.status not in PRE_DISPATCH:
        raise Conflict("A dispatched shipment is not edited", code="invalid_status", current_status=sh.status)
    _link(uow, sh, challan_id=data.challan_id, packing_list_id=data.packing_list_id)
    if data.transporter_party_id is not None:
        sh.transporter_party_id = data.transporter_party_id
        sh.transporter_name = _transporter(uow, data.transporter_party_id)
    elif data.transporter_name is not None:
        sh.transporter_name = data.transporter_name
    if data.planned_dispatch_date is not None:
        sh.planned_dispatch_date = data.planned_dispatch_date
    if data.notes is not None:
        sh.notes = data.notes
    sh.updated_at = uow.now()
    scheduled = _schedule(uow, sh, data.cutoff_date, data.cutoff_time)
    uow.flush()
    if scheduled:
        _emit_scheduled(uow, sh)
    return sh


def _emit_status(uow: UnitOfWork, sh: Shipment, name: str) -> None:
    uow.emit(
        name,
        aggregate_id=sh.id,
        aggregate_version=sh.version,
        payload={
            "shipment_id": str(sh.id),
            "challan_id": str(sh.challan_id) if sh.challan_id else None,
            "evidence_kind": sh.evidence_kind,
            "exception_code": sh.exception_code,
        },
    )


def _mark_dispatched(
    uow: UnitOfWork, sh: Shipment, posting_id: uuid.UUID | None, at: datetime | None
) -> None:
    sh.status, sh.dispatched_at, sh.dispatch_posting_id = S.DISPATCHED.value, at or uow.now(), posting_id
    uow.flush()
    _emit_status(uow, sh, ev.SHIPMENT_DISPATCHED)


def transition(uow: UnitOfWork, shipment_id: uuid.UUID, data: ShipmentTransition) -> Shipment:
    sh = _locked(uow, shipment_id)
    t = TRANSITIONS.get((sh.status, data.action.value))
    if t is None:
        raise Conflict(
            "That action is not available now",
            code="invalid_transition",
            current_status=sh.status,
            allowed_transitions=[a.value for a in allowed_actions(sh.status)],
        )
    require_scope(uow, Shipment, sh.id, t[1])
    uow.expect_version(sh, data.expected_version)
    action, now = data.action, uow.now()
    if action is A.DISPATCH:
        return _dispatch(uow, sh)
    if action is A.DELIVER:
        if data.evidence_kind is None or not (data.evidence_file_id or data.evidence_note):
            raise invalid(
                "Record the delivery evidence (kind and a file or a note)",
                ["evidence_kind"],
                "evidence_required",
            )
        if data.evidence_file_id is not None:
            from app.platform.files.models import FileObject

            f = uow.session.get(FileObject, data.evidence_file_id)
            if f is None or f.company_id != uow.actor.company_id:
                raise NotFound(code="not_found", resource_type="files.file")
        sh.delivered_at, sh.evidence_kind = now, data.evidence_kind.value
        sh.evidence_file_id, sh.evidence_note = data.evidence_file_id, data.evidence_note
    elif action is A.RECORD_EXCEPTION:
        if data.exception_code is None:
            raise invalid("Choose what went wrong", ["exception_code"], "exception_code_required")
        sh.exception_code, sh.exception_note, sh.exception_at = data.exception_code.value, data.note, now
    elif action is A.RESOLVE_EXCEPTION:
        sh.status_reason = data.note or data.reason
    elif action is A.CANCEL:
        if not data.reason:
            raise invalid("Give a reason", ["reason"], "reason_required")
        sh.status_reason = data.reason
    sh.status = t[0]
    uow.flush()
    name = {A.DELIVER: ev.SHIPMENT_DELIVERED, A.RECORD_EXCEPTION: ev.SHIPMENT_EXCEPTION}.get(action)
    if name:
        _emit_status(uow, sh, name)
    uow.audit(
        f"logistics.shipment.{action.value}",
        resource_type="logistics.shipment",
        resource_id=sh.id,
        resource_label=sh.shipment_number,
        reason=data.reason,
        details={"to_status": t[0]},
    )
    return sh


def _dispatch(uow: UnitOfWork, sh: Shipment) -> Shipment:
    """Issue the linked challan (the one stock movement) or accept an issued one, then mark the shipment dispatched."""
    if sh.challan_id is None:
        raise Conflict("Link the challan this shipment carries before dispatch", code="challan_required")
    from app.modules.challans.models import Challan
    from app.modules.challans.schemas import ChallanTransition
    from app.modules.challans.transitions import transition_challan

    challan = uow.repo(Challan).get(sh.challan_id, include_archived=False)
    if challan.status == "draft":
        if not uow.actor.can("challans.challan.issue"):
            raise Forbidden(
                "Issuing the challan needs challans.challan.issue",
                code="permission_denied",
                permission="challans.challan.issue",
            )
        challan = transition_challan(
            uow, challan.id, ChallanTransition(action="issue", expected_version=challan.version)
        )
    elif challan.status not in ("issued", "closed"):
        raise Conflict("The challan is not issued", code="challan_not_issued", challan_status=challan.status)
    _mark_dispatched(uow, sh, challan.issue_posting_id, challan.issued_at)
    uow.audit(
        "logistics.shipment.dispatch",
        resource_type="logistics.shipment",
        resource_id=sh.id,
        resource_label=sh.shipment_number,
        details={"challan_number": challan.challan_number},
    )
    return sh


def handle_challan_issued(uow: UnitOfWork, event: DomainEvent) -> None:
    """``logistics.shipment_status``: shipments carrying the issued challan become dispatched (exactly once)."""
    if not once(uow, ev.SHIPMENT_STATUS, event.id):
        return
    cid = (event.payload or {}).get("challan_id")
    if not cid:
        return
    rows = list(
        uow.session.scalars(
            select(Shipment)
            .where(
                Shipment.company_id == uow.actor.company_id,
                Shipment.challan_id == uuid.UUID(str(cid)),
                Shipment.status.in_(PRE_DISPATCH),
            )
            .with_for_update()
        )
    )
    if not rows:
        return
    from app.modules.challans.models import Challan

    challan = uow.session.get(Challan, uuid.UUID(str(cid)))
    for sh in rows:
        _mark_dispatched(
            uow, sh, challan.issue_posting_id if challan else None, challan.issued_at if challan else None
        )


def add_tracking_ref(uow: UnitOfWork, shipment_id: uuid.UUID, data: TrackingRefIn) -> Shipment:
    sh = _locked(uow, shipment_id)
    require_scope(uow, Shipment, sh.id, "update")
    exists = uow.session.scalar(
        select(ShipmentTrackingRef.id).where(
            ShipmentTrackingRef.shipment_id == sh.id,
            ShipmentTrackingRef.ref_type == data.ref_type.value,
            ShipmentTrackingRef.value == data.value,
        )
    )
    if exists is None:
        uow.add(
            ShipmentTrackingRef(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                shipment_id=sh.id,
                ref_type=data.ref_type.value,
                value=data.value,
            )
        )
        sh.updated_at = uow.now()
        uow.flush()
    return sh


# ---- reads -------------------------------------------------------------------------------------------------------
def _cutoff_local(uow: UnitOfWork, at: datetime | None) -> str | None:
    if at is None:
        return None
    local = at.astimezone(_calendar(uow).tz)
    return local.strftime("%d %b %Y %H:%M")


def _summaries(uow: UnitOfWork, rows: list[Shipment]) -> list[dict]:  # type: ignore[type-arg]
    from app.modules.challans.models import Challan
    from app.modules.orders.models import SalesOrder

    orders = {
        r[0]: r
        for r in uow.session.execute(
            select(SalesOrder.id, SalesOrder.order_number, SalesOrder.status).where(
                SalesOrder.id.in_([s.sales_order_id for s in rows if s.sales_order_id])
            )
        ).all()
    }
    challans = {
        r[0]: r
        for r in uow.session.execute(
            select(Challan.id, Challan.challan_number, Challan.status).where(
                Challan.id.in_([s.challan_id for s in rows if s.challan_id])
            )
        ).all()
    }
    now = uow.now()
    return [
        {
            "id": s.id,
            "shipment_number": s.shipment_number,
            "status": s.status,
            "mode": s.mode,
            "party_name": s.party_name,
            "order": DocRef(
                id=s.sales_order_id,
                number=orders[s.sales_order_id][1],
                status=orders[s.sales_order_id][2],
                path=f"/sales/orders/{s.sales_order_id}",
            )
            if s.sales_order_id in orders
            else None,
            "challan": DocRef(
                id=s.challan_id,
                number=challans[s.challan_id][1],
                status=challans[s.challan_id][2],
                path=f"/operations/challans/{s.challan_id}",
            )
            if s.challan_id in challans
            else None,
            "transporter_name": s.transporter_name,
            "planned_dispatch_date": s.planned_dispatch_date,
            "cutoff_at": s.cutoff_at,
            "cutoff_local": _cutoff_local(uow, s.cutoff_at),
            "is_past_cutoff": bool(s.cutoff_at and s.cutoff_at < now and s.status in PRE_DISPATCH),
            "path": path(s.id),
            "version": s.version,
        }
        for s in rows
    ]


def list_shipments(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    sales_order_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[ShipmentSummary]:
    repo = uow.repo(Shipment)
    filters = []
    if status:
        filters.append(Shipment.status.in_(status))
    if sales_order_id is not None:
        filters.append(Shipment.sales_order_id == sales_order_id)
    if q and (f := repo.search_filter(q, ["search_text"])) is not None:
        filters.append(f)
    page = repo.list(
        *filters,
        order_by=[Shipment.cutoff_at.asc().nulls_last(), Shipment.id.desc()],
        limit=limit,
        offset=offset,
    )
    items = [ShipmentSummary(**d) for d in _summaries(uow, list(page.items))]
    return Page[ShipmentSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def detail(uow: UnitOfWork, sh: Shipment) -> ShipmentDetail:
    refs = list(
        uow.session.scalars(
            select(ShipmentTrackingRef)
            .where(ShipmentTrackingRef.shipment_id == sh.id)
            .order_by(ShipmentTrackingRef.ref_type, ShipmentTrackingRef.value)
        )
    )
    pl = uow.session.get(PackingList, sh.packing_list_id) if sh.packing_list_id else None
    repo = uow.repo(Shipment)

    def scoped(action: str) -> bool:
        return (
            uow.session.scalar(select(Shipment.id).where(Shipment.id == sh.id, repo.clause(action)))
            is not None
        )

    caps = {}
    for a in A:
        t = TRANSITIONS.get((sh.status, a.value))
        ok = t is not None and scoped(t[1])
        reason = "invalid_status" if t is None else "permission_denied"
        if ok and a is A.DISPATCH and sh.challan_id is None:
            ok, reason = False, "challan_required"
        caps[a.value] = cap(ok, reason)
    caps["update"] = cap(
        scoped("update") and sh.status in PRE_DISPATCH,
        "invalid_status" if scoped("update") else "permission_denied",
    )
    return ShipmentDetail(
        **_summaries(uow, [sh])[0],
        packing_list=DocRef(
            id=pl.id,
            number=pl.packing_list_number,
            status=pl.status,
            path=f"/operations/dispatch/packing-lists/{pl.id}",
        )
        if pl
        else None,
        dispatched_at=sh.dispatched_at,
        dispatch_posting_id=sh.dispatch_posting_id,
        delivered_at=sh.delivered_at,
        evidence_kind=sh.evidence_kind,
        evidence_file_id=sh.evidence_file_id,
        evidence_note=sh.evidence_note,  # type: ignore[arg-type]
        exception_code=sh.exception_code,
        exception_note=sh.exception_note,
        exception_at=sh.exception_at,  # type: ignore[arg-type]
        notes=sh.notes,
        tracking_refs=[TrackingRefRead(id=r.id, ref_type=r.ref_type, value=r.value) for r in refs],  # type: ignore[arg-type]
        allowed_actions=allowed_actions(sh.status),
        capabilities=caps,
    )


def get_shipment(uow: UnitOfWork, shipment_id: uuid.UUID) -> ShipmentDetail:
    return detail(uow, uow.repo(Shipment).get(shipment_id))


# ---- container profiles and load suggestions -------------------------------------------------------------------------
def _profile_read(p: ContainerProfile) -> ContainerProfileRead:
    return ContainerProfileRead(
        id=p.id,
        code=p.code,
        name=p.name,
        internal_volume_m3=Decimal(p.internal_volume_m3),
        max_payload_kg=Decimal(p.max_payload_kg),
        fill_factor=Decimal(p.fill_factor),
        is_active=p.is_active,
    )


def list_profiles(uow: UnitOfWork) -> list[ContainerProfileRead]:
    if not (uow.actor.can("logistics.load_plan.run") or uow.actor.can("logistics.container_profile.manage")):
        raise Forbidden(code="permission_denied", permission="logistics.load_plan.run")
    rows = uow.session.scalars(
        select(ContainerProfile)
        .where(ContainerProfile.company_id == uow.actor.company_id)
        .order_by(ContainerProfile.code)
    )
    return [_profile_read(p) for p in rows]


def save_profile(uow: UnitOfWork, data: ContainerProfileIn) -> ContainerProfileRead:
    uow.actor.require("logistics.container_profile.manage")
    p = uow.session.scalars(
        select(ContainerProfile).where(
            ContainerProfile.company_id == uow.actor.company_id, ContainerProfile.code == data.code
        )
    ).first()
    if p is None:
        p = ContainerProfile(id=uuid.uuid7(), company_id=uow.actor.company_id, code=data.code)
        uow.add(p)
    p.name, p.internal_volume_m3, p.max_payload_kg, p.fill_factor = (
        data.name,
        data.internal_volume_m3,
        data.max_payload_kg,
        data.fill_factor,
    )
    p.is_active = True
    uow.flush()
    return _profile_read(p)


def suggest_load(uow: UnitOfWork, data: LoadSuggestionRequest) -> LoadSuggestion:
    """Read-only: a deterministic container suggestion for a packing list the actor can read."""
    uow.actor.require("logistics.load_plan.run")
    pl = _visible_packing_list(uow, data.packing_list_id)
    profile = uow.session.scalars(
        select(ContainerProfile).where(
            ContainerProfile.company_id == uow.actor.company_id,
            ContainerProfile.id == data.container_profile_id,
            ContainerProfile.is_active.is_(True),
        )
    ).first()
    if profile is None:
        raise NotFound(code="not_found", resource_type="logistics.container_profile")
    lines = list(
        uow.session.scalars(
            select(PackingListLine)
            .where(PackingListLine.packing_list_id == pl.id)
            .order_by(PackingListLine.line_no)
        )
    )
    from app.modules.catalogue.models import Product

    keys = (
        dict(
            uow.session.execute(
                select(Product.id, Product.product_key).where(Product.id.in_([ln.product_id for ln in lines]))
            ).all()
        )
        if lines
        else {}
    )
    carton_lines = []
    for ln in lines:
        cartons = ln.cartons or 0
        per_cbm = (Decimal(ln.cbm) / cartons) if ln.cbm is not None and cartons else None
        per_kg = (Decimal(ln.gross_kg) / cartons) if ln.gross_kg is not None and cartons else None
        carton_lines.append(
            CartonLine(
                line_no=ln.line_no,
                ref=keys.get(ln.product_id, ""),
                cartons=cartons,
                carton_cbm=per_cbm,
                carton_kg=per_kg,
                is_fragile=ln.is_fragile,
            )
        )
    container = Container(
        volume_m3=Decimal(profile.internal_volume_m3),
        max_payload_kg=Decimal(profile.max_payload_kg),
        fill_factor=Decimal(profile.fill_factor),
    )
    result = plan(carton_lines, container)
    loads = []
    for load in result.loads:
        vol, kg, binding = result.utilisation(container, load)
        loads.append(
            SuggestedLoad(
                index=load.index,
                cbm=load.cbm.quantize(Decimal("0.000001")),
                gross_kg=load.kg.quantize(Decimal("0.001")),
                volume_utilisation_pct=vol,
                payload_utilisation_pct=kg,
                binding_constraint=binding,
                allocations=[
                    LoadAllocation(line_no=a.line_no, product_key=a.ref, cartons=a.cartons)
                    for a in load.allocations
                ],
            )
        )
    return LoadSuggestion(
        label=result.label,
        container=_profile_read(profile),
        container_count=len(loads),
        loads=loads,
        unplanned=[UnplannedLine(line_no=n, reason=r) for n, r in result.unplanned],
        manual_review_line_nos=result.manual_review,
        totals_partial=pl.totals_partial,
    )
