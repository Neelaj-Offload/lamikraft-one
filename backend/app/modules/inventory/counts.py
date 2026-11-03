"""Stock counts (operations.md §3): freeze records each balance as ``system_qty_at_snapshot`` with the movement-sequence
high-water mark, counters enter what they find, the variance is visible before approval, and approval (by someone
other than the person who submitted the count) posts ``counted - snapshot`` per line against the adjustment location,
so movements after the snapshot stay valid and the warehouse never has to stop."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.inventory import events as ev
from app.modules.inventory.enums import CountStatus, LocationType
from app.modules.inventory.locations import company_location, get_location
from app.modules.inventory.models import Location, StockBalance, StockCount, StockCountLine
from app.modules.inventory.policies import can_on_warehouse, require_warehouse
from app.modules.inventory.posting import PostingLine, PostingRequest, high_water_seq, post_movement
from app.modules.inventory.reads import (
    location_ref,
    location_refs,
    lot_refs,
    product_refs,
    user_refs,
    warehouse_refs,
)
from app.modules.inventory.schemas import (
    CountCreate,
    CountEntries,
    CountLineAdd,
    CountLineRead,
    CountRead,
    Decision,
    Versioned,
)
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


def _lines(uow: UnitOfWork, count: StockCount) -> list[StockCountLine]:
    return list(
        uow.session.scalars(
            select(StockCountLine)
            .where(StockCountLine.stock_count_id == count.id)
            .order_by(StockCountLine.line_no)
        )
    )


def count_read(uow: UnitOfWork, count: StockCount) -> CountRead:
    lines = _lines(uow, count)
    products = product_refs(uow, [ln.product_id for ln in lines])
    locs = location_refs(uow, [ln.location_id for ln in lines])
    lots = lot_refs(uow, [ln.lot_id for ln in lines])
    users = user_refs(uow, [count.frozen_by, count.submitted_by, count.approved_by, count.created_by])
    counter = can_on_warehouse(uow, count.warehouse_id, "inventory.stock_count.create")
    approver = can_on_warehouse(uow, count.warehouse_id, "inventory.stock_count.approve")
    own = count.submitted_by == uow.actor.user_id
    st = count.status

    def cap(ok: bool, reason: str) -> Capability:
        return Capability(allowed=ok, reason_code=None if ok else reason)

    variance = [
        ln
        for ln in lines
        if ln.counted_qty is not None and Decimal(ln.counted_qty) != Decimal(ln.system_qty_at_snapshot)
    ]
    location = get_location(uow, count.location_id) if count.location_id else None
    return CountRead(
        id=count.id,
        number=count.number,
        status=CountStatus(st),
        warehouse=warehouse_refs(uow, [count.warehouse_id])[count.warehouse_id],
        location=location_ref(location) if location else None,
        snapshot_seq=count.snapshot_seq,
        frozen_at=count.frozen_at,
        frozen_by=users.get(count.frozen_by) if count.frozen_by else None,
        submitted_by=users.get(count.submitted_by) if count.submitted_by else None,
        approved_by=users.get(count.approved_by) if count.approved_by else None,
        approved_at=count.approved_at,
        posting_id=count.posting_id,
        notes=count.notes,
        lines=[
            CountLineRead(
                id=ln.id,
                line_no=ln.line_no,
                product=products[ln.product_id],
                location=locs[ln.location_id],
                lot=lots.get(ln.lot_id) if ln.lot_id else None,
                system_quantity=Decimal(ln.system_qty_at_snapshot),
                counted_quantity=Decimal(ln.counted_qty) if ln.counted_qty is not None else None,
                variance=(Decimal(ln.counted_qty) - Decimal(ln.system_qty_at_snapshot))
                if ln.counted_qty is not None
                else None,
                unit=ln.uom_code,
            )
            for ln in lines
        ],
        counted_lines=sum(1 for ln in lines if ln.counted_qty is not None),
        variance_lines=len(variance),
        created_at=count.created_at,
        created_by=users.get(count.created_by) if count.created_by else None,
        version=count.version,
        capabilities={
            "freeze": cap(
                counter and st == CountStatus.DRAFT.value,
                "invalid_status" if counter else "permission_denied",
            ),
            "enter": cap(
                counter and st == CountStatus.FROZEN.value,
                "invalid_status" if counter else "permission_denied",
            ),
            "submit": cap(
                counter and st == CountStatus.FROZEN.value,
                "invalid_status" if counter else "permission_denied",
            ),
            "approve": cap(
                approver and st == CountStatus.SUBMITTED.value and not own,
                "approver_is_counter"
                if approver and own
                else "invalid_status"
                if approver
                else "permission_denied",
            ),
            "cancel": cap(
                counter and st in (CountStatus.DRAFT.value, CountStatus.FROZEN.value),
                "invalid_status" if counter else "permission_denied",
            ),
        },
    )


def create_count(uow: UnitOfWork, data: CountCreate) -> StockCount:
    from app.modules.inventory.documents import _number

    wh = require_warehouse(uow, data.warehouse_id, "inventory.stock_count.create")
    if data.location_id is not None:
        loc = get_location(uow, data.location_id)
        if loc.warehouse_id != wh.id:
            raise ValidationFailed(
                "The location is not in this warehouse",
                errors=[
                    {
                        "loc": ["body", "location_id"],
                        "msg": "wrong warehouse",
                        "code": "location_not_in_warehouse",
                    }
                ],
            )
    count = StockCount(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        number="SC",
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        location_id=data.location_id,
        status=CountStatus.DRAFT.value,
        notes=data.notes,
    )
    count.number = _number(uow, "inventory.stock_count", count.id, wh.branch_id)
    uow.add(count)
    uow.flush()
    return count


def _locked(uow: UnitOfWork, count_id: uuid.UUID, key: str) -> StockCount:
    count = uow.session.scalars(
        select(StockCount)
        .where(StockCount.company_id == uow.actor.company_id, StockCount.id == count_id)
        .with_for_update()
    ).first()
    if count is None:
        raise NotFound(code="not_found", resource_type="inventory.stock_count")
    require_warehouse(uow, count.warehouse_id, key)
    return count


def _scope_locations(uow: UnitOfWork, count: StockCount) -> list[Location]:
    rows = list(
        uow.session.scalars(
            select(Location).where(
                Location.company_id == uow.actor.company_id,
                Location.warehouse_id == count.warehouse_id,
                Location.location_type == LocationType.INTERNAL.value,
            )
        )
    )
    if count.location_id is None:
        return rows
    wanted = {count.location_id}
    grew = True
    while grew:  # the location and its bins
        grew = False
        for loc in rows:
            if loc.parent_id in wanted and loc.id not in wanted:
                wanted.add(loc.id)
                grew = True
    return [loc for loc in rows if loc.id in wanted]


def freeze_count(uow: UnitOfWork, count_id: uuid.UUID, data: Versioned) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.create")
    uow.expect_version(count, data.expected_version)
    if count.status != CountStatus.DRAFT.value:
        raise Conflict("Only a draft count is frozen", code="invalid_status", current_status=count.status)
    locs = {loc.id for loc in _scope_locations(uow, count)}
    # the snapshot is read under the summaries' share of the posting locks: take the high-water mark first
    count.snapshot_seq = high_water_seq(uow)
    balances = list(
        uow.session.scalars(
            select(StockBalance)
            .where(
                StockBalance.company_id == uow.actor.company_id,
                StockBalance.location_id.in_(locs),
                StockBalance.owner_party_id.is_(None),
                StockBalance.quantity != 0,
            )
            .order_by(StockBalance.product_id, StockBalance.location_id, StockBalance.lot_id)
        )
    )
    products = product_refs(uow, [b.product_id for b in balances])
    for i, b in enumerate(balances, start=1):
        uow.add(
            StockCountLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                stock_count_id=count.id,
                line_no=i,
                product_id=b.product_id,
                location_id=b.location_id,
                lot_id=b.lot_id,
                system_qty_at_snapshot=Decimal(b.quantity),
                uom_code=products[b.product_id].stock_unit or "pcs",
            )
        )
    count.status, count.frozen_at, count.frozen_by = CountStatus.FROZEN.value, uow.now(), uow.actor.user_id
    uow.flush()
    uow.emit(
        ev.COUNT_FROZEN,
        aggregate_id=count.id,
        aggregate_version=count.version,
        payload={"stock_count_id": str(count.id), "posting_id": None},
    )
    return count


def enter_counts(uow: UnitOfWork, count_id: uuid.UUID, data: CountEntries) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.create")
    uow.expect_version(count, data.expected_version)
    if count.status != CountStatus.FROZEN.value:
        raise Conflict(
            "Counts are entered on a frozen count", code="invalid_status", current_status=count.status
        )
    lines = {ln.id: ln for ln in _lines(uow, count)}
    for e in data.entries:
        ln = lines.get(e.line_id)
        if ln is None:
            raise ValidationFailed(
                "Unknown count line",
                errors=[
                    {"loc": ["body", "entries"], "msg": "not a line of this count", "code": "unknown_line"}
                ],
            )
        ln.counted_qty = e.counted_quantity
    count.updated_at = uow.now()
    uow.flush()
    return count


def add_count_line(uow: UnitOfWork, count_id: uuid.UUID, data: CountLineAdd) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.create")
    uow.expect_version(count, data.expected_version)
    if count.status != CountStatus.FROZEN.value:
        raise Conflict(
            "Lines are added to a frozen count", code="invalid_status", current_status=count.status
        )
    if data.location_id not in {loc.id for loc in _scope_locations(uow, count)}:
        raise ValidationFailed(
            "The location is outside this count",
            errors=[
                {"loc": ["body", "location_id"], "msg": "outside the count", "code": "location_not_in_count"}
            ],
        )
    products = product_refs(uow, [data.product_id])
    if data.product_id not in products or products[data.product_id].stock_unit is None:
        raise ValidationFailed(
            "The product is not stock-tracked",
            errors=[
                {
                    "loc": ["body", "product_id"],
                    "msg": "not stock-tracked",
                    "code": "product_not_stock_tracked",
                }
            ],
        )
    existing = _lines(uow, count)
    if any(
        (ln.product_id, ln.location_id, ln.lot_id) == (data.product_id, data.location_id, data.lot_id)
        for ln in existing
    ):
        raise ValidationFailed(
            "That line is already on the count",
            errors=[{"loc": ["body", "product_id"], "msg": "duplicate", "code": "duplicate_line"}],
        )
    uow.add(
        StockCountLine(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            stock_count_id=count.id,
            line_no=len(existing) + 1,
            product_id=data.product_id,
            location_id=data.location_id,
            lot_id=data.lot_id,
            system_qty_at_snapshot=ZERO,
            counted_qty=data.counted_quantity,
            uom_code=products[data.product_id].stock_unit or "pcs",
        )
    )
    count.updated_at = uow.now()
    uow.flush()
    return count


def submit_count(uow: UnitOfWork, count_id: uuid.UUID, data: Versioned) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.create")
    uow.expect_version(count, data.expected_version)
    if count.status != CountStatus.FROZEN.value:
        raise Conflict("Only a frozen count is submitted", code="invalid_status", current_status=count.status)
    missing = [ln.line_no for ln in _lines(uow, count) if ln.counted_qty is None]
    if missing:
        raise ValidationFailed(
            "Every line needs a counted quantity",
            errors=[
                {"loc": ["body", "lines", n], "msg": "not counted", "code": "not_counted"} for n in missing
            ],
        )
    count.status, count.submitted_at, count.submitted_by = (
        CountStatus.SUBMITTED.value,
        uow.now(),
        uow.actor.user_id,
    )
    uow.flush()
    return count


def approve_count(uow: UnitOfWork, count_id: uuid.UUID, data: Decision) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.approve")
    uow.expect_version(count, data.expected_version)
    if count.status != CountStatus.SUBMITTED.value:
        raise Conflict(
            "Only a submitted count is approved", code="invalid_status", current_status=count.status
        )
    if count.submitted_by == uow.actor.user_id:
        raise Forbidden("The person who submitted a count cannot approve it", code="approver_is_counter")
    adjust = company_location(uow, LocationType.ADJUSTMENT).id
    lines = []
    for ln in _lines(uow, count):
        delta = Decimal(ln.counted_qty) - Decimal(ln.system_qty_at_snapshot)  # type: ignore[arg-type]
        if delta == 0:
            continue
        lines.append(
            PostingLine(
                product_id=ln.product_id,
                quantity=abs(delta),
                uom_code=ln.uom_code,
                lot_id=ln.lot_id,
                from_location_id=adjust if delta > 0 else ln.location_id,
                to_location_id=ln.location_id if delta > 0 else adjust,
                source_line_type="inventory.stock_count_line",
                source_line_id=ln.id,
            )
        )
    if lines:
        receipt = post_movement(
            uow,
            PostingRequest(
                source_type="stock_count",
                source_id=count.id,
                purpose="count",
                source_label=count.number,
                reason_code="count_variance",
                allow_reserved_shortfall=True,
                lines=tuple(lines),
            ),
        )
        count.posting_id = receipt.posting.id
    count.status, count.approved_at, count.approved_by = (
        CountStatus.POSTED.value,
        uow.now(),
        uow.actor.user_id,
    )
    uow.flush()
    uow.emit(
        ev.COUNT_POSTED,
        aggregate_id=count.id,
        aggregate_version=count.version,
        payload={
            "stock_count_id": str(count.id),
            "posting_id": str(count.posting_id) if count.posting_id else None,
        },
    )
    uow.audit(
        "inventory.stock_count.approve",
        resource_type="inventory.stock_count",
        resource_id=count.id,
        resource_label=count.number,
        details={"variance_lines": len(lines)},
    )
    return count


def cancel_count(uow: UnitOfWork, count_id: uuid.UUID, data: Versioned) -> StockCount:
    count = _locked(uow, count_id, "inventory.stock_count.create")
    uow.expect_version(count, data.expected_version)
    if count.status not in (CountStatus.DRAFT.value, CountStatus.FROZEN.value):
        raise Conflict(
            "A submitted count is approved or left, not cancelled",
            code="invalid_status",
            current_status=count.status,
        )
    count.status = CountStatus.CANCELLED.value
    uow.flush()
    return count
