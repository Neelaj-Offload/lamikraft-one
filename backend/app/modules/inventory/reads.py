"""Inventory read models: stock by product and warehouse (real projections), product positions, the ledger browser,
postings, reservations, shortages and availability. Every read is filtered to the actor's visible warehouses."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, func, or_, select

from app.core.errors import NotFound
from app.core.http.capabilities import Capability
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.catalogue.models import Product
from app.modules.inventory.enums import LocationType
from app.modules.inventory.models import (
    Location,
    Lot,
    ReorderRule,
    Reservation,
    ShortageState,
    StockBalance,
    StockMovement,
    StockPosting,
    StockSummary,
    Warehouse,
)
from app.modules.inventory.policies import can_on_warehouse, visible_warehouse_ids
from app.modules.inventory.schemas import (
    Availability,
    BalanceRead,
    CauseRef,
    InventoryUserRef,
    LocationRef,
    LotRef,
    MovementPage,
    MovementRead,
    PostingRead,
    ProductPosition,
    ProductRef,
    ReservationPage,
    ReservationRead,
    ShortageRead,
    StockPage,
    StockRow,
    StockTotals,
    WarehouseRef,
)
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


# ---- reference builders ----------------------------------------------------------------------------------
def product_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProductRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id.in_(wanted))
    )
    return {
        p.id: ProductRef(
            id=p.id,
            product_key=p.product_key,
            name=p.product_name,
            stock_unit=p.stock_uom_code,
            track_lots=bool(p.track_lots),
        )
        for p in rows
    }


def warehouse_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, WarehouseRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Warehouse).where(Warehouse.company_id == uow.actor.company_id, Warehouse.id.in_(wanted))
    )
    return {w.id: WarehouseRef(id=w.id, code=w.code, name=w.name) for w in rows}


def location_ref(loc: Location) -> LocationRef:
    return LocationRef(
        id=loc.id,
        code=loc.code,
        name=loc.name,
        location_type=LocationType(loc.location_type),
        warehouse_id=loc.warehouse_id,
        stock_category=loc.stock_category,  # type: ignore[arg-type]
    )


def location_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, LocationRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(
        select(Location).where(Location.company_id == uow.actor.company_id, Location.id.in_(wanted))
    )
    return {loc.id: location_ref(loc) for loc in rows}


def lot_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, LotRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.scalars(select(Lot).where(Lot.company_id == uow.actor.company_id, Lot.id.in_(wanted)))
    return {lot.id: LotRef(id=lot.id, lot_code=lot.lot_code, lot_kind=lot.lot_kind) for lot in rows}  # type: ignore[arg-type]


def user_refs(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, InventoryUserRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: InventoryUserRef(id=r[0], display_name=r[1]) for r in rows}


SOURCE_PATHS = {
    "challan": "/operations/challans/{id}",
    "stock_count": "/operations/inventory/stock-takes/{id}",
    "adjustment": "/operations/inventory/adjustments/{id}",
    "opening_batch": "/operations/inventory/opening/{id}",
    "transfer": "/operations/inventory/transfers/{id}",
}


def source_path(source_type: str, source_id: uuid.UUID) -> str | None:
    template = SOURCE_PATHS.get(source_type)
    return template.format(id=source_id) if template else None


# ---- stock by product and warehouse ------------------------------------------------------------------------------
def _location_totals(
    uow: UnitOfWork, pairs: Sequence[tuple[uuid.UUID, uuid.UUID]], types: Sequence[str]
) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    if not pairs:
        return {}
    rows = uow.session.execute(
        select(StockBalance.product_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity))
        .join(Location, Location.id == StockBalance.location_id)
        .where(
            StockBalance.company_id == uow.actor.company_id,
            Location.location_type.in_(list(types)),
            StockBalance.product_id.in_({p for p, _ in pairs}),
            StockBalance.warehouse_id.in_({w for _, w in pairs}),
        )
        .group_by(StockBalance.product_id, StockBalance.warehouse_id)
    ).all()
    return {(r[0], r[1]): Decimal(r[2] or 0) for r in rows}


def _rows(uow: UnitOfWork, summaries: Sequence[StockSummary]) -> list[StockRow]:
    pairs = [(s.product_id, s.warehouse_id) for s in summaries]
    products = product_refs(uow, [p for p, _ in pairs])
    whs = warehouse_refs(uow, [w for _, w in pairs])
    qc = _location_totals(uow, pairs, [LocationType.QC_HOLD.value])
    rej = _location_totals(uow, pairs, [LocationType.REJECTED.value])
    shortages = {
        (s.product_id, s.warehouse_id): Decimal(s.shortfall_qty)
        for s in uow.session.scalars(
            select(ShortageState).where(
                ShortageState.company_id == uow.actor.company_id, ShortageState.status == "open"
            )
        )
    }
    rules = {
        (r.product_id, r.warehouse_id): r
        for r in uow.session.scalars(
            select(ReorderRule).where(
                ReorderRule.company_id == uow.actor.company_id, ReorderRule.is_active.is_(True)
            )
        )
    }
    out = []
    for s in summaries:
        key = (s.product_id, s.warehouse_id)
        available = Decimal(s.available_on_hand) - Decimal(s.reserved)
        rule = rules.get(key)
        out.append(
            StockRow(
                product=products[s.product_id],
                warehouse=whs[s.warehouse_id],
                on_hand=Decimal(s.available_on_hand),
                reserved=Decimal(s.reserved),
                available=available,
                qc_hold=qc.get(key, ZERO),
                rejected=rej.get(key, ZERO),
                unit=products[s.product_id].stock_unit,
                shortage=shortages.get(key),
                reorder_min=Decimal(rule.min_qty) if rule else None,
                below_reorder=bool(rule and available < Decimal(rule.min_qty)),
                version=s.version,
            )
        )
    return out


def stock_page(
    uow: UnitOfWork,
    *,
    q: str | None,
    warehouse_id: uuid.UUID | None,
    short_only: bool,
    limit: int,
    offset: int,
) -> StockPage:
    visible = visible_warehouse_ids(uow)
    conds: list[ColumnElement[bool]] = [
        StockSummary.company_id == uow.actor.company_id,
        StockSummary.warehouse_id.in_(visible),
    ]
    if warehouse_id:
        conds.append(StockSummary.warehouse_id == warehouse_id)
    stmt = select(StockSummary).join(Product, Product.id == StockSummary.product_id).where(*conds)
    for tok in tokens(q or ""):
        stmt = stmt.where(Product.search_text.ilike(contains_pattern(tok), escape=LIKE_ESCAPE))
    if short_only:
        stmt = stmt.where(
            select(ShortageState.id)
            .where(
                ShortageState.product_id == StockSummary.product_id,
                ShortageState.warehouse_id == StockSummary.warehouse_id,
                ShortageState.status == "open",
            )
            .exists()
        )
    total = uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        uow.session.scalars(
            stmt.order_by(Product.product_key, StockSummary.warehouse_id).limit(limit).offset(offset)
        )
    )
    base = select(StockSummary).where(*conds)
    all_pairs = uow.session.execute(
        select(StockSummary.product_id, StockSummary.warehouse_id).where(*conds)
    ).all()
    short = (
        uow.session.scalar(
            select(func.count())
            .select_from(ShortageState)
            .where(
                ShortageState.company_id == uow.actor.company_id,
                ShortageState.status == "open",
                ShortageState.warehouse_id.in_(visible),
                *([ShortageState.warehouse_id == warehouse_id] if warehouse_id else []),
            )
        )
        or 0
    )
    below = sum(1 for r in _rows(uow, list(uow.session.scalars(base))) if r.below_reorder) if all_pairs else 0
    return StockPage(
        items=_rows(uow, rows),
        total=int(total),
        limit=limit,
        offset=offset,
        totals=StockTotals(
            products=len({p for p, _ in all_pairs}), short_products=int(short), below_reorder=below
        ),
    )


def product_position(uow: UnitOfWork, product_id: uuid.UUID) -> ProductPosition:
    products = product_refs(uow, [product_id])
    if product_id not in products:
        raise NotFound(code="not_found", resource_type="catalogue.product")
    visible = set(visible_warehouse_ids(uow))
    summaries = list(
        uow.session.scalars(
            select(StockSummary)
            .where(
                StockSummary.company_id == uow.actor.company_id,
                StockSummary.product_id == product_id,
                StockSummary.warehouse_id.in_(visible),
            )
            .order_by(StockSummary.warehouse_id)
        )
    )
    balances = list(
        uow.session.scalars(
            select(StockBalance)
            .join(Location, Location.id == StockBalance.location_id)
            .where(
                StockBalance.company_id == uow.actor.company_id,
                StockBalance.product_id == product_id,
                StockBalance.quantity != 0,
                Location.is_stock_bearing.is_(True),
                or_(StockBalance.warehouse_id.in_(visible), StockBalance.warehouse_id.is_(None)),
            )
        )
    )
    locs = location_refs(uow, [b.location_id for b in balances])
    lots = lot_refs(uow, [b.lot_id for b in balances])
    from app.modules.parties.models import Party

    owners = (
        {
            r[0]: r[1]
            for r in uow.session.execute(
                select(Party.id, Party.display_name).where(
                    Party.id.in_({b.owner_party_id for b in balances if b.owner_party_id})
                )
            )
        }
        if any(b.owner_party_id for b in balances)
        else {}
    )
    external = sum(
        (
            Decimal(b.quantity)
            for b in balances
            if locs[b.location_id].location_type in (LocationType.EXTERNAL_HOLDING, LocationType.OFFICE)
        ),
        ZERO,
    )
    transit = sum(
        (
            Decimal(b.quantity)
            for b in balances
            if locs[b.location_id].location_type == LocationType.IN_TRANSIT
        ),
        ZERO,
    )
    return ProductPosition(
        product=products[product_id],
        unit=products[product_id].stock_unit,
        warehouses=_rows(uow, summaries),
        balances=[
            BalanceRead(
                location=locs[b.location_id],
                lot=lots.get(b.lot_id) if b.lot_id else None,
                owner_party_id=b.owner_party_id,
                owner_name=owners.get(b.owner_party_id) if b.owner_party_id else None,
                quantity=Decimal(b.quantity),
                last_movement_at=b.last_movement_at,
            )
            for b in sorted(balances, key=lambda b: (locs[b.location_id].code, str(b.lot_id)))
        ],
        external=external,
        in_transit=transit,
    )


def availability(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Availability:
    from app.modules.inventory.policies import require_warehouse

    require_warehouse(uow, warehouse_id)
    s = uow.session.scalars(
        select(StockSummary).where(
            StockSummary.company_id == uow.actor.company_id,
            StockSummary.product_id == product_id,
            StockSummary.warehouse_id == warehouse_id,
        )
    ).first()
    unit = product_refs(uow, [product_id]).get(product_id)
    on_hand = Decimal(s.available_on_hand) if s else ZERO
    reserved = Decimal(s.reserved) if s else ZERO
    return Availability(
        product_id=product_id,
        warehouse_id=warehouse_id,
        on_hand=on_hand,
        reserved=reserved,
        available=on_hand - reserved,
        unit=unit.stock_unit if unit else None,
    )


# ---- the ledger browser ------------------------------------------------------------------------------------------------
def _movement_reads(
    uow: UnitOfWork, rows: Sequence[tuple[StockMovement, StockPosting]]
) -> list[MovementRead]:
    products = product_refs(uow, [m.product_id for m, _ in rows])
    locs = location_refs(uow, [x for m, _ in rows for x in (m.from_location_id, m.to_location_id)])
    lots = lot_refs(uow, [m.lot_id for m, _ in rows])
    return [
        MovementRead(
            id=m.id,
            seq=m.seq,
            posting_id=m.posting_id,
            line_no=m.line_no,
            product=products[m.product_id],
            lot=lots.get(m.lot_id) if m.lot_id else None,
            from_location=locs[m.from_location_id],
            to_location=locs[m.to_location_id],
            quantity=Decimal(m.quantity),
            unit=m.uom_code,
            entered_quantity=Decimal(m.entered_qty),
            entered_unit=m.entered_uom,
            owner_party_id=m.owner_party_id,
            counterparty_party_id=m.counterparty_party_id,
            reservation_id=m.reservation_id,
            source_type=p.source_type,
            source_id=p.source_id,
            source_label=p.source_label,
            source_path=source_path(p.source_type, p.source_id),
            purpose=p.purpose,
            posted_at=p.posted_at,
            is_reversal=p.reverses_posting_id is not None,
        )
        for m, p in rows
    ]


def _visible_movement(uow: UnitOfWork) -> ColumnElement[bool]:
    visible = visible_warehouse_ids(uow)
    return or_(StockMovement.from_warehouse_id.in_(visible), StockMovement.to_warehouse_id.in_(visible))


def movement_page(
    uow: UnitOfWork,
    *,
    product_id: uuid.UUID | None,
    warehouse_id: uuid.UUID | None,
    source_type: str | None,
    source_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    offset: int,
) -> MovementPage:
    stmt = (
        select(StockMovement, StockPosting)
        .join(StockPosting, StockPosting.id == StockMovement.posting_id)
        .where(StockMovement.company_id == uow.actor.company_id, _visible_movement(uow))
    )
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(
            or_(
                StockMovement.from_warehouse_id == warehouse_id, StockMovement.to_warehouse_id == warehouse_id
            )
        )
    if source_type:
        stmt = stmt.where(StockPosting.source_type == source_type)
    if source_id:
        stmt = stmt.where(StockPosting.source_id == source_id)
    if date_from:
        stmt = stmt.where(StockPosting.posted_at >= date_from)
    if date_to:
        stmt = stmt.where(StockPosting.posted_at < date_to)
    total = uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = [
        (r[0], r[1])
        for r in uow.session.execute(
            stmt.order_by(StockMovement.seq.desc()).limit(limit).offset(offset)
        ).all()
    ]
    return MovementPage(items=_movement_reads(uow, rows), total=int(total), limit=limit, offset=offset)


def posting_read(uow: UnitOfWork, posting_id: uuid.UUID) -> PostingRead:
    posting = uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.id == posting_id
        )
    ).first()
    if posting is None:
        raise NotFound(code="not_found", resource_type="inventory.posting")
    movements = list(
        uow.session.scalars(
            select(StockMovement)
            .where(StockMovement.posting_id == posting.id, _visible_movement(uow))
            .order_by(StockMovement.line_no)
        )
    )
    if not movements:
        raise NotFound(code="not_found", resource_type="inventory.posting")
    reversal = uow.session.scalar(
        select(StockPosting.id).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.reverses_posting_id == posting.id
        )
    )
    whs = {w for m in movements for w in (m.from_warehouse_id, m.to_warehouse_id) if w}
    may_reverse = all(can_on_warehouse(uow, w, "inventory.posting.reverse") for w in whs)
    reversible = (
        reversal is None and posting.reverses_posting_id is None and posting.source_type not in ("challan",)
    )
    users = user_refs(uow, [posting.posted_by])
    return PostingRead(
        id=posting.id,
        source_type=posting.source_type,
        source_id=posting.source_id,
        source_label=posting.source_label,
        source_path=source_path(posting.source_type, posting.source_id),
        purpose=posting.purpose,
        reason_code=posting.reason_code,
        reason=posting.reason,
        posted_at=posting.posted_at,
        posted_by=users.get(posting.posted_by) if posting.posted_by else None,
        reverses_posting_id=posting.reverses_posting_id,
        reversed_by_posting_id=reversal,
        movements=_movement_reads(uow, [(m, posting) for m in movements]),
        capabilities={
            "reverse": Capability(
                allowed=may_reverse and reversible,
                reason_code=None
                if may_reverse and reversible
                else (
                    "permission_denied"
                    if not may_reverse
                    else "already_reversed"
                    if reversal
                    else "reverse_through_source_document"
                ),
            )
        },
    )


# ---- reservations ----------------------------------------------------------------------------------------------------
def _demand_path(r: Reservation) -> str | None:
    if r.demand_type == "so_line" and r.demand_parent_id:
        return f"/sales/orders/{r.demand_parent_id}"
    return None


def reservation_reads(uow: UnitOfWork, rows: Sequence[Reservation]) -> list[ReservationRead]:
    from app.modules.inventory.reservations import remaining

    products = product_refs(uow, [r.product_id for r in rows])
    whs = warehouse_refs(uow, [r.warehouse_id for r in rows])
    out = []
    for r in rows:
        may = can_on_warehouse(uow, r.warehouse_id, "inventory.stock.reserve")
        active = r.status == "active"
        out.append(
            ReservationRead(
                id=r.id,
                product=products[r.product_id],
                warehouse=whs[r.warehouse_id],
                quantity=Decimal(r.quantity),
                consumed=Decimal(r.consumed_qty),
                released=Decimal(r.released_qty),
                remaining=remaining(r),
                unit=r.uom_code,
                status=r.status,
                demand_type=r.demand_type,
                demand_id=r.demand_id,
                demand_parent_id=r.demand_parent_id,  # type: ignore[arg-type]
                demand_label=r.demand_label,
                demand_path=_demand_path(r),
                created_at=r.created_at,
                released_at=r.released_at,
                capabilities={
                    "release": Capability(
                        allowed=may and active,
                        reason_code=None
                        if may and active
                        else ("permission_denied" if not may else "reservation_not_active"),
                    )
                },
            )
        )
    return out


def reservation_page(
    uow: UnitOfWork,
    *,
    status: str | None,
    product_id: uuid.UUID | None,
    warehouse_id: uuid.UUID | None,
    demand_parent_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> ReservationPage:
    stmt = select(Reservation).where(
        Reservation.company_id == uow.actor.company_id,
        Reservation.warehouse_id.in_(visible_warehouse_ids(uow)),
    )
    if status:
        stmt = stmt.where(Reservation.status == status)
    if product_id:
        stmt = stmt.where(Reservation.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(Reservation.warehouse_id == warehouse_id)
    if demand_parent_id:
        stmt = stmt.where(Reservation.demand_parent_id == demand_parent_id)
    total = uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        uow.session.scalars(
            stmt.order_by(Reservation.created_at.desc(), Reservation.id.desc()).limit(limit).offset(offset)
        )
    )
    return ReservationPage(items=reservation_reads(uow, rows), total=int(total), limit=limit, offset=offset)


# ---- shortages -------------------------------------------------------------------------------------------------------
def _cause_labels(uow: UnitOfWork, refs: list[dict[str, str]]) -> list[CauseRef]:
    from app.modules.orders.models import SalesOrder, SalesOrderLine

    line_ids = [uuid.UUID(r["id"]) for r in refs if r["type"] == "orders.sales_order_line"]
    labels: dict[str, tuple[str, str]] = {}
    if line_ids:
        for ln, o in uow.session.execute(
            select(SalesOrderLine, SalesOrder)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .where(SalesOrderLine.id.in_(line_ids))
        ).all():
            labels[str(ln.id)] = (f"{o.order_number} · line {ln.line_no}", f"/sales/orders/{o.id}")
    # Slice-4 merge: the other lanes' causes (work-order materials, late PO lines) get labels and links too
    material_ids = [uuid.UUID(r["id"]) for r in refs if r["type"] == "production.wo_material"]
    if material_ids:
        from app.modules.production.models import WoMaterial, WorkOrder

        for m, w in uow.session.execute(
            select(WoMaterial, WorkOrder)
            .join(WorkOrder, WorkOrder.id == WoMaterial.work_order_id)
            .where(WoMaterial.id.in_(material_ids))
        ).all():
            labels[str(m.id)] = (f"{w.wo_number} · material {m.line_no}", f"/operations/production/work-orders/{w.id}")
    po_line_ids = [uuid.UUID(r["id"]) for r in refs if r["type"] == "procurement.purchase_order_line"]
    if po_line_ids:
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderLine

        for pl, po in uow.session.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(PurchaseOrderLine.id.in_(po_line_ids))
        ).all():
            labels[str(pl.id)] = (
                f"{po.po_number} · line {pl.line_no} (expected {pl.expected_date.isoformat()})",
                f"/operations/purchasing/orders/{po.id}",
            )
    return [
        CauseRef(
            type=r["type"],
            id=uuid.UUID(r["id"]),
            label=labels.get(r["id"], (None, None))[0],
            path=labels.get(r["id"], (None, None))[1],
        )
        for r in refs
    ]


def shortage_reads(
    uow: UnitOfWork, *, include_resolved: bool = False, warehouse_id: uuid.UUID | None = None
) -> list[ShortageRead]:
    stmt = select(ShortageState).where(
        ShortageState.company_id == uow.actor.company_id,
        ShortageState.warehouse_id.in_(visible_warehouse_ids(uow)),
    )
    if not include_resolved:
        stmt = stmt.where(ShortageState.status == "open")
    if warehouse_id:
        stmt = stmt.where(ShortageState.warehouse_id == warehouse_id)
    rows = list(uow.session.scalars(stmt.order_by(ShortageState.detected_at, ShortageState.id)))
    products = product_refs(uow, [r.product_id for r in rows])
    whs = warehouse_refs(uow, [r.warehouse_id for r in rows])
    return [
        ShortageRead(
            id=r.id,
            product=products[r.product_id],
            warehouse=whs[r.warehouse_id],
            status=r.status,
            demand=Decimal(r.demand_qty),
            free=Decimal(r.free_qty),
            shortfall=Decimal(r.shortfall_qty),
            unit=products[r.product_id].stock_unit,
            caused_by=_cause_labels(uow, list(r.caused_by or [])),
            version=r.version,
            detected_at=r.detected_at,
            resolved_at=r.resolved_at,
        )
        for r in rows
    ]
