"""Quality public service: inspections of stock held in a warehouse's QC hold.

- ``request_inspection(uow, ...)``: called by procurement (goods receipts of QC-required products), the production lane
  (outputs; through the integrator) and returns. One live inspection per subject: a repeat returns the existing one.
  Emits ``quality.inspection.requested``.
- ``decide_inspection``: records the checklist and the accepted / rejected split (must add up to the inspected
  quantity), then posts **one** movement through the inventory posting service: accepted QC hold -> stock (released),
  rejected QC hold -> rejected (held for return or scrap). Emits ``.passed`` (nothing rejected) or ``.failed``.
- ``register_subject_handler(subject_type, fn)``: the requesting module's callback after a decision (procurement
  updates the PO line's accepted / rejected figures), so this module never imports its requesters.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.core.http.capabilities import Capability
from app.core.http.pagination import Page
from app.modules.inventory.enums import LocationType
from app.modules.inventory.policies import can_on_warehouse, require_warehouse
from app.modules.inventory.service import (
    PostingLine,
    PostingRequest,
    default_location,
    get_location,
    post_movement,
    warehouse_location,
)
from app.modules.quality import events as ev
from app.modules.quality.enums import CheckResult, InspectionStatus, SubjectType
from app.modules.quality.models import Inspection
from app.modules.quality.policies import CREATE, READ
from app.modules.quality.schemas import (
    ChecklistItem,
    InspectionCreate,
    InspectionDecision,
    InspectionDetail,
    InspectionProduct,
    InspectionSummary,
    InspectionWarehouse,
)
from app.platform.uow import UnitOfWork

S = InspectionStatus
SubjectHandler = Callable[[UnitOfWork, Inspection], None]
_HANDLERS: dict[str, SubjectHandler] = {}

DEFAULT_CHECKLIST = (
    ("quantity_matches", "Quantity matches the documents"),
    ("visual_ok", "Surface and finish free of defects"),
    ("dimensions_ok", "Dimensions within tolerance"),
    ("packaging_ok", "Packaging intact and labelled"),
)

__all__ = [
    "READ",
    "decide_inspection",
    "get_inspection",
    "list_inspections",
    "register_subject_handler",
    "request_inspection",
]


def register_subject_handler(subject_type: str, handler: SubjectHandler) -> None:
    _HANDLERS[subject_type] = handler


def path(inspection_id: uuid.UUID) -> str:
    return f"/operations/quality/{inspection_id}"


def _business_date(uow: UnitOfWork):  # noqa: ANN202
    from app.modules.procurement.common import business_date

    return business_date(uow)


def live_for_subject(uow: UnitOfWork, subject_type: str, subject_id: uuid.UUID) -> Inspection | None:
    return uow.session.scalars(
        select(Inspection).where(
            Inspection.company_id == uow.actor.company_id,
            Inspection.subject_type == subject_type,
            Inspection.subject_id == subject_id,
            Inspection.status != S.CANCELLED.value,
        )
    ).first()


def request_inspection(
    uow: UnitOfWork,
    *,
    subject_type: str,
    subject_id: uuid.UUID,
    subject_label: str,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    quantity: Decimal,
    uom_code: str,
    lot_id: uuid.UUID | None = None,
    owner_party_id: uuid.UUID | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    work_order_id: uuid.UUID | None = None,
) -> Inspection:
    """Create (or return the live) inspection for a subject whose quantity is already in the warehouse's QC hold."""
    SubjectType(subject_type)
    existing = live_for_subject(uow, subject_type, subject_id)
    if existing is not None:
        return existing
    from app.modules.inventory.models import Warehouse

    wh = uow.session.get(Warehouse, warehouse_id)
    assert wh is not None and wh.company_id == uow.actor.company_id
    insp = Inspection(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        inspection_number="QC",
        status=S.PENDING.value,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_label=subject_label[:120],
        source_type=source_type,
        source_id=source_id,
        work_order_id=work_order_id
        if work_order_id is not None
        else (subject_id if subject_type == SubjectType.WORK_ORDER.value else None),
        product_id=product_id,
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        lot_id=lot_id,
        owner_party_id=owner_party_id,
        quantity=quantity,
        uom_code=uom_code,
        requested_at=uow.now(),
    )
    insp.inspection_number = uow.allocate_number(
        "quality.inspection",
        document_date=_business_date(uow),
        resource_type="quality.inspection",
        resource_id=insp.id,
        branch_id=wh.branch_id,
    )
    uow.add(insp)
    uow.flush()
    uow.emit(
        ev.INSPECTION_REQUESTED,
        aggregate_id=insp.id,
        aggregate_version=insp.version,
        payload={"inspection_id": str(insp.id), "subject_type": subject_type, "subject_id": str(subject_id)},
    )
    return insp


