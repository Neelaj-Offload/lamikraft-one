"""Masters: work centres (capacity per shift from the work calendar, protected hourly rate), versioned BOMs and
routings.

A BOM or routing version is edited by its author while draft and **approved by someone else** (403
``separation_of_duties``; the database backs it with CHECK ``approved_by <> created_by``). Approval validates the
version (components exist, units convert to the component's stock unit, alternates point at primary lines, no BOM
cycle through the approved versions of the components, routing operations name active work centres) and retires the
previously approved version of the product, so exactly one version is approved at a time. Approved and retired
versions are immutable; a change is a new draft version (``copy_from_id``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import quantize_unit_price
from app.modules.catalogue.models import Product
from app.modules.production import events as ev
from app.modules.production.capacity import center_calendar, shift_reads
from app.modules.production.common import (
    problem,
    product,
    product_refs,
    require_work_center,
    user_refs,
    work_center,
    work_center_refs,
)
from app.modules.production.enums import MasterStatus
from app.modules.production.models import (
    Bom,
    BomLine,
    CapacityException,
    Routing,
    RoutingOperation,
    WorkCenter,
)
from app.modules.production.schemas import (
    BomCreate,
    BomLineIn,
    BomLineRead,
    BomRead,
    BomUpdate,
    CapacityExceptionIn,
    CapacityExceptionRead,
    MasterCommand,
    MasterSummary,
    RoutingCreate,
    RoutingOperationIn,
    RoutingOperationRead,
    RoutingRead,
    RoutingUpdate,
    WorkCenterCreate,
    WorkCenterRead,
    WorkCenterSummary,
    WorkCenterUpdate,
)
from app.platform.org.reference import convert
from app.platform.uow import UnitOfWork

WC_MANAGE = "production.work_center.manage"
CAPACITY_READ = "production.capacity.read"
BOM_READ, BOM_MANAGE, BOM_APPROVE = "production.bom.read", "production.bom.manage", "production.bom.approve"
ROUTING_READ, ROUTING_MANAGE, ROUTING_APPROVE = (
    "production.routing.read",
    "production.routing.manage",
    "production.routing.approve",
)
MAX_DEPTH = 12


# =====================================================================================================
# work centres
# =====================================================================================================
def _calendar_ok(uow: UnitOfWork, calendar_id: uuid.UUID | None) -> None:
    if calendar_id is None:
        return
    from app.platform.org.workcal import WorkCalendar

    cal = uow.session.get(WorkCalendar, calendar_id)
    if cal is None or cal.company_id != uow.actor.company_id:
        raise problem(["calendar_id"], "unknown work calendar", "calendar_not_found")


def _party_ok(uow: UnitOfWork, party_id: uuid.UUID | None) -> None:
    if party_id is None:
        return
    from app.modules.parties.models import Party

    found = uow.session.scalar(select(Party.id).where(Party.company_id == uow.actor.company_id, Party.id == party_id))
    if found is None:
        raise problem(["job_work_party_id"], "unknown party", "party_not_found")


def work_center_summary(uow: UnitOfWork, wc: WorkCenter) -> WorkCenterSummary:
    cc = center_calendar(uow, wc)
    from app.core.money import Money

    rate = (
        Money(amount=wc.rate_per_hour_amount, currency=wc.rate_per_hour_currency)  # type: ignore[arg-type]
        if wc.rate_per_hour_amount is not None
        else None
    )
    return WorkCenterSummary(
        id=wc.id, code=wc.code, name=wc.name, kind=wc.kind,  # type: ignore[arg-type]
        machine_count=wc.machine_count, efficiency_pct=wc.efficiency_pct, is_active=wc.is_active,
        standard_day_minutes=cc.standard_day(), rate_per_hour=rate,
    )


def work_center_read(uow: UnitOfWork, wc: WorkCenter) -> WorkCenterRead:
    base = work_center_summary(uow, wc)
    cc = center_calendar(uow, wc)
    exceptions = [
        CapacityExceptionRead(id=e.id, exception_date=e.exception_date, available_minutes=e.available_minutes,
                              reason=e.reason)
        for e in sorted(cc.exceptions.values(), key=lambda e: e.exception_date)
    ]
    can = uow.actor.can(WC_MANAGE)
    cap = Capability(allowed=can, reason_code=None if can else "permission_denied")
    return WorkCenterRead(
        **base.model_dump(exclude={"redacted_fields"}),
        calendar=cc.ref, shifts=shift_reads(cc), job_work_party_id=wc.job_work_party_id, notes=wc.notes,
        exceptions=exceptions, version=wc.version, capabilities={"update": cap, "manage_exceptions": cap},
    )


def list_work_centers(uow: UnitOfWork, *, include_inactive: bool = False) -> list[WorkCenterSummary]:
    uow.actor.require(CAPACITY_READ)
    stmt = select(WorkCenter).where(WorkCenter.company_id == uow.actor.company_id)
    if not include_inactive:
        stmt = stmt.where(WorkCenter.is_active.is_(True))
    return [work_center_summary(uow, c) for c in uow.session.scalars(stmt.order_by(WorkCenter.code))]


def get_work_center(uow: UnitOfWork, work_center_id: uuid.UUID) -> WorkCenter:
    uow.actor.require(CAPACITY_READ)
    return require_work_center(uow, work_center_id)


def create_work_center(uow: UnitOfWork, data: WorkCenterCreate) -> WorkCenter:
    uow.actor.require(WC_MANAGE)
    if uow.session.scalar(select(WorkCenter.id).where(WorkCenter.company_id == uow.actor.company_id,
                                                      WorkCenter.code == data.code)):
        raise problem(["code"], "code already used", "duplicate_code", "A work centre with this code exists")
    _calendar_ok(uow, data.calendar_id)
    _party_ok(uow, data.job_work_party_id)
    wc = WorkCenter(
        id=uuid.uuid7(), company_id=uow.actor.company_id, code=data.code, name=data.name, kind=data.kind.value,
        calendar_id=data.calendar_id, machine_count=data.machine_count, efficiency_pct=data.efficiency_pct,
        rate_per_hour_amount=quantize_unit_price(data.rate_per_hour.amount) if data.rate_per_hour else None,
        rate_per_hour_currency=data.rate_per_hour.currency if data.rate_per_hour else None,
        job_work_party_id=data.job_work_party_id, notes=data.notes, is_active=True,
    )
    uow.add(wc)
    uow.flush()
    uow.audit("production.work_center.created", resource_type="production.work_center", resource_id=wc.id,
              resource_label=wc.code, restricted_fields=["rate_per_hour_amount"] if data.rate_per_hour else None)
    return wc


def update_work_center(uow: UnitOfWork, work_center_id: uuid.UUID, data: WorkCenterUpdate) -> WorkCenter:
    uow.actor.require(WC_MANAGE)
    wc = require_work_center(uow, work_center_id)
    uow.session.refresh(wc, with_for_update=True)
    uow.expect_version(wc, data.expected_version)
    changed: list[str] = []
    for name in ("name", "machine_count", "efficiency_pct", "is_active", "notes"):
        value = getattr(data, name)
        if value is not None and getattr(wc, name) != value:
            setattr(wc, name, value)
            changed.append(name)
    if "calendar_id" in data.model_fields_set and data.calendar_id != wc.calendar_id:
        _calendar_ok(uow, data.calendar_id)
        wc.calendar_id = data.calendar_id
        changed.append("calendar_id")
    if data.clear_rate:
        wc.rate_per_hour_amount = wc.rate_per_hour_currency = None
        changed.append("rate_per_hour")
    elif data.rate_per_hour is not None:
        wc.rate_per_hour_amount = quantize_unit_price(data.rate_per_hour.amount)
        wc.rate_per_hour_currency = data.rate_per_hour.currency
        changed.append("rate_per_hour")
    if changed:
        wc.updated_at = uow.now()
        uow.flush()
        uow.audit("production.work_center.updated", resource_type="production.work_center", resource_id=wc.id,
                  resource_label=wc.code, details={"changed_fields": changed},
                  restricted_fields=["rate_per_hour_amount"] if "rate_per_hour" in changed else None)
    return wc


def upsert_capacity_exception(uow: UnitOfWork, work_center_id: uuid.UUID, data: CapacityExceptionIn) -> WorkCenter:
    uow.actor.require(WC_MANAGE)
    wc = require_work_center(uow, work_center_id)
    row = uow.session.scalars(
        select(CapacityException).where(
            CapacityException.company_id == uow.actor.company_id, CapacityException.work_center_id == wc.id,
            CapacityException.exception_date == data.exception_date,
        ).with_for_update()
    ).first()
    if row is None:
        uow.add(CapacityException(id=uuid.uuid7(), company_id=uow.actor.company_id, work_center_id=wc.id,
                                  exception_date=data.exception_date, available_minutes=data.available_minutes,
                                  reason=data.reason))
    else:
        row.available_minutes, row.reason, row.updated_at = data.available_minutes, data.reason, uow.now()
    uow.flush()
    from app.modules.production.capacity import refresh_overloads

    refresh_overloads(uow, [(wc.id, data.exception_date)])
    uow.audit("production.capacity_exception.set", resource_type="production.work_center", resource_id=wc.id,
              resource_label=wc.code, details={"date": data.exception_date.isoformat()})
    return wc


def delete_capacity_exception(uow: UnitOfWork, work_center_id: uuid.UUID, exception_id: uuid.UUID) -> WorkCenter:
    uow.actor.require(WC_MANAGE)
    wc = require_work_center(uow, work_center_id)
    row = uow.session.scalars(
        select(CapacityException).where(CapacityException.company_id == uow.actor.company_id,
                                        CapacityException.work_center_id == wc.id, CapacityException.id == exception_id)
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="production.capacity_exception")
    day = row.exception_date
    uow.session.delete(row)
    uow.flush()
    from app.modules.production.capacity import refresh_overloads

    refresh_overloads(uow, [(wc.id, day)])
    return wc


# =====================================================================================================
# versions: shared helpers
# =====================================================================================================
def _next_version(uow: UnitOfWork, model: type[Bom] | type[Routing], product_id: uuid.UUID) -> int:
    uow.advisory_xact_lock(model.__tablename__, str(product_id))
    current = uow.session.scalar(
        select(func.max(model.version_no)).where(model.company_id == uow.actor.company_id,
                                                 model.product_id == product_id)
    )
    return int(current or 0) + 1


def _master_caps(uow: UnitOfWork, row: Bom | Routing, manage: str, approve: str) -> tuple[dict[str, Capability], list[TransitionRead]]:
    draft = row.status == MasterStatus.DRAFT.value
    can_manage = uow.actor.can(manage)
    can_approve = uow.actor.can(approve)
    author = row.created_by == uow.actor.user_id

    def cap(ok: bool, reason: str | None) -> Capability:
        return Capability(allowed=ok, reason_code=None if ok else reason)

    caps = {
        "update": cap(draft and can_manage, "permission_denied" if not can_manage else f"version_{row.status}"),
        "approve": cap(
            draft and can_approve and not author,
            "permission_denied" if not can_approve else ("separation_of_duties" if author else f"version_{row.status}"),
        ),
        "retire": cap(row.status == MasterStatus.APPROVED.value and can_manage,
                      "permission_denied" if not can_manage else f"version_{row.status}"),
        "new_version": cap(can_manage, "permission_denied"),
    }
    transitions = []
    if caps["approve"].allowed:
        transitions.append(TransitionRead(action="approve", to_status="approved", requires_reason=False))
    if caps["retire"].allowed:
        transitions.append(TransitionRead(action="retire", to_status="retired", requires_reason=True))
    return caps, transitions


def _summary(uow: UnitOfWork, row: Bom | Routing, line_count: int) -> MasterSummary:
    products = product_refs(uow, [row.product_id])
    users = user_refs(uow, [row.created_by, row.approved_by])
    return MasterSummary(
        id=row.id, product=products[row.product_id], version_no=row.version_no, status=row.status,  # type: ignore[arg-type]
        author=users.get(row.created_by) if row.created_by else None,
        approved_by=users.get(row.approved_by) if row.approved_by else None,
        approved_at=row.approved_at, updated_at=row.updated_at, line_count=line_count,
    )


def _lock_master(uow: UnitOfWork, model: type[Bom] | type[Routing], row_id: uuid.UUID, read_key: str) -> Bom | Routing:
    uow.actor.require(read_key)
    row = uow.session.scalars(
        select(model).where(model.company_id == uow.actor.company_id, model.id == row_id).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type=f"production.{model.__tablename__.removeprefix('production_')}")
    return row


def _require_draft(row: Bom | Routing) -> None:
    if row.status != MasterStatus.DRAFT.value:
        raise Conflict(f"Version {row.version_no} is {row.status} and cannot change; create a new version",
                       code=f"version_{row.status}")


def _separation(uow: UnitOfWork, row: Bom | Routing, key: str) -> None:
    uow.actor.require(key)
    if row.created_by is not None and row.created_by == uow.actor.user_id:
        raise Forbidden("The author of a version cannot approve it; ask a colleague", code="separation_of_duties",
                        permission=key)


# =====================================================================================================
# BOMs
# =====================================================================================================
def _bom_lines(uow: UnitOfWork, bom_id: uuid.UUID) -> list[BomLine]:
    return list(uow.session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)))


def approved_bom(uow: UnitOfWork, product_id: uuid.UUID) -> Bom | None:
    return uow.session.scalars(
        select(Bom).where(Bom.company_id == uow.actor.company_id, Bom.product_id == product_id,
                          Bom.status == MasterStatus.APPROVED.value)
    ).first()


def approved_routing(uow: UnitOfWork, product_id: uuid.UUID) -> Routing | None:
    return uow.session.scalars(
        select(Routing).where(Routing.company_id == uow.actor.company_id, Routing.product_id == product_id,
                              Routing.status == MasterStatus.APPROVED.value)
    ).first()


def bom_read(uow: UnitOfWork, bom: Bom) -> BomRead:
    lines = _bom_lines(uow, bom.id)
    refs = product_refs(uow, [ln.component_product_id for ln in lines])
    with_bom = set(uow.session.scalars(
        select(Bom.product_id).where(Bom.company_id == uow.actor.company_id, Bom.status == MasterStatus.APPROVED.value,
                                     Bom.product_id.in_([ln.component_product_id for ln in lines]))
    )) if lines else set()
    caps, transitions = _master_caps(uow, bom, BOM_MANAGE, BOM_APPROVE)
    return BomRead(
        **_summary(uow, bom, len(lines)).model_dump(),
        notes=bom.notes, retired_at=bom.retired_at, version=bom.version, capabilities=caps,
        allowed_transitions=transitions,
        lines=[
            BomLineRead(id=ln.id, line_no=ln.line_no, component=refs[ln.component_product_id], qty_per=ln.qty_per,
                        uom_code=ln.uom_code, scrap_pct=ln.scrap_pct, is_sheet_material=ln.is_sheet_material,
                        alternate_for_line_no=ln.alternate_for_line_no,
                        has_approved_bom=ln.component_product_id in with_bom, notes=ln.notes)
            for ln in lines
        ],
    )


def list_boms(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, status: list[str] | None = None,
              q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[MasterSummary], int]:
    uow.actor.require(BOM_READ)
    return _list_masters(uow, Bom, BomLine, "bom_id", product_id, status, q, limit, offset)


def _list_masters(uow: UnitOfWork, model: type[Bom] | type[Routing], child: type, fk: str, product_id: uuid.UUID | None,
                  status: list[str] | None, q: str | None, limit: int, offset: int) -> tuple[list[MasterSummary], int]:
    from app.core.text import LIKE_ESCAPE, contains_pattern

    stmt = select(model).join(Product, Product.id == model.product_id).where(model.company_id == uow.actor.company_id)
    if product_id:
        stmt = stmt.where(model.product_id == product_id)
    if status:
        stmt = stmt.where(model.status.in_(status))
    if q:
        pat = contains_pattern(q.strip())
        stmt = stmt.where(Product.product_key.ilike(pat, escape=LIKE_ESCAPE) | Product.product_name.ilike(pat, escape=LIKE_ESCAPE))
    total = int(uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = list(uow.session.scalars(stmt.order_by(Product.product_key, model.version_no.desc()).limit(limit).offset(offset)))
    counts = dict(uow.session.execute(
        select(getattr(child, fk), func.count()).where(getattr(child, fk).in_([r.id for r in rows])).group_by(getattr(child, fk))
    ).all()) if rows else {}
    return [_summary(uow, r, int(counts.get(r.id, 0))) for r in rows], total


def get_bom(uow: UnitOfWork, bom_id: uuid.UUID) -> Bom:
    uow.actor.require(BOM_READ)
    bom = uow.session.scalars(select(Bom).where(Bom.company_id == uow.actor.company_id, Bom.id == bom_id)).first()
    if bom is None:
        raise NotFound(code="not_found", resource_type="production.bom")
    return bom


def _write_bom_lines(uow: UnitOfWork, bom: Bom, lines: list[BomLineIn]) -> None:
    for old in _bom_lines(uow, bom.id):
        uow.session.delete(old)
    uow.flush()
    errors: list[dict[str, object]] = []
    used: set[int] = set()
    next_no = 1
    rows: list[BomLine] = []
    for i, ln in enumerate(lines):
        loc: list[str | int] = ["lines", i]
        comp = uow.session.scalars(select(Product).where(Product.company_id == uow.actor.company_id,
                                                         Product.id == ln.component_product_id)).first()
        if comp is None:
            errors.append({"loc": ["body", *loc, "component_product_id"], "msg": "unknown product", "code": "product_not_found"})
            continue
        if comp.id == bom.product_id:
            errors.append({"loc": ["body", *loc, "component_product_id"], "msg": "a product cannot contain itself",
                           "code": "bom_cycle"})
            continue
        uom = ln.uom_code or comp.stock_uom_code or comp.unit_of_sale
        if not uom:
            errors.append({"loc": ["body", *loc, "uom_code"], "msg": "the component has no stock unit", "code": "uom_required"})
            continue
        line_no = ln.line_no or next_no
        while line_no in used:
            line_no += 1
        if line_no in used:
            errors.append({"loc": ["body", *loc, "line_no"], "msg": "duplicate line number", "code": "duplicate_line_no"})
            continue
        used.add(line_no)
        next_no = max(next_no, line_no + 1)
        rows.append(BomLine(id=uuid.uuid7(), company_id=uow.actor.company_id, bom_id=bom.id, line_no=line_no,
                            component_product_id=comp.id, qty_per=ln.qty_per, uom_code=uom, scrap_pct=ln.scrap_pct,
                            is_sheet_material=ln.is_sheet_material, alternate_for_line_no=ln.alternate_for_line_no,
                            notes=ln.notes))
    if errors:
        raise ValidationFailed("Some BOM lines are not valid", errors=errors)
    uow.add_all(rows)
    uow.flush()


def create_bom(uow: UnitOfWork, data: BomCreate) -> Bom:
    uow.actor.require(BOM_MANAGE)
    parent = product(uow, data.product_id)
    lines = data.lines
    source: Bom | None = None
    if data.copy_from_id is not None:
        source = get_bom(uow, data.copy_from_id)
        if source.product_id != parent.id:
            raise problem(["copy_from_id"], "a version of another product", "copy_from_other_product")
        if not lines:
            lines = [BomLineIn(line_no=ln.line_no, component_product_id=ln.component_product_id, qty_per=ln.qty_per,
                               uom_code=ln.uom_code, scrap_pct=ln.scrap_pct, is_sheet_material=ln.is_sheet_material,
                               alternate_for_line_no=ln.alternate_for_line_no, notes=ln.notes)
                     for ln in _bom_lines(uow, source.id)]
    bom = Bom(id=uuid.uuid7(), company_id=uow.actor.company_id, product_id=parent.id,
              version_no=_next_version(uow, Bom, parent.id), status=MasterStatus.DRAFT.value,
              notes=data.notes if data.notes is not None else (source.notes if source else None),
              copied_from_id=source.id if source else None)
    uow.add(bom)
    uow.flush()
    _write_bom_lines(uow, bom, lines)
    uow.audit("production.bom.created", resource_type="production.bom", resource_id=bom.id,
              resource_label=f"{parent.product_key} BOM v{bom.version_no}")
    return bom


def update_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: BomUpdate) -> Bom:
    uow.actor.require(BOM_MANAGE)
    bom = _lock_master(uow, Bom, bom_id, BOM_READ)
    assert isinstance(bom, Bom)
    uow.expect_version(bom, data.expected_version)
    _require_draft(bom)
    if data.notes is not None:
        bom.notes = data.notes
    if data.lines is not None:
        _write_bom_lines(uow, bom, data.lines)
    bom.updated_at = uow.now()
    uow.flush()
    return bom


def _component_closure(uow: UnitOfWork, start: set[uuid.UUID], target: uuid.UUID) -> list[uuid.UUID] | None:
    """A path from ``start`` components to ``target`` through approved BOMs (a cycle), or None."""
    frontier = [(c, [c]) for c in sorted(start)]
    seen: set[uuid.UUID] = set()
    while frontier:
        pid, path = frontier.pop(0)
        if pid == target:
            return path
        if pid in seen or len(path) > MAX_DEPTH:
            continue
        seen.add(pid)
        sub = approved_bom(uow, pid)
        if sub is None:
            continue
        for ln in _bom_lines(uow, sub.id):
            frontier.append((ln.component_product_id, [*path, ln.component_product_id]))
    return None


def _validate_bom(uow: UnitOfWork, bom: Bom, lines: list[BomLine]) -> None:
    errors: list[dict[str, object]] = []
    if not lines:
        raise ValidationFailed("A BOM needs at least one component",
                               errors=[{"loc": ["body", "lines"], "msg": "no lines", "code": "no_lines"}])
    primaries = {ln.line_no for ln in lines if ln.alternate_for_line_no is None}
    comps = {p.id: p for p in uow.session.scalars(select(Product).where(
        Product.company_id == uow.actor.company_id, Product.id.in_({ln.component_product_id for ln in lines})))}
    for ln in lines:
        loc = ["body", "lines", ln.line_no]
        if ln.alternate_for_line_no is not None and ln.alternate_for_line_no not in primaries:
            errors.append({"loc": loc, "msg": f"line {ln.alternate_for_line_no} is not a primary line", "code": "alternate_without_primary"})
        comp = comps[ln.component_product_id]
        if not comp.stock_uom_code:
            errors.append({"loc": loc, "msg": f"{comp.product_key} has no stock unit", "code": "stock_uom_missing"})
            continue
        try:
            convert(uow, ln.qty_per, ln.uom_code, comp.stock_uom_code, comp.id)
        except ValidationFailed:
            errors.append({"loc": loc, "msg": f"no conversion from {ln.uom_code} to {comp.stock_uom_code}",
                           "code": "uom_conversion_missing"})
    cycle = _component_closure(uow, {ln.component_product_id for ln in lines}, bom.product_id)
    if cycle is not None:
        keys = {p.id: p.product_key for p in uow.session.scalars(select(Product).where(Product.id.in_(cycle)))}
        errors.append({"loc": ["body", "lines"], "msg": "cycle: " + " > ".join(keys.get(c, str(c)) for c in cycle),
                       "code": "bom_cycle"})
    if errors:
        raise ValidationFailed("This BOM version cannot be approved", errors=errors)


def approve_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: MasterCommand) -> Bom:
    bom = _lock_master(uow, Bom, bom_id, BOM_READ)
    assert isinstance(bom, Bom)
    uow.expect_version(bom, data.expected_version)
    _separation(uow, bom, BOM_APPROVE)
    _require_draft(bom)
    _validate_bom(uow, bom, _bom_lines(uow, bom.id))
    previous = approved_bom(uow, bom.product_id)
    now = uow.now()
    if previous is not None:
        previous.status, previous.retired_at, previous.retired_by = MasterStatus.RETIRED.value, now, uow.actor.user_id
        uow.flush()
    bom.status, bom.approved_by, bom.approved_at, bom.updated_at = MasterStatus.APPROVED.value, uow.actor.user_id, now, now
    uow.flush()
    uow.emit(ev.BOM_APPROVED, aggregate_id=bom.id, aggregate_version=bom.version,
             payload={"bom_id": str(bom.id), "version_no": bom.version_no})
    uow.audit("production.bom.approved", resource_type="production.bom", resource_id=bom.id,
              resource_label=f"BOM v{bom.version_no}", reason=data.reason,
              details={"retired_version_id": str(previous.id) if previous else None})
    return bom


def retire_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: MasterCommand) -> Bom:
    uow.actor.require(BOM_MANAGE)
    bom = _lock_master(uow, Bom, bom_id, BOM_READ)
    assert isinstance(bom, Bom)
    uow.expect_version(bom, data.expected_version)
    if bom.status != MasterStatus.APPROVED.value:
        raise Conflict("Only the approved version can be retired", code=f"version_{bom.status}")
    bom.status, bom.retired_at, bom.retired_by, bom.updated_at = MasterStatus.RETIRED.value, uow.now(), uow.actor.user_id, uow.now()
    uow.flush()
    uow.audit("production.bom.retired", resource_type="production.bom", resource_id=bom.id,
              resource_label=f"BOM v{bom.version_no}", reason=data.reason)
    return bom


# =====================================================================================================
# routings
# =====================================================================================================
def _routing_ops(uow: UnitOfWork, routing_id: uuid.UUID) -> list[RoutingOperation]:
    return list(uow.session.scalars(
        select(RoutingOperation).where(RoutingOperation.routing_id == routing_id).order_by(RoutingOperation.seq)
    ))


def routing_read(uow: UnitOfWork, routing: Routing) -> RoutingRead:
    ops = _routing_ops(uow, routing.id)
    centers = work_center_refs(uow, [o.work_center_id for o in ops])
    caps, transitions = _master_caps(uow, routing, ROUTING_MANAGE, ROUTING_APPROVE)
    return RoutingRead(
        **_summary(uow, routing, len(ops)).model_dump(),
        standard_batch_qty=routing.standard_batch_qty, notes=routing.notes, retired_at=routing.retired_at,
        version=routing.version, capabilities=caps, allowed_transitions=transitions,
        operations=[
            RoutingOperationRead(id=o.id, seq=o.seq, name=o.name, work_center=centers[o.work_center_id],
                                 setup_minutes=o.setup_minutes, run_minutes_per_unit=o.run_minutes_per_unit,
                                 is_board_cutting=o.is_board_cutting, is_job_work=o.is_job_work)
            for o in ops
        ],
    )


def list_routings(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, status: list[str] | None = None,
                  q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[MasterSummary], int]:
    uow.actor.require(ROUTING_READ)
    return _list_masters(uow, Routing, RoutingOperation, "routing_id", product_id, status, q, limit, offset)


def get_routing(uow: UnitOfWork, routing_id: uuid.UUID) -> Routing:
    uow.actor.require(ROUTING_READ)
    r = uow.session.scalars(select(Routing).where(Routing.company_id == uow.actor.company_id, Routing.id == routing_id)).first()
    if r is None:
        raise NotFound(code="not_found", resource_type="production.routing")
    return r


def _write_ops(uow: UnitOfWork, routing: Routing, ops: list[RoutingOperationIn]) -> None:
    for old in _routing_ops(uow, routing.id):
        uow.session.delete(old)
    uow.flush()
    seqs = [o.seq for o in ops]
    if len(set(seqs)) != len(seqs):
        raise problem(["operations"], "operation sequence numbers repeat", "duplicate_seq")
    rows = []
    for i, o in enumerate(ops):
        work_center(uow, o.work_center_id, ["operations", i, "work_center_id"])
        rows.append(RoutingOperation(id=uuid.uuid7(), company_id=uow.actor.company_id, routing_id=routing.id, seq=o.seq,
                                     name=o.name, work_center_id=o.work_center_id, setup_minutes=o.setup_minutes,
                                     run_minutes_per_unit=o.run_minutes_per_unit, is_board_cutting=o.is_board_cutting,
                                     is_job_work=o.is_job_work))
    uow.add_all(rows)
    uow.flush()


def create_routing(uow: UnitOfWork, data: RoutingCreate) -> Routing:
    uow.actor.require(ROUTING_MANAGE)
    parent = product(uow, data.product_id)
    ops = data.operations
    source: Routing | None = None
    if data.copy_from_id is not None:
        source = get_routing(uow, data.copy_from_id)
        if source.product_id != parent.id:
            raise problem(["copy_from_id"], "a version of another product", "copy_from_other_product")
        if not ops:
            ops = [RoutingOperationIn(seq=o.seq, name=o.name, work_center_id=o.work_center_id,
                                      setup_minutes=o.setup_minutes, run_minutes_per_unit=o.run_minutes_per_unit,
                                      is_board_cutting=o.is_board_cutting, is_job_work=o.is_job_work)
                   for o in _routing_ops(uow, source.id)]
    routing = Routing(id=uuid.uuid7(), company_id=uow.actor.company_id, product_id=parent.id,
                      version_no=_next_version(uow, Routing, parent.id), status=MasterStatus.DRAFT.value,
                      standard_batch_qty=data.standard_batch_qty if source is None or "standard_batch_qty" in data.model_fields_set
                      else source.standard_batch_qty,
                      notes=data.notes if data.notes is not None else (source.notes if source else None),
                      copied_from_id=source.id if source else None)
    uow.add(routing)
    uow.flush()
    _write_ops(uow, routing, ops)
    uow.audit("production.routing.created", resource_type="production.routing", resource_id=routing.id,
              resource_label=f"{parent.product_key} routing v{routing.version_no}")
    return routing


def update_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: RoutingUpdate) -> Routing:
    uow.actor.require(ROUTING_MANAGE)
    routing = _lock_master(uow, Routing, routing_id, ROUTING_READ)
    assert isinstance(routing, Routing)
    uow.expect_version(routing, data.expected_version)
    _require_draft(routing)
    if data.standard_batch_qty is not None:
        if data.standard_batch_qty <= 0:
            raise problem(["standard_batch_qty"], "must be greater than zero", "not_positive")
        routing.standard_batch_qty = data.standard_batch_qty
    if data.notes is not None:
        routing.notes = data.notes
    if data.operations is not None:
        _write_ops(uow, routing, data.operations)
    routing.updated_at = uow.now()
    uow.flush()
    return routing


def approve_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: MasterCommand) -> Routing:
    routing = _lock_master(uow, Routing, routing_id, ROUTING_READ)
    assert isinstance(routing, Routing)
    uow.expect_version(routing, data.expected_version)
    _separation(uow, routing, ROUTING_APPROVE)
    _require_draft(routing)
    ops = _routing_ops(uow, routing.id)
    if not ops:
        raise ValidationFailed("A routing needs at least one operation",
                               errors=[{"loc": ["body", "operations"], "msg": "no operations", "code": "no_operations"}])
    inactive = [o.seq for o in ops if not require_work_center(uow, o.work_center_id).is_active]
    if inactive:
        raise ValidationFailed("Some operations use an inactive work centre",
                               errors=[{"loc": ["body", "operations", s], "msg": "inactive work centre",
                                        "code": "work_center_inactive"} for s in inactive])
    previous = approved_routing(uow, routing.product_id)
    now = uow.now()
    if previous is not None:
        previous.status, previous.retired_at, previous.retired_by = MasterStatus.RETIRED.value, now, uow.actor.user_id
        uow.flush()
    routing.status, routing.approved_by, routing.approved_at, routing.updated_at = (
        MasterStatus.APPROVED.value, uow.actor.user_id, now, now)
    uow.flush()
    uow.emit(ev.ROUTING_APPROVED, aggregate_id=routing.id, aggregate_version=routing.version,
             payload={"routing_id": str(routing.id), "version_no": routing.version_no})
    uow.audit("production.routing.approved", resource_type="production.routing", resource_id=routing.id,
              resource_label=f"Routing v{routing.version_no}", reason=data.reason)
    return routing


def retire_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: MasterCommand) -> Routing:
    uow.actor.require(ROUTING_MANAGE)
    routing = _lock_master(uow, Routing, routing_id, ROUTING_READ)
    assert isinstance(routing, Routing)
    uow.expect_version(routing, data.expected_version)
    if routing.status != MasterStatus.APPROVED.value:
        raise Conflict("Only the approved version can be retired", code=f"version_{routing.status}")
    routing.status, routing.retired_at, routing.retired_by, routing.updated_at = (
        MasterStatus.RETIRED.value, uow.now(), uow.actor.user_id, uow.now())
    uow.flush()
    uow.audit("production.routing.retired", resource_type="production.routing", resource_id=routing.id,
              resource_label=f"Routing v{routing.version_no}", reason=data.reason)
    return routing


def bom_lines(uow: UnitOfWork, bom_id: uuid.UUID) -> list[BomLine]:
    return _bom_lines(uow, bom_id)


def routing_operations(uow: UnitOfWork, routing_id: uuid.UUID) -> list[RoutingOperation]:
    return _routing_ops(uow, routing_id)


ZERO = Decimal(0)
