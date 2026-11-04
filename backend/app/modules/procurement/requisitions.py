"""Purchase requisitions (``PR-YYYY-NNNN``): draft -> submitted -> approved | rejected -> closed; cancelled.

Separation of duties: the person who requested or submitted a requisition never decides it (403
``approver_is_requester``, backed by a CHECK). An approved requisition converts into a draft purchase order for one
vendor; each line's ``qty_ordered`` grows with the PO lines made from it and the requisition closes when every line is
fully ordered. The destination warehouse is checked against the actor's warehouse scope on every command.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict, Forbidden
from app.core.http.pagination import Page
from app.modules.inventory.policies import require_warehouse
from app.modules.procurement import events as ev
from app.modules.procurement.common import (
    ZERO,
    cap,
    number,
    plain,
    product_briefs,
    require_scope,
    stock_product,
    user_briefs,
    warehouse_briefs,
)
from app.modules.procurement.enums import RequisitionAction, RequisitionStatus
from app.modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Requisition,
    RequisitionLine,
    VendorItem,
)
from app.modules.procurement.policies import PR_READ
from app.modules.procurement.schemas import (
    DocLink,
    RequisitionCreate,
    RequisitionDecision,
    RequisitionDetail,
    RequisitionLineRead,
    RequisitionSummary,
)
from app.platform.uow import UnitOfWork

S = RequisitionStatus
CREATE = "procurement.requisition.create"
UPDATE = "procurement.requisition.update"
APPROVE = "procurement.requisition.approve"


def path(requisition_id: uuid.UUID) -> str:
    return f"/operations/purchasing/requisitions/{requisition_id}"


def lines_of(uow: UnitOfWork, requisition_id: uuid.UUID) -> list[RequisitionLine]:
    return list(
        uow.session.scalars(
            select(RequisitionLine)
            .where(RequisitionLine.requisition_id == requisition_id)
            .order_by(RequisitionLine.line_no)
        )
    )


def create_requisition(uow: UnitOfWork, data: RequisitionCreate) -> Requisition:
    uow.actor.require(CREATE)
    wh = require_warehouse(uow, data.warehouse_id)
    r = Requisition(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        requisition_number="PR",
        status=S.DRAFT.value,
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        owner_user_id=uow.actor.user_id,
        required_by=data.required_by,
        notes=data.notes,
    )
    r.requisition_number = number(uow, "procurement.requisition", r.id, wh.branch_id)
    r.search_text = r.requisition_number.lower()
    uow.add(r)
    uow.flush()
    for i, ln in enumerate(data.lines, start=1):
        p = stock_product(uow, ln.product_id, ["lines", i - 1])
        if ln.suggested_vendor_item_id is not None:
            vi = uow.session.get(VendorItem, ln.suggested_vendor_item_id)
            if vi is None or vi.company_id != uow.actor.company_id or vi.product_id != p.id:
                from app.modules.procurement.common import invalid

                raise invalid(
                    "The vendor item is not for this product",
                    ["lines", i - 1, "suggested_vendor_item_id"],
                    "vendor_item_mismatch",
                )
        uow.add(
            RequisitionLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                requisition_id=r.id,
                line_no=i,
                product_id=p.id,
                quantity=ln.quantity,
                uom_code=ln.unit or p.stock_uom_code,
                required_by=ln.required_by or data.required_by,
                suggested_vendor_item_id=ln.suggested_vendor_item_id,
                demand_ref_type=ln.demand_ref_type,
                demand_ref_id=ln.demand_ref_id,
                notes=ln.notes,
            )
        )
    uow.flush()
    uow.audit(
        "procurement.requisition.create",
        resource_type="procurement.requisition",
        resource_id=r.id,
        resource_label=r.requisition_number,
    )
    return r


def _locked(uow: UnitOfWork, requisition_id: uuid.UUID, action: str = "read") -> Requisition:
    r = uow.repo(Requisition).get(requisition_id, action, for_update=True)
    require_warehouse(uow, r.warehouse_id)
    return r


def _emit(uow: UnitOfWork, r: Requisition, name: str) -> None:
    uow.emit(
        name,
        aggregate_id=r.id,
        aggregate_version=r.version,
        payload={"requisition_id": str(r.id), "requisition_number": r.requisition_number},
    )


#: (status, action) -> (to status, permission action)
TRANSITIONS: dict[tuple[str, str], tuple[str, str]] = {
    (S.DRAFT.value, RequisitionAction.SUBMIT.value): (S.SUBMITTED.value, "update"),
    (S.DRAFT.value, RequisitionAction.CANCEL.value): (S.CANCELLED.value, "update"),
    (S.SUBMITTED.value, RequisitionAction.APPROVE.value): (S.APPROVED.value, "approve"),
    (S.SUBMITTED.value, RequisitionAction.REJECT.value): (S.REJECTED.value, "approve"),
    (S.SUBMITTED.value, RequisitionAction.CANCEL.value): (S.CANCELLED.value, "update"),
    (S.APPROVED.value, RequisitionAction.CLOSE.value): (S.CLOSED.value, "update"),
}


def allowed_actions(status: str) -> list[RequisitionAction]:
    return [RequisitionAction(a) for (s, a) in TRANSITIONS if s == status]


def decide(uow: UnitOfWork, requisition_id: uuid.UUID, data: RequisitionDecision) -> Requisition:
    r = _locked(uow, requisition_id)
    t = TRANSITIONS.get((r.status, data.action.value))
    if t is None:
        raise Conflict(
            "That action is not available now",
            code="invalid_transition",
            current_status=r.status,
            allowed_transitions=[a.value for a in allowed_actions(r.status)],
        )
    to_status, perm = t
    require_scope(uow, Requisition, r.id, perm)
    uow.expect_version(r, data.expected_version)
    now = uow.now()
    if data.action is RequisitionAction.SUBMIT:
        r.submitted_at, r.submitted_by = now, uow.actor.user_id
    elif data.action in (RequisitionAction.APPROVE, RequisitionAction.REJECT):
        if uow.actor.user_id in (r.owner_user_id, r.submitted_by):
            raise Forbidden(
                "The person who raised or submitted a requisition cannot decide it",
                code="approver_is_requester",
            )
        if data.action is RequisitionAction.REJECT and not data.note:
            from app.modules.procurement.common import invalid

            raise invalid("Say why the requisition is rejected", ["note"], "reason_required")
        r.decided_at, r.decided_by, r.decision_note = now, uow.actor.user_id, data.note
    r.status = to_status
    uow.flush()
    name = {
        RequisitionAction.SUBMIT: ev.REQUISITION_SUBMITTED,
        RequisitionAction.APPROVE: ev.REQUISITION_APPROVED,
        RequisitionAction.REJECT: ev.REQUISITION_REJECTED,
    }.get(data.action)
    if name:
        _emit(uow, r, name)
    uow.audit(
        f"procurement.requisition.{data.action.value}",
        resource_type="procurement.requisition",
        resource_id=r.id,
        resource_label=r.requisition_number,
        reason=data.note,
    )
    return r


def refresh_ordered(uow: UnitOfWork, requisition_line_ids: list[uuid.UUID]) -> None:
    """Recompute ``qty_ordered`` of requisition lines from live PO lines; close fully ordered requisitions."""
    if not requisition_line_ids:
        return
    from app.modules.procurement.enums import PurchaseOrderStatus as P

    lines = list(
        uow.session.scalars(
            select(RequisitionLine).where(RequisitionLine.id.in_(requisition_line_ids)).with_for_update()
        )
    )
    for ln in lines:
        total = uow.session.scalar(
            select(func.coalesce(func.sum(PurchaseOrderLine.quantity - PurchaseOrderLine.qty_cancelled), 0))
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(PurchaseOrderLine.requisition_line_id == ln.id, PurchaseOrder.status != P.CANCELLED.value)
        )
        ln.qty_ordered = Decimal(total or 0)
    uow.flush()
    for rid in {ln.requisition_id for ln in lines}:
        r = uow.session.get(Requisition, rid)
        assert r is not None
        all_lines = lines_of(uow, rid)
        if r.status == S.APPROVED.value and all(
            Decimal(x.qty_ordered) >= Decimal(x.quantity) for x in all_lines
        ):
            r.status = S.CLOSED.value
            uow.flush()


# ---- reads ---------------------------------------------------------------------------------------------------------
def _summary_fields(uow: UnitOfWork, rows: list[Requisition]) -> list[dict]:  # type: ignore[type-arg]
    whs = warehouse_briefs(uow, [r.warehouse_id for r in rows])
    users = user_briefs(uow, [r.owner_user_id for r in rows])
    counts = (
        dict(
            uow.session.execute(
                select(RequisitionLine.requisition_id, func.count())
                .where(RequisitionLine.requisition_id.in_([r.id for r in rows]))
                .group_by(RequisitionLine.requisition_id)
            ).all()
        )
        if rows
        else {}
    )
    return [
        {
            "id": r.id,
            "requisition_number": r.requisition_number,
            "status": r.status,
            "warehouse": whs[r.warehouse_id],
            "owner": users[r.owner_user_id],
            "required_by": r.required_by,
            "line_count": int(counts.get(r.id, 0)),
            "created_at": r.created_at,
            "path": path(r.id),
            "version": r.version,
        }
        for r in rows
    ]


def list_requisitions(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Page[RequisitionSummary]:
    repo = uow.repo(Requisition)
    filters = []
    if status:
        filters.append(Requisition.status.in_(status))
    if q and (f := repo.search_filter(q, ["search_text"])) is not None:
        filters.append(f)
    page = repo.list(
        *filters, order_by=[Requisition.created_at.desc(), Requisition.id.desc()], limit=limit, offset=offset
    )
    items = [RequisitionSummary(**d) for d in _summary_fields(uow, list(page.items))]
    return Page[RequisitionSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def detail(uow: UnitOfWork, r: Requisition) -> RequisitionDetail:
    lines = lines_of(uow, r.id)
    products = product_briefs(uow, [ln.product_id for ln in lines])
    users = user_briefs(uow, [r.submitted_by, r.decided_by])
    pos = list(
        uow.session.execute(
            select(PurchaseOrder.id, PurchaseOrder.po_number, PurchaseOrder.status)
            .where(PurchaseOrder.requisition_id == r.id)
            .order_by(PurchaseOrder.po_number)
        ).all()
    )
    repo = uow.repo(Requisition)
    in_update = uow.session.scalar(
        select(Requisition.id).where(Requisition.id == r.id, repo.clause("update"))
    )
    in_approve = uow.session.scalar(
        select(Requisition.id).where(Requisition.id == r.id, repo.clause("approve"))
    )
    own = uow.actor.user_id in (r.owner_user_id, r.submitted_by)
    submitted = r.status == S.SUBMITTED.value
    decide_cap = cap(
        bool(in_approve) and submitted and not own,
        "permission_denied"
        if not in_approve
        else "approver_is_requester"
        if own and submitted
        else "invalid_status",
    )
    can_convert = bool(uow.actor.can("procurement.purchase_order.create")) and r.status == S.APPROVED.value
    base = _summary_fields(uow, [r])[0]
    return RequisitionDetail(
        **base,
        notes=r.notes,
        submitted_at=r.submitted_at,
        submitted_by=users.get(r.submitted_by) if r.submitted_by else None,
        decided_at=r.decided_at,
        decided_by=users.get(r.decided_by) if r.decided_by else None,
        decision_note=r.decision_note,
        lines=[
            RequisitionLineRead(
                id=ln.id,
                line_no=ln.line_no,
                product=products[ln.product_id],
                quantity=plain(ln.quantity),
                unit=ln.uom_code,
                required_by=ln.required_by,
                qty_ordered=plain(ln.qty_ordered),
                qty_remaining=plain(max(Decimal(ln.quantity) - Decimal(ln.qty_ordered), ZERO)),
                suggested_vendor_item_id=ln.suggested_vendor_item_id,
                demand_ref_type=ln.demand_ref_type,
                demand_ref_id=ln.demand_ref_id,
                notes=ln.notes,
            )
            for ln in lines
        ],
        purchase_orders=[
            DocLink(id=i, number=n, status=s, path=f"/operations/purchasing/orders/{i}") for i, n, s in pos
        ],
        capabilities={
            "submit": cap(
                bool(in_update) and r.status == S.DRAFT.value,
                "permission_denied" if not in_update else "invalid_status",
            ),
            "approve": decide_cap,
            "reject": decide_cap,
            "cancel": cap(
                bool(in_update) and r.status in (S.DRAFT.value, S.SUBMITTED.value),
                "permission_denied" if not in_update else "invalid_status",
            ),
            "convert": cap(
                can_convert,
                "invalid_status"
                if uow.actor.can("procurement.purchase_order.create")
                else "permission_denied",
            ),
        },
    )


def get_requisition(uow: UnitOfWork, requisition_id: uuid.UUID) -> RequisitionDetail:
    r = uow.repo(Requisition).get(requisition_id)
    require_warehouse(uow, r.warehouse_id)
    return detail(uow, r)


READ = PR_READ