def create_inspection(uow: UnitOfWork, data: InspectionCreate) -> Inspection:
    """An inspection of stock already held in QC (e.g. a customer return); the warehouse must be in scope."""
    wh = require_warehouse(uow, data.warehouse_id, CREATE)
    from app.modules.procurement.common import stock_product

    p = stock_product(uow, data.product_id, [])
    insp_id = uuid.uuid7()
    return request_inspection(
        uow,
        subject_type=SubjectType.STOCK.value,
        subject_id=insp_id,
        subject_label=f"QC hold at {wh.code}"[:120],
        product_id=p.id,
        warehouse_id=wh.id,
        quantity=Decimal(data.quantity),
        uom_code=data.unit or p.stock_uom_code or "pcs",
        lot_id=data.lot_id,
    )


def _invalid(msg: str, loc: str, code: str) -> ValidationFailed:
    return ValidationFailed(msg, errors=[{"loc": ["body", loc], "msg": msg, "code": code}])


def decide_inspection(uow: UnitOfWork, inspection_id: uuid.UUID, data: InspectionDecision) -> Inspection:
    repo = uow.repo(Inspection)
    insp = repo.get(inspection_id, for_update=True)
    require_warehouse(uow, insp.warehouse_id, CREATE)
    repo.require_action(insp, "create")
    uow.expect_version(insp, data.expected_version)
    if insp.status != S.PENDING.value:
        raise Conflict(
            "This inspection was already decided", code="invalid_status", current_status=insp.status
        )
    accepted, rejected = Decimal(data.qty_accepted), Decimal(data.qty_rejected)
    if accepted + rejected != Decimal(insp.quantity):
        raise _invalid(
            "Accepted and rejected must add up to the inspected quantity",
            "qty_accepted",
            "results_do_not_add_up",
        )
    if rejected > 0 and not data.reject_reason_code:
        raise _invalid("Say why goods are rejected", "reject_reason_code", "reason_required")
    if rejected > 0 and not any(c.result is CheckResult.FAIL for c in data.checklist) and not data.findings:
        raise _invalid("Record the failed check or the findings", "findings", "findings_required")
    qc = warehouse_location(uow, insp.warehouse_id, LocationType.QC_HOLD)
    if data.release_location_id is not None:
        release = get_location(uow, data.release_location_id)
        if release.warehouse_id != insp.warehouse_id or release.location_type != LocationType.INTERNAL.value:
            raise _invalid(
                "Choose a stock location of this warehouse",
                "release_location_id",
                "location_not_in_warehouse",
            )
    else:
        release = default_location(uow, insp.warehouse_id)
    lines: list[PostingLine] = []
    if accepted > 0:
        lines.append(
            PostingLine(
                product_id=insp.product_id,
                quantity=accepted,
                uom_code=insp.uom_code,
                from_location_id=qc.id,
                to_location_id=release.id,
                lot_id=insp.lot_id,
                owner_party_id=insp.owner_party_id,
                source_line_type="quality.inspection",
                source_line_id=insp.id,
            )
        )
    if rejected > 0:
        rej = warehouse_location(uow, insp.warehouse_id, LocationType.REJECTED)
        lines.append(
            PostingLine(
                product_id=insp.product_id,
                quantity=rejected,
                uom_code=insp.uom_code,
                from_location_id=qc.id,
                to_location_id=rej.id,
                lot_id=insp.lot_id,
                owner_party_id=insp.owner_party_id,
                source_line_type="quality.inspection",
                source_line_id=insp.id,
            )
        )
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="qc_inspection",
            source_id=insp.id,
            purpose="qc",
            source_label=insp.inspection_number,
            reason_code=data.reject_reason_code,
            lines=tuple(lines),
        ),
    )
    insp.qty_accepted, insp.qty_rejected = accepted, rejected
    insp.checklist = [c.model_dump(mode="json") for c in data.checklist]
    insp.findings, insp.reject_reason_code = data.findings, data.reject_reason_code
    insp.release_location_id = release.id
    insp.decided_at, insp.decided_by, insp.posting_id = uow.now(), uow.actor.user_id, receipt.posting.id
    insp.status = S.FAILED.value if rejected > 0 else S.PASSED.value
    uow.flush()
    handler = _HANDLERS.get(insp.subject_type)
    if handler is not None:
        handler(uow, insp)
    uow.emit(
        ev.INSPECTION_FAILED if rejected > 0 else ev.INSPECTION_PASSED,
        aggregate_id=insp.id,
        aggregate_version=insp.version,
        payload={
            "inspection_id": str(insp.id),
            "subject_type": insp.subject_type,
            "subject_id": str(insp.subject_id),
        },
    )
    uow.audit(
        "quality.inspection.decide",
        resource_type="quality.inspection",
        resource_id=insp.id,
        resource_label=insp.inspection_number,
        details={"status": insp.status, "posting_id": str(receipt.posting.id)},
    )
    return insp


