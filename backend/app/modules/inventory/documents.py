"""Inventory documents and master data commands: warehouses, bins, lots, reorder rules, relocations, reversals,
adjustments (draft -> submitted -> posted | rejected, approver never the creator), opening-stock batches (created by
one person, approved by another with MFA step-up; one posting per batch from the opening location) and two-step
transfers (dispatch to in-transit, receive at the destination)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.catalogue.models import Product
from app.modules.inventory import events as ev
from app.modules.inventory.enums import (
    AdjustmentDirection,
    AdjustmentStatus,
    LocationType,
    OpeningStatus,
    TransferStatus,
)
from app.modules.inventory.locations import (
    add_bin,
    company_location,
    create_warehouse_rows,
    default_location,
    get_location,
)
from app.modules.inventory.models import (
    Adjustment,
    AdjustmentLine,
    Location,
    Lot,
    OpeningBatch,
    OpeningBatchLine,
    ReorderRule,
    StockMovement,
    StockPosting,
    Transfer,
    TransferLine,
    Warehouse,
)
from app.modules.inventory.policies import can_on_warehouse, require_warehouse
from app.modules.inventory.posting import PostingLine, PostingRequest, post_movement, reverse_posting
from app.modules.inventory.reads import (
    location_ref,
    location_refs,
    lot_refs,
    product_refs,
    user_refs,
    warehouse_refs,
)
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    BinCreate,
    Decision,
    DocLineRead,
    DocumentRead,
    DocumentSummary,
    LotCreate,
    LotMeasure,
    LotRead,
    OpeningBatchCreate,
    RelocationCreate,
    ReorderRuleIn,
    ReorderRuleRead,
    TransferCreate,
    Versioned,
    WarehouseCreate,
    WarehouseRead,
)
from app.platform.authz.stepup import require_step_up
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)


def _business_date(uow: UnitOfWork):  # noqa: ANN202
    from app.core.clock import local_date
    from app.platform.org.models import Company

    zone = (
        uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
        or "Asia/Kolkata"
    )
    return local_date(uow.now(), zone)


def _number(uow: UnitOfWork, key: str, resource_id: uuid.UUID, branch_id: uuid.UUID | None) -> str:
    return uow.allocate_number(
        key,
        document_date=_business_date(uow),
        resource_type=key,
        resource_id=resource_id,
        branch_id=branch_id,
    )


def _product(uow: UnitOfWork, product_id: uuid.UUID, loc: list[str | int]) -> Product:
    p = uow.session.scalars(
        select(Product).where(Product.company_id == uow.actor.company_id, Product.id == product_id)
    ).first()
    if p is None or not p.is_stock_tracked or not p.stock_uom_code:
        raise ValidationFailed(
            "The product is not stock-tracked",
            errors=[
                {
                    "loc": ["body", *loc, "product_id"],
                    "msg": "not stock-tracked",
                    "code": "product_not_stock_tracked",
                }
            ],
        )
    return p


def _warehouse_location(
    uow: UnitOfWork,
    warehouse: Warehouse,
    location_id: uuid.UUID | None,
    loc: list[str | int],
    types: tuple[LocationType, ...] = (LocationType.INTERNAL,),
) -> Location:
    if location_id is None:
        return default_location(uow, warehouse.id)
    location = get_location(uow, location_id)
    if location.warehouse_id != warehouse.id or LocationType(location.location_type) not in types:
        raise ValidationFailed(
            "The location is not a stock location of this warehouse",
            errors=[
                {
                    "loc": ["body", *loc, "location_id"],
                    "msg": "wrong location",
                    "code": "location_not_in_warehouse",
                }
            ],
        )
    return location


# =====================================================================================================
# warehouses, bins, lots
# =====================================================================================================
def warehouse_read(uow: UnitOfWork, wh: Warehouse) -> WarehouseRead:
    locs = list(
        uow.session.scalars(
            select(Location)
            .where(Location.company_id == uow.actor.company_id, Location.warehouse_id == wh.id)
            .order_by(Location.code)
        )
    )
    manage = uow.actor.can("inventory.warehouse.manage")
    return WarehouseRead(
        id=wh.id,
        code=wh.code,
        name=wh.name,
        branch_id=wh.branch_id,
        address=wh.address,
        is_active=wh.is_active,
        market=wh.market,
        country_code=wh.country_code,
        locations=[location_ref(loc) for loc in locs],
        capabilities={
            "manage": Capability(allowed=manage, reason_code=None if manage else "permission_denied")
        },
    )


def create_warehouse(uow: UnitOfWork, data: WarehouseCreate, *, origin_ref: str | None = None) -> Warehouse:
    uow.actor.require("inventory.warehouse.manage")
    if uow.session.scalar(
        select(Warehouse.id).where(Warehouse.company_id == uow.actor.company_id, Warehouse.code == data.code)
    ):
        raise ValidationFailed(
            "A warehouse with this code exists",
            errors=[{"loc": ["body", "code"], "msg": "code already used", "code": "duplicate_code"}],
        )
    wh = create_warehouse_rows(
        uow,
        code=data.code,
        name=data.name,
        branch_id=data.branch_id,
        address=data.address,
        origin_ref=origin_ref,
        market=data.market,
        country_code=data.country_code,
    )
    uow.audit(
        "inventory.warehouse.create",
        resource_type="inventory.warehouse",
        resource_id=wh.id,
        resource_label=wh.code,
    )
    return wh


def create_bin(uow: UnitOfWork, warehouse_id: uuid.UUID, data: BinCreate) -> Location:
    wh = require_warehouse(uow, warehouse_id)
    uow.actor.require("inventory.warehouse.manage")
    return add_bin(uow, wh, code=data.code, name=data.name)


def lot_read(uow: UnitOfWork, lot: Lot) -> LotRead:
    from app.modules.inventory.models import StockBalance

    on_hand = (
        uow.session.scalar(
            select(func.coalesce(func.sum(StockBalance.quantity), 0))
            .join(Location, Location.id == StockBalance.location_id)
            .where(StockBalance.lot_id == lot.id, Location.is_stock_bearing.is_(True))
        )
        or ZERO
    )
    return LotRead(
        id=lot.id,
        lot_code=lot.lot_code,
        lot_kind=lot.lot_kind,
        product=product_refs(uow, [lot.product_id])[lot.product_id],  # type: ignore[arg-type]
        supplier_lot_ref=lot.supplier_lot_ref,
        length_mm=lot.length_mm,
        width_mm=lot.width_mm,
        thickness_mm=lot.thickness_mm,
        grain_axis=lot.grain_axis,
        verification_status=lot.verification_status,
        on_hand=Decimal(on_hand),
    )


def create_lot(uow: UnitOfWork, data: LotCreate) -> Lot:
    if not uow.actor.can("inventory.lot.manage"):
        raise Forbidden(code="permission_denied", permission="inventory.lot.manage")
    _product(uow, data.product_id, [])
    if uow.session.scalar(
        select(Lot.id).where(
            Lot.company_id == uow.actor.company_id,
            Lot.product_id == data.product_id,
            Lot.lot_code == data.lot_code,
        )
    ):
        raise ValidationFailed(
            "This lot code exists for the product",
            errors=[{"loc": ["body", "lot_code"], "msg": "lot code already used", "code": "duplicate_lot"}],
        )
    lot = Lot(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        product_id=data.product_id,
        lot_code=data.lot_code,
        lot_kind=data.lot_kind.value,
        supplier_lot_ref=data.supplier_lot_ref,
    )
    uow.add(lot)
    uow.flush()
    return lot


def ensure_lot(uow: UnitOfWork, product_id: uuid.UUID, lot_code: str) -> Lot:
    lot = uow.session.scalars(
        select(Lot).where(
            Lot.company_id == uow.actor.company_id, Lot.product_id == product_id, Lot.lot_code == lot_code
        )
    ).first()
    if lot is None:
        lot = Lot(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            product_id=product_id,
            lot_code=lot_code,
            lot_kind="standard",
        )
        uow.add(lot)
        uow.flush()
    return lot


def measure_lot(uow: UnitOfWork, lot_id: uuid.UUID, data: LotMeasure) -> Lot:
    if not uow.actor.can("inventory.lot.manage"):
        raise Forbidden(code="permission_denied", permission="inventory.lot.manage")
    lot = uow.session.scalars(
        select(Lot).where(Lot.company_id == uow.actor.company_id, Lot.id == lot_id).with_for_update()
    ).first()
    if lot is None:
        raise NotFound(code="not_found", resource_type="inventory.lot")
    lot.length_mm, lot.width_mm, lot.thickness_mm, lot.grain_axis = (
        data.length_mm,
        data.width_mm,
        data.thickness_mm,
        data.grain_axis,
    )
    lot.verification_status, lot.measured_by, lot.measured_at = "verified", uow.actor.user_id, uow.now()
    uow.flush()
    uow.emit(
        ev.LOT_MEASURED,
        aggregate_id=lot.id,
        aggregate_version=lot.version,
        payload={"lot_id": str(lot.id), "lot_kind": lot.lot_kind},
    )
    return lot


# =====================================================================================================
# reorder rules
# =====================================================================================================
def reorder_reads(uow: UnitOfWork, rules: list[ReorderRule]) -> list[ReorderRuleRead]:
    from app.modules.inventory.models import StockSummary

    products = product_refs(uow, [r.product_id for r in rules])
    whs = warehouse_refs(uow, [r.warehouse_id for r in rules])
    out = []
    for r in rules:
        s = uow.session.scalars(
            select(StockSummary).where(
                StockSummary.company_id == uow.actor.company_id,
                StockSummary.product_id == r.product_id,
                StockSummary.warehouse_id == r.warehouse_id,
            )
        ).first()
        available = (Decimal(s.available_on_hand) - Decimal(s.reserved)) if s else ZERO
        below = r.is_active and available < Decimal(r.min_qty)
        suggest = max(Decimal(r.reorder_qty), Decimal(r.max_qty) - available) if below else ZERO
        out.append(
            ReorderRuleRead(
                id=r.id,
                product=products[r.product_id],
                warehouse=whs[r.warehouse_id],
                min_quantity=Decimal(r.min_qty),
                max_quantity=Decimal(r.max_qty),
                reorder_quantity=Decimal(r.reorder_qty),
                is_active=r.is_active,
                available=available,
                below_min=below,
                suggested_quantity=suggest,
                version=r.version,
            )
        )
    return out


def upsert_reorder_rule(uow: UnitOfWork, data: ReorderRuleIn) -> ReorderRule:
    uow.actor.require("inventory.reorder_rule.manage")
    require_warehouse(uow, data.warehouse_id)
    _product(uow, data.product_id, [])
    if data.max_quantity < data.min_quantity:
        raise ValidationFailed(
            "The maximum must be at least the minimum",
            errors=[{"loc": ["body", "max_quantity"], "msg": "below the minimum", "code": "max_below_min"}],
        )
    rule = uow.session.scalars(
        select(ReorderRule)
        .where(
            ReorderRule.company_id == uow.actor.company_id,
            ReorderRule.product_id == data.product_id,
            ReorderRule.warehouse_id == data.warehouse_id,
        )
        .with_for_update()
    ).first()
    if rule is None:
        rule = ReorderRule(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            product_id=data.product_id,
            warehouse_id=data.warehouse_id,
            min_qty=data.min_quantity,
            max_qty=data.max_quantity,
            reorder_qty=data.reorder_quantity,
            is_active=data.is_active,
        )
        uow.add(rule)
    else:
        rule.min_qty, rule.max_qty, rule.reorder_qty, rule.is_active = (
            data.min_quantity,
            data.max_quantity,
            data.reorder_quantity,
            data.is_active,
        )
    uow.flush()
    return rule


# =====================================================================================================
# relocation and reversal
# =====================================================================================================
def relocate(uow: UnitOfWork, data: RelocationCreate) -> StockPosting:
    src, dst = get_location(uow, data.from_location_id), get_location(uow, data.to_location_id)
    for loc in (src, dst):
        if loc.warehouse_id is None or loc.location_type != LocationType.INTERNAL.value:
            raise ValidationFailed(
                "Relocation moves stock between bins of a warehouse",
                errors=[{"loc": ["body", "to_location_id"], "msg": "not a bin", "code": "not_a_bin"}],
            )
        require_warehouse(uow, loc.warehouse_id, "inventory.stock.post")
    source_id = (
        uuid.uuid5(uuid.NAMESPACE_URL, f"relocation:{uow.actor.idempotency_key}")
        if uow.actor.idempotency_key
        else uuid.uuid7()
    )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="relocation",
            source_id=source_id,
            purpose="relocate",
            source_label=f"{src.code} → {dst.code}",
            lines=(
                PostingLine(
                    product_id=data.product_id,
                    quantity=data.quantity,
                    uom_code=data.unit,
                    from_location_id=src.id,
                    to_location_id=dst.id,
                    lot_id=data.lot_id,
                ),
            ),
        ),
    )
    return receipt.posting


def reverse_posting_command(
    uow: UnitOfWork, posting_id: uuid.UUID, *, reason_code: str, reason: str | None
) -> StockPosting:
    """``inventory.posting.reverse`` (RA, sensitive) over every warehouse the posting touched; source documents with
    their own correction path (challans: cancel; counts and adjustments: a new document) are not reversed here."""
    posting = uow.session.scalars(
        select(StockPosting).where(
            StockPosting.company_id == uow.actor.company_id, StockPosting.id == posting_id
        )
    ).first()
    if posting is None:
        raise NotFound(code="not_found", resource_type="inventory.posting")
    whs = set(
        uow.session.scalars(
            select(StockMovement.from_warehouse_id).where(StockMovement.posting_id == posting.id)
        )
    ) | set(
        uow.session.scalars(
            select(StockMovement.to_warehouse_id).where(StockMovement.posting_id == posting.id)
        )
    )
    whs.discard(None)
    for w in sorted(whs, key=str):  # type: ignore[arg-type]
        require_warehouse(uow, w, "inventory.posting.reverse")  # type: ignore[arg-type]
    if posting.source_type == "challan":
        raise Conflict(
            "Challan postings are corrected by cancelling the challan", code="reverse_through_source_document"
        )
    require_step_up(uow, "inventory.posting.reverse")
    receipt = reverse_posting(uow, posting.id, reason_code=reason_code, reason=reason)
    uow.audit(
        "inventory.posting.reverse",
        resource_type="inventory.posting",
        resource_id=posting.id,
        resource_label=posting.source_label,
        reason=reason,
        details={"reason_code": reason_code, "reversal_posting_id": str(receipt.posting.id)},
    )
    return receipt.posting


# =====================================================================================================
# adjustments
# =====================================================================================================
def _doc_lines_read(uow: UnitOfWork, lines: list) -> list[DocLineRead]:
    products = product_refs(uow, [ln.product_id for ln in lines])
    locs = location_refs(uow, [getattr(ln, "location_id", None) for ln in lines])
    lots = lot_refs(uow, [ln.lot_id for ln in lines])
    return [
        DocLineRead(
            id=ln.id,
            line_no=ln.line_no,
            product=products[ln.product_id],
            location=locs.get(getattr(ln, "location_id", None)) if getattr(ln, "location_id", None) else None,
            lot=lots.get(ln.lot_id) if ln.lot_id else None,
            quantity=Decimal(ln.quantity),
            unit=ln.uom_code,
            direction=getattr(ln, "direction", None),
            lot_code=getattr(ln, "lot_code", None),
            late_opening=getattr(ln, "late_opening", None),
        )
        for ln in lines
    ]


def _cap(ok: bool, reason: str) -> Capability:
    return Capability(allowed=ok, reason_code=None if ok else reason)


def adjustment_read(uow: UnitOfWork, adj: Adjustment) -> DocumentRead:
    lines = list(
        uow.session.scalars(
            select(AdjustmentLine)
            .where(AdjustmentLine.adjustment_id == adj.id)
            .order_by(AdjustmentLine.line_no)
        )
    )
    users = user_refs(uow, [adj.created_by, adj.decided_by])
    approver = can_on_warehouse(uow, adj.warehouse_id, "inventory.adjustment.approve")
    creator = can_on_warehouse(uow, adj.warehouse_id, "inventory.adjustment.create")
    own = adj.created_by == uow.actor.user_id
    decide = approver and adj.status == AdjustmentStatus.SUBMITTED.value and not own
    return DocumentRead(
        id=adj.id,
        kind="adjustment",
        number=adj.number,
        status=adj.status,
        warehouse=warehouse_refs(uow, [adj.warehouse_id])[adj.warehouse_id],
        reason_code=adj.reason_code,
        reason=adj.reason,
        notes=adj.notes,
        created_by=users.get(adj.created_by) if adj.created_by else None,
        created_at=adj.created_at,
        decided_by=users.get(adj.decided_by) if adj.decided_by else None,
        decided_at=adj.decided_at,
        decision_note=adj.decision_note,
        posting_id=adj.posting_id,
        lines=_doc_lines_read(uow, lines),
        version=adj.version,
        capabilities={
            "submit": _cap(
                creator and adj.status == AdjustmentStatus.DRAFT.value,
                "invalid_status" if creator else "permission_denied",
            ),
            "approve": _cap(
                decide,
                "approver_is_creator"
                if approver and own
                else "invalid_status"
                if approver
                else "permission_denied",
            ),
            "reject": _cap(
                decide,
                "approver_is_creator"
                if approver and own
                else "invalid_status"
                if approver
                else "permission_denied",
            ),
        },
    )


def create_adjustment(uow: UnitOfWork, data: AdjustmentCreate) -> Adjustment:
    wh = require_warehouse(uow, data.warehouse_id, "inventory.adjustment.create")
    adj = Adjustment(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        number="ADJ",
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        status=AdjustmentStatus.DRAFT.value,
        reason_code=data.reason_code.value,
        reason=data.reason,
        notes=data.notes,
    )
    adj.number = _number(uow, "inventory.adjustment", adj.id, wh.branch_id)
    uow.add(adj)
    uow.flush()
    for i, ln in enumerate(data.lines, start=1):
        p = _product(uow, ln.product_id, ["lines", i - 1])
        loc = _warehouse_location(
            uow,
            wh,
            ln.location_id,
            ["lines", i - 1],
            (LocationType.INTERNAL, LocationType.QC_HOLD, LocationType.REJECTED),
        )
        uow.add(
            AdjustmentLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                adjustment_id=adj.id,
                line_no=i,
                product_id=p.id,
                location_id=loc.id,
                lot_id=ln.lot_id,
                direction=ln.direction.value,
                quantity=ln.quantity,
                uom_code=ln.unit or p.stock_uom_code,
            )
        )
    uow.flush()
    return adj


def _locked_doc(uow: UnitOfWork, model: type, doc_id: uuid.UUID, resource: str):  # noqa: ANN202
    doc = uow.session.scalars(
        select(model).where(model.company_id == uow.actor.company_id, model.id == doc_id).with_for_update()
    ).first()
    if doc is None:
        raise NotFound(code="not_found", resource_type=resource)
    require_warehouse(uow, doc.warehouse_id if hasattr(doc, "warehouse_id") else doc.from_warehouse_id)
    return doc


def submit_adjustment(uow: UnitOfWork, adjustment_id: uuid.UUID, data: Versioned) -> Adjustment:
    adj = _locked_doc(uow, Adjustment, adjustment_id, "inventory.adjustment")
    require_warehouse(uow, adj.warehouse_id, "inventory.adjustment.create")
    uow.expect_version(adj, data.expected_version)
    if adj.status != AdjustmentStatus.DRAFT.value:
        raise Conflict("Only a draft is submitted", code="invalid_status", current_status=adj.status)
    adj.status, adj.submitted_at = AdjustmentStatus.SUBMITTED.value, uow.now()
    uow.flush()
    return adj


def decide_adjustment(
    uow: UnitOfWork, adjustment_id: uuid.UUID, data: Decision, *, approve: bool
) -> Adjustment:
    adj = _locked_doc(uow, Adjustment, adjustment_id, "inventory.adjustment")
    require_warehouse(uow, adj.warehouse_id, "inventory.adjustment.approve")
    uow.expect_version(adj, data.expected_version)
    if adj.status != AdjustmentStatus.SUBMITTED.value:
        raise Conflict(
            "Only a submitted adjustment is decided", code="invalid_status", current_status=adj.status
        )
    if adj.created_by == uow.actor.user_id:
        raise Forbidden("The person who created an adjustment cannot approve it", code="approver_is_creator")
    adj.decided_by, adj.decided_at, adj.decision_note = uow.actor.user_id, uow.now(), data.note
    if not approve:
        adj.status = AdjustmentStatus.REJECTED.value
        uow.flush()
        return adj
    adjust_loc = company_location(uow, LocationType.ADJUSTMENT).id
    lines = list(
        uow.session.scalars(
            select(AdjustmentLine)
            .where(AdjustmentLine.adjustment_id == adj.id)
            .order_by(AdjustmentLine.line_no)
        )
    )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="adjustment",
            source_id=adj.id,
            purpose="adjust",
            source_label=adj.number,
            reason_code=adj.reason_code,
            reason=adj.reason,
            allow_reserved_shortfall=True,  # an approved loss may eat into reservations; the shortfall is emitted, never silent
            lines=tuple(
                PostingLine(
                    product_id=ln.product_id,
                    quantity=Decimal(ln.quantity),
                    uom_code=ln.uom_code,
                    lot_id=ln.lot_id,
                    from_location_id=adjust_loc
                    if ln.direction == AdjustmentDirection.IN.value
                    else ln.location_id,
                    to_location_id=ln.location_id
                    if ln.direction == AdjustmentDirection.IN.value
                    else adjust_loc,
                    source_line_type="inventory.adjustment_line",
                    source_line_id=ln.id,
                )
                for ln in lines
            ),
        ),
    )
    adj.status, adj.posting_id = AdjustmentStatus.POSTED.value, receipt.posting.id
    uow.flush()
    uow.emit(
        ev.ADJUSTMENT_POSTED,
        aggregate_id=adj.id,
        aggregate_version=adj.version,
        payload={"adjustment_id": str(adj.id), "posting_id": str(receipt.posting.id)},
    )
    uow.audit(
        "inventory.adjustment.approve",
        resource_type="inventory.adjustment",
        resource_id=adj.id,
        resource_label=adj.number,
        details={"posting_id": str(receipt.posting.id)},
    )
    return adj


# =====================================================================================================
# opening stock batches (one creator, a different approver with MFA; never derived from challans)
# =====================================================================================================
def opening_read(uow: UnitOfWork, batch: OpeningBatch) -> DocumentRead:
    lines = list(
        uow.session.scalars(
            select(OpeningBatchLine)
            .where(OpeningBatchLine.opening_batch_id == batch.id)
            .order_by(OpeningBatchLine.line_no)
        )
    )
    users = user_refs(uow, [batch.created_by, batch.decided_by])
    approver = uow.actor.can("inventory.opening_batch.approve")
    own = batch.created_by == uow.actor.user_id
    decide = approver and batch.status == OpeningStatus.SUBMITTED.value and not own
    creator = uow.actor.can("inventory.opening_batch.create")
    return DocumentRead(
        id=batch.id,
        kind="opening_batch",
        number=batch.number,
        status=batch.status,
        warehouse=warehouse_refs(uow, [batch.warehouse_id])[batch.warehouse_id],
        notes=batch.notes,
        created_by=users.get(batch.created_by) if batch.created_by else None,
        created_at=batch.created_at,
        decided_by=users.get(batch.decided_by) if batch.decided_by else None,
        decided_at=batch.decided_at,
        decision_note=batch.decision_note,
        posting_id=batch.posting_id,
        lines=_doc_lines_read(uow, lines),
        version=batch.version,
        capabilities={
            "submit": _cap(
                creator and batch.status == OpeningStatus.DRAFT.value,
                "invalid_status" if creator else "permission_denied",
            ),
            "approve": _cap(
                decide,
                "approver_is_creator"
                if approver and own
                else "invalid_status"
                if approver
                else "permission_denied",
            ),
            "reject": _cap(
                decide,
                "approver_is_creator"
                if approver and own
                else "invalid_status"
                if approver
                else "permission_denied",
            ),
        },
    )


def _has_non_opening_movements(uow: UnitOfWork, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> bool:
    return bool(
        uow.session.scalar(
            select(func.count())
            .select_from(StockMovement)
            .join(StockPosting, StockPosting.id == StockMovement.posting_id)
            .where(
                StockMovement.company_id == uow.actor.company_id,
                StockMovement.product_id == product_id,
                (StockMovement.from_warehouse_id == warehouse_id)
                | (StockMovement.to_warehouse_id == warehouse_id),
                StockPosting.source_type != "opening_batch",
            )
        )
    )


def create_opening_batch(
    uow: UnitOfWork, data: OpeningBatchCreate, *, origin_ref: str | None = None
) -> OpeningBatch:
    uow.actor.require("inventory.opening_batch.create")
    require_step_up(uow, "inventory.opening_batch.create")
    wh = require_warehouse(uow, data.warehouse_id)
    batch = OpeningBatch(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        number="OB",
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        status=OpeningStatus.DRAFT.value,
        notes=data.notes,
        source_file_sha256=data.source_file_sha256,
        origin_ref=origin_ref,
    )
    batch.number = _number(uow, "inventory.opening_batch", batch.id, wh.branch_id)
    uow.add(batch)
    uow.flush()
    errors = []
    for i, ln in enumerate(data.lines, start=1):
        p = _product(uow, ln.product_id, ["lines", i - 1])
        loc = _warehouse_location(uow, wh, ln.location_id, ["lines", i - 1])
        if p.track_lots and not ln.lot_code:
            errors.append(
                {
                    "loc": ["body", "lines", i - 1, "lot_code"],
                    "msg": f"{p.product_key} is lot-tracked",
                    "code": "lot_required",
                }
            )
        if not ln.late_opening and _has_non_opening_movements(uow, p.id, wh.id):
            errors.append(
                {
                    "loc": ["body", "lines", i - 1, "product_id"],
                    "msg": f"{p.product_key} already has movements at {wh.code}; mark the line as a late opening to post it",
                    "code": "movements_exist",
                }
            )
        uow.add(
            OpeningBatchLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                opening_batch_id=batch.id,
                line_no=i,
                product_id=p.id,
                location_id=loc.id,
                lot_code=ln.lot_code,
                quantity=ln.quantity,
                uom_code=ln.unit or p.stock_uom_code,
                source_row_ref=ln.source_row_ref,
                late_opening=ln.late_opening,
            )
        )
    if errors:
        raise ValidationFailed("Some opening lines are not valid", errors=errors)
    uow.flush()
    uow.audit(
        "inventory.opening_batch.create",
        resource_type="inventory.opening_batch",
        resource_id=batch.id,
        resource_label=batch.number,
    )
    return batch


def submit_opening_batch(uow: UnitOfWork, batch_id: uuid.UUID, data: Versioned) -> OpeningBatch:
    uow.actor.require("inventory.opening_batch.create")
    batch = _locked_doc(uow, OpeningBatch, batch_id, "inventory.opening_batch")
    uow.expect_version(batch, data.expected_version)
    if batch.status != OpeningStatus.DRAFT.value:
        raise Conflict("Only a draft is submitted", code="invalid_status", current_status=batch.status)
    batch.status, batch.submitted_at = OpeningStatus.SUBMITTED.value, uow.now()
    uow.flush()
    return batch


def decide_opening_batch(
    uow: UnitOfWork, batch_id: uuid.UUID, data: Decision, *, approve: bool
) -> OpeningBatch:
    uow.actor.require("inventory.opening_batch.approve")
    batch = _locked_doc(uow, OpeningBatch, batch_id, "inventory.opening_batch")
    uow.expect_version(batch, data.expected_version)
    if batch.status != OpeningStatus.SUBMITTED.value:
        raise Conflict(
            "Only a submitted batch is decided", code="invalid_status", current_status=batch.status
        )
    if batch.created_by == uow.actor.user_id:
        raise Forbidden(
            "Opening stock is approved by a second person, never its creator", code="approver_is_creator"
        )
    require_step_up(uow, "inventory.opening_batch.approve")
    batch.decided_by, batch.decided_at, batch.decision_note = uow.actor.user_id, uow.now(), data.note
    if not approve:
        batch.status = OpeningStatus.REJECTED.value
        uow.flush()
        return batch
    lines = list(
        uow.session.scalars(
            select(OpeningBatchLine)
            .where(OpeningBatchLine.opening_batch_id == batch.id)
            .order_by(OpeningBatchLine.line_no)
        )
    )
    for ln in lines:
        if not ln.late_opening and _has_non_opening_movements(uow, ln.product_id, batch.warehouse_id):
            raise Conflict(
                "Stock has moved since the batch was prepared; re-check the opening lines",
                code="movements_exist",
                line_id=str(ln.id),
            )
        if ln.lot_code and ln.lot_id is None:
            ln.lot_id = ensure_lot(uow, ln.product_id, ln.lot_code).id
    uow.flush()
    opening = company_location(uow, LocationType.OPENING).id
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="opening_batch",
            source_id=batch.id,
            purpose="opening",
            source_label=batch.number,
            lines=tuple(
                PostingLine(
                    product_id=ln.product_id,
                    quantity=Decimal(ln.quantity),
                    uom_code=ln.uom_code,
                    from_location_id=opening,
                    to_location_id=ln.location_id,
                    lot_id=ln.lot_id,
                    source_line_type="inventory.opening_batch_line",
                    source_line_id=ln.id,
                )
                for ln in lines
            ),
        ),
    )
    batch.status, batch.posting_id = OpeningStatus.POSTED.value, receipt.posting.id
    uow.flush()
    uow.emit(
        ev.OPENING_POSTED,
        aggregate_id=batch.id,
        aggregate_version=batch.version,
        payload={"opening_batch_id": str(batch.id), "posting_id": str(receipt.posting.id)},
    )
    uow.audit(
        "inventory.opening_batch.approve",
        resource_type="inventory.opening_batch",
        resource_id=batch.id,
        resource_label=batch.number,
        details={"posting_id": str(receipt.posting.id), "lines": len(lines)},
    )
    return batch


# =====================================================================================================
# transfers (two postings through the in-transit holding)
# =====================================================================================================
def transfer_read(uow: UnitOfWork, tr: Transfer) -> DocumentRead:
    lines = list(
        uow.session.scalars(
            select(TransferLine).where(TransferLine.transfer_id == tr.id).order_by(TransferLine.line_no)
        )
    )
    whs = warehouse_refs(uow, [tr.from_warehouse_id, tr.to_warehouse_id])
    users = user_refs(uow, [tr.created_by])
    send = can_on_warehouse(uow, tr.from_warehouse_id, "inventory.stock.post")
    recv = can_on_warehouse(uow, tr.to_warehouse_id, "inventory.stock.post")
    return DocumentRead(
        id=tr.id,
        kind="transfer",
        number=tr.number,
        status=tr.status,
        warehouse=whs[tr.from_warehouse_id],
        to_warehouse=whs[tr.to_warehouse_id],
        notes=tr.notes,
        created_by=users.get(tr.created_by) if tr.created_by else None,
        created_at=tr.created_at,
        posting_id=tr.dispatch_posting_id,
        second_posting_id=tr.receive_posting_id,
        lines=_doc_lines_read(uow, lines),
        version=tr.version,
        capabilities={
            "dispatch": _cap(
                send and tr.status == TransferStatus.DRAFT.value,
                "invalid_status" if send else "permission_denied",
            ),
            "receive": _cap(
                recv and tr.status == TransferStatus.DISPATCHED.value,
                "invalid_status" if recv else "permission_denied",
            ),
            "cancel": _cap(
                send and tr.status == TransferStatus.DRAFT.value,
                "invalid_status" if send else "permission_denied",
            ),
        },
    )


def create_transfer(uow: UnitOfWork, data: TransferCreate) -> Transfer:
    src = require_warehouse(uow, data.from_warehouse_id, "inventory.stock.post")
    dst = require_warehouse(uow, data.to_warehouse_id)
    if src.id == dst.id:
        raise ValidationFailed(
            "Choose two different warehouses",
            errors=[{"loc": ["body", "to_warehouse_id"], "msg": "same warehouse", "code": "same_warehouse"}],
        )
    tr = Transfer(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        number="TR",
        from_warehouse_id=src.id,
        to_warehouse_id=dst.id,
        branch_id=src.branch_id,
        status=TransferStatus.DRAFT.value,
        notes=data.notes,
    )
    tr.number = _number(uow, "inventory.transfer", tr.id, src.branch_id)
    uow.add(tr)
    uow.flush()
    for i, ln in enumerate(data.lines, start=1):
        p = _product(uow, ln.product_id, ["lines", i - 1])
        uow.add(
            TransferLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                transfer_id=tr.id,
                line_no=i,
                product_id=p.id,
                lot_id=ln.lot_id,
                quantity=ln.quantity,
                uom_code=ln.unit or p.stock_uom_code,
            )
        )
    uow.flush()
    return tr


def _transfer_locked(uow: UnitOfWork, transfer_id: uuid.UUID) -> Transfer:
    tr = uow.session.scalars(
        select(Transfer)
        .where(Transfer.company_id == uow.actor.company_id, Transfer.id == transfer_id)
        .with_for_update()
    ).first()
    if tr is None:
        raise NotFound(code="not_found", resource_type="inventory.transfer")
    require_warehouse(uow, tr.from_warehouse_id)
    return tr


def dispatch_transfer(uow: UnitOfWork, transfer_id: uuid.UUID, data: Versioned) -> Transfer:
    tr = _transfer_locked(uow, transfer_id)
    require_warehouse(uow, tr.from_warehouse_id, "inventory.stock.post")
    uow.expect_version(tr, data.expected_version)
    if tr.status != TransferStatus.DRAFT.value:
        raise Conflict("Only a draft transfer is dispatched", code="invalid_status", current_status=tr.status)
    lines = list(
        uow.session.scalars(
            select(TransferLine).where(TransferLine.transfer_id == tr.id).order_by(TransferLine.line_no)
        )
    )
    src, transit = (
        default_location(uow, tr.from_warehouse_id).id,
        company_location(uow, LocationType.IN_TRANSIT).id,
    )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="transfer",
            source_id=tr.id,
            purpose="dispatch",
            source_label=tr.number,
            lines=tuple(
                PostingLine(
                    product_id=ln.product_id,
                    quantity=Decimal(ln.quantity),
                    uom_code=ln.uom_code,
                    from_location_id=src,
                    to_location_id=transit,
                    lot_id=ln.lot_id,
                    source_line_type="inventory.transfer_line",
                    source_line_id=ln.id,
                )
                for ln in lines
            ),
        ),
    )
    tr.status, tr.dispatch_posting_id, tr.dispatched_at = (
        TransferStatus.DISPATCHED.value,
        receipt.posting.id,
        uow.now(),
    )
    uow.flush()
    return tr


def receive_transfer(uow: UnitOfWork, transfer_id: uuid.UUID, data: Versioned) -> Transfer:
    tr = _transfer_locked(uow, transfer_id)
    require_warehouse(uow, tr.to_warehouse_id, "inventory.stock.post")
    uow.expect_version(tr, data.expected_version)
    if tr.status != TransferStatus.DISPATCHED.value:
        raise Conflict(
            "Only a dispatched transfer is received", code="invalid_status", current_status=tr.status
        )
    lines = list(
        uow.session.scalars(
            select(TransferLine).where(TransferLine.transfer_id == tr.id).order_by(TransferLine.line_no)
        )
    )
    transit, dst = (
        company_location(uow, LocationType.IN_TRANSIT).id,
        default_location(uow, tr.to_warehouse_id).id,
    )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="transfer",
            source_id=tr.id,
            purpose="receive",
            source_label=tr.number,
            lines=tuple(
                PostingLine(
                    product_id=ln.product_id,
                    quantity=Decimal(ln.quantity),
                    uom_code=ln.uom_code,
                    from_location_id=transit,
                    to_location_id=dst,
                    lot_id=ln.lot_id,
                    source_line_type="inventory.transfer_line",
                    source_line_id=ln.id,
                )
                for ln in lines
            ),
        ),
    )
    tr.status, tr.receive_posting_id, tr.received_at = (
        TransferStatus.RECEIVED.value,
        receipt.posting.id,
        uow.now(),
    )
    uow.flush()
    return tr


def cancel_transfer(uow: UnitOfWork, transfer_id: uuid.UUID, data: Versioned) -> Transfer:
    tr = _transfer_locked(uow, transfer_id)
    require_warehouse(uow, tr.from_warehouse_id, "inventory.stock.post")
    uow.expect_version(tr, data.expected_version)
    if tr.status != TransferStatus.DRAFT.value:
        raise Conflict(
            "A dispatched transfer is received, not cancelled",
            code="invalid_status",
            current_status=tr.status,
        )
    tr.status = TransferStatus.CANCELLED.value
    uow.flush()
    return tr


# ---- document lists -------------------------------------------------------------------------------------------
def document_summaries(
    uow: UnitOfWork, kind: str, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[DocumentSummary], int]:
    from app.modules.inventory.models import PickList, PickListLine, StockCount, StockCountLine
    from app.modules.inventory.policies import visible_warehouse_ids

    model, line_model, fk, path = {
        "adjustment": (Adjustment, AdjustmentLine, "adjustment_id", "/operations/inventory/adjustments/{id}"),
        "opening_batch": (
            OpeningBatch,
            OpeningBatchLine,
            "opening_batch_id",
            "/operations/inventory/opening/{id}",
        ),
        "transfer": (Transfer, TransferLine, "transfer_id", "/operations/inventory/transfers/{id}"),
        "stock_count": (
            StockCount,
            StockCountLine,
            "stock_count_id",
            "/operations/inventory/stock-takes/{id}",
        ),
        "pick_list": (PickList, PickListLine, "pick_list_id", "/operations/inventory/pick-lists/{id}"),
    }[kind]
    wh_col = model.from_warehouse_id if model is Transfer else model.warehouse_id
    stmt = select(model).where(
        model.company_id == uow.actor.company_id, wh_col.in_(visible_warehouse_ids(uow))
    )
    if status:
        stmt = stmt.where(model.status == status)
    total = uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(
        uow.session.scalars(
            stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit).offset(offset)
        )
    )
    counts = (
        dict(
            uow.session.execute(
                select(getattr(line_model, fk), func.count())
                .where(getattr(line_model, fk).in_([r.id for r in rows]))
                .group_by(getattr(line_model, fk))
            ).all()
        )
        if rows
        else {}
    )
    whs = warehouse_refs(uow, [r.from_warehouse_id if model is Transfer else r.warehouse_id for r in rows])
    users = user_refs(uow, [r.created_by for r in rows])
    return [
        DocumentSummary(
            id=r.id,
            kind=kind,
            number=r.number,
            status=r.status,  # type: ignore[arg-type]
            warehouse=whs[r.from_warehouse_id if model is Transfer else r.warehouse_id],
            line_count=int(counts.get(r.id, 0)),
            created_by=users.get(r.created_by) if r.created_by else None,
            created_at=r.created_at,
            path=path.format(id=r.id),
        )
        for r in rows
    ], int(total)