# ---- reads -----------------------------------------------------------------------------------------------------------
_SOURCE_PATHS = {
    "procurement.goods_receipt": "/operations/purchasing/receipts/{id}",
    "challans.challan": "/operations/challans/{id}",
    "production.work_order": "/operations/production/work-orders/{id}",
}


def _summaries(uow: UnitOfWork, rows: list[Inspection]) -> list[dict]:  # type: ignore[type-arg]
    from app.modules.inventory.reads import lot_refs, product_refs, warehouse_refs

    products = product_refs(uow, [r.product_id for r in rows])
    whs = warehouse_refs(uow, [r.warehouse_id for r in rows])
    lots = lot_refs(uow, [r.lot_id for r in rows])
    from app.modules.procurement.common import plain

    out = []
    for r in rows:
        p, w = products[r.product_id], whs[r.warehouse_id]
        template = _SOURCE_PATHS.get(r.source_type or "")
        out.append(
            {
                "id": r.id,
                "inspection_number": r.inspection_number,
                "status": r.status,
                "subject_type": r.subject_type,
                "subject_id": r.subject_id,
                "subject_label": r.subject_label,
                "source_path": template.format(id=r.source_id) if template and r.source_id else None,
                "product": InspectionProduct(id=p.id, product_key=p.product_key, name=p.name),
                "warehouse": InspectionWarehouse(id=w.id, code=w.code, name=w.name),
                "lot_code": lots[r.lot_id].lot_code if r.lot_id and r.lot_id in lots else None,
                "quantity": plain(r.quantity),
                "unit": r.uom_code,
                "qty_accepted": plain(r.qty_accepted),
                "qty_rejected": plain(r.qty_rejected),
                "requested_at": r.requested_at,
                "decided_at": r.decided_at,
                "path": path(r.id),
                "version": r.version,
            }
        )
    return out


def list_inspections(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    warehouse_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[InspectionSummary]:
    repo = uow.repo(Inspection)
    filters = []
    if status:
        filters.append(Inspection.status.in_(status))
    if warehouse_id is not None:
        require_warehouse(uow, warehouse_id)
        filters.append(Inspection.warehouse_id == warehouse_id)
    if source_id is not None:
        filters.append(Inspection.source_id == source_id)
    page = repo.list(
        *filters, order_by=[Inspection.requested_at.desc(), Inspection.id.desc()], limit=limit, offset=offset
    )
    items = [InspectionSummary(**d) for d in _summaries(uow, list(page.items))]
    return Page[InspectionSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def detail(uow: UnitOfWork, insp: Inspection) -> InspectionDetail:
    from app.modules.procurement.common import user_briefs

    users = user_briefs(uow, [insp.decided_by])
    can = can_on_warehouse(uow, insp.warehouse_id, CREATE) and uow.repo(Inspection).can(insp, "create")
    pending = insp.status == S.PENDING.value
    return InspectionDetail(
        **_summaries(uow, [insp])[0],
        checklist=[ChecklistItem.model_validate(c) for c in insp.checklist or []],
        findings=insp.findings,
        reject_reason_code=insp.reject_reason_code,
        decided_by_name=users[insp.decided_by].display_name if insp.decided_by in users else None,
        posting_id=insp.posting_id,
        work_order_id=insp.work_order_id,
        suggested_checklist=[
            ChecklistItem(code=c, label=label, result=CheckResult.PASS) for c, label in DEFAULT_CHECKLIST
        ],
        capabilities={
            "decide": Capability(
                allowed=can and pending,
                reason_code=None if can and pending else "invalid_status" if can else "permission_denied",
            ),
        },
    )


def get_inspection(uow: UnitOfWork, inspection_id: uuid.UUID) -> InspectionDetail:
    insp = uow.repo(Inspection).get(inspection_id)
    require_warehouse(uow, insp.warehouse_id)
    return detail(uow, insp)


def pending_count(uow: UnitOfWork, source_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return int(
        uow.session.scalar(
            select(func.count())
            .select_from(Inspection)
            .where(
                Inspection.company_id == uow.actor.company_id,
                Inspection.source_id == source_id,
                Inspection.status == S.PENDING.value,
            )
        )
        or 0
    )
