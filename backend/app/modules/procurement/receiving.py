"""Goods receipts (``GRN-YYYY-NNNN``): partial receipts per purchase-order line.

Posting a receipt (``procurement.goods_receipt.post`` in scope over the receiving warehouse):
1. lock the PO, then its lines by id (the documented lock order: header -> lines -> stock rows inside the posting);
2. each line stays within ``ordered x (1 + tolerance) - cancelled - (received - rejected)`` (409 ``over_receipt``),
   in the PO line's unit, with a lot code for lot-tracked products;
3. **one** posting through ``inventory.service.post_movement`` (source ``goods_receipt``, purpose ``receive``):
   supplier -> the warehouse's QC hold for QC-required products, supplier -> a stock bin otherwise;
4. QC-free quantities count as accepted at once; QC-required lines create a quality inspection, and the stock only
   becomes available when the inspection releases it;
5. the PO becomes partially received / received; ``procurement.goods_receipt.posted`` is emitted.
Replays (same key, a re-delivered command, a second click) return the same posting.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.core.errors import Conflict
from app.core.http.pagination import Page
from app.modules.inventory.enums import LocationType
from app.modules.inventory.policies import can_on_warehouse, require_warehouse
from app.modules.inventory.service import (
    PostingLine,
    PostingRequest,
    company_location,
    default_location,
    get_location,
    post_movement,
    warehouse_location,
)
from app.modules.procurement import events as ev
from app.modules.procurement.common import (
    business_date,
    cap,
    invalid,
    party_briefs,
    plain,
    product_briefs,
    user_briefs,
    warehouse_briefs,
)
from app.modules.procurement.enums import PO_OPEN_FOR_RECEIPT, GoodsReceiptStatus
from app.modules.procurement.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine
from app.modules.procurement.policies import GRN_POST
from app.modules.procurement.purchase_orders import lines_of, receivable, recompute_status
from app.modules.procurement.schemas import DocLink, GrnCreate, GrnDetail, GrnLineRead, GrnSummary
from app.platform.uow import UnitOfWork

G = GoodsReceiptStatus
OPEN = frozenset(s.value for s in PO_OPEN_FOR_RECEIPT)
SUBJECT = "procurement.goods_receipt_line"


def path(grn_id: uuid.UUID) -> str:
    return f"/operations/purchasing/receipts/{grn_id}"


def grn_lines(uow: UnitOfWork, grn_id: uuid.UUID) -> list[GoodsReceiptLine]:
    return list(
        uow.session.scalars(
            select(GoodsReceiptLine)
            .where(GoodsReceiptLine.goods_receipt_id == grn_id)
            .order_by(GoodsReceiptLine.line_no)
        )
    )


def _po_for_receipt(uow: UnitOfWork, po_id: uuid.UUID) -> PurchaseOrder:
    """The PO (404 outside the actor's PO read scope) locked for receiving."""
    po = uow.repo(PurchaseOrder).get(po_id, for_update=True)
    if po.status not in OPEN:
        raise Conflict("The order is not open for receiving", code="po_not_open", current_status=po.status)
    return po


def create_receipt(uow: UnitOfWork, data: GrnCreate) -> GoodsReceipt:
    po = _po_for_receipt(uow, data.purchase_order_id)
    wh = require_warehouse(uow, data.warehouse_id or po.warehouse_id, GRN_POST)
    po_lines = {ln.id: ln for ln in lines_of(uow, po.id)}
    grn = GoodsReceipt(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        grn_number="GRN",
        purchase_order_id=po.id,
        vendor_party_id=po.vendor_party_id,
        warehouse_id=wh.id,
        branch_id=wh.branch_id,
        status=G.DRAFT.value,
        received_on=data.received_on or business_date(uow),
        vendor_challan_ref=data.vendor_challan_ref,
        vendor_invoice_ref=data.vendor_invoice_ref,
        notes=data.notes,
    )
    grn.grn_number = uow.allocate_number(
        "procurement.goods_receipt",
        document_date=business_date(uow),
        resource_type="procurement.goods_receipt",
        resource_id=grn.id,
        branch_id=wh.branch_id,
    )
    uow.add(grn)
    uow.flush()
    products = product_briefs(uow, [ln.product_id for ln in po_lines.values()])
    for i, ln in enumerate(data.lines, start=1):
        loc: list[str | int] = ["lines", i - 1]
        pl = po_lines.get(ln.po_line_id)
        if pl is None:
            raise invalid("The line is not on this purchase order", [*loc, "po_line_id"], "po_line_mismatch")
        if ln.unit and ln.unit != pl.uom_code:
            raise invalid(f"Receive in the order unit ({pl.uom_code})", [*loc, "unit"], "unit_mismatch")
        product = products[pl.product_id]
        if product.track_lots and not ln.lot_code:
            raise invalid(
                "Enter the lot code (the product is lot-tracked)", [*loc, "lot_code"], "lot_required"
            )
        location_id = None
        if not product.qc_required and ln.location_id is not None:
            target = get_location(uow, ln.location_id)
            if target.warehouse_id != wh.id or target.location_type != LocationType.INTERNAL.value:
                raise invalid(
                    "Choose a stock location of the receiving warehouse",
                    [*loc, "location_id"],
                    "location_not_in_warehouse",
                )
            location_id = target.id
        uow.add(
            GoodsReceiptLine(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                goods_receipt_id=grn.id,
                line_no=i,
                po_line_id=pl.id,
                product_id=pl.product_id,
                quantity=ln.quantity,
                uom_code=pl.uom_code,
                lot_code=ln.lot_code,
                supplier_lot_ref=ln.supplier_lot_ref,
                location_id=location_id,
                qc_required=product.qc_required,
            )
        )
    uow.flush()
    uow.audit(
        "procurement.goods_receipt.create",
        resource_type="procurement.goods_receipt",
        resource_id=grn.id,
        resource_label=grn.grn_number,
        details={"po_number": po.po_number},
    )
    return grn


def post_receipt(uow: UnitOfWork, grn_id: uuid.UUID, *, expected_version: int | None = None) -> GoodsReceipt:
    grn = uow.repo(GoodsReceipt).get(grn_id, for_update=True)
    require_warehouse(uow, grn.warehouse_id, GRN_POST)
    uow.repo(GoodsReceipt).require_action(grn, "post")
    if grn.status == G.POSTED.value:
        return grn  # already posted (a replay); the posting is unique per receipt anyway
    if grn.status != G.DRAFT.value:
        raise Conflict("Only a draft receipt is posted", code="invalid_status", current_status=grn.status)
    if expected_version is not None:
        uow.expect_version(grn, expected_version)
    po = _po_for_receipt(uow, grn.purchase_order_id)
    po_lines = {ln.id: ln for ln in lines_of(uow, po.id, for_update=True)}
    lines = grn_lines(uow, grn.id)
    from app.modules.inventory.documents import ensure_lot

    supplier = company_location(uow, LocationType.SUPPLIER)
    qc_hold = warehouse_location(uow, grn.warehouse_id, LocationType.QC_HOLD)
    stock = default_location(uow, grn.warehouse_id)
    requested: dict[uuid.UUID, Decimal] = {}
    for gl in lines:
        requested[gl.po_line_id] = requested.get(gl.po_line_id, Decimal(0)) + Decimal(gl.quantity)
    for po_line_id, qty in requested.items():
        pl = po_lines[po_line_id]
        if qty > receivable(pl):
            raise Conflict(
                f"Line {pl.line_no}: more than the order allows (open {plain(receivable(pl))} {pl.uom_code})",
                code="over_receipt",
                po_line_id=str(pl.id),
            )
    posting_lines: list[PostingLine] = []
    for gl in lines:
        if gl.lot_code:
            lot = ensure_lot(uow, gl.product_id, gl.lot_code)
            if gl.supplier_lot_ref and not lot.supplier_lot_ref:
                lot.supplier_lot_ref = gl.supplier_lot_ref
            gl.lot_id = lot.id
        gl.location_id = qc_hold.id if gl.qc_required else (gl.location_id or stock.id)
        posting_lines.append(
            PostingLine(
                product_id=gl.product_id,
                quantity=Decimal(gl.quantity),
                uom_code=gl.uom_code,
                from_location_id=supplier.id,
                to_location_id=gl.location_id,
                lot_id=gl.lot_id,
                counterparty_party_id=grn.vendor_party_id,
                source_line_type=SUBJECT,
                source_line_id=gl.id,
            )
        )
    uow.flush()
    receipt = post_movement(
        uow,
        PostingRequest(
            source_type="goods_receipt",
            source_id=grn.id,
            purpose="receive",
            source_label=grn.grn_number,
            lines=tuple(posting_lines),
        ),
    )
    from app.modules.quality import service as quality

    for gl in lines:
        pl = po_lines[gl.po_line_id]
        pl.qty_received = Decimal(pl.qty_received) + Decimal(gl.quantity)
        if not gl.qc_required:
            pl.qty_accepted = Decimal(pl.qty_accepted) + Decimal(gl.quantity)
    uow.flush()
    for gl in lines:
        if gl.qc_required:
            insp = quality.request_inspection(
                uow,
                subject_type=SUBJECT,
                subject_id=gl.id,
                subject_label=f"{grn.grn_number} line {gl.line_no}",
                product_id=gl.product_id,
                warehouse_id=grn.warehouse_id,
                quantity=Decimal(gl.quantity),
                uom_code=gl.uom_code,
                lot_id=gl.lot_id,
                source_type="procurement.goods_receipt",
                source_id=grn.id,
            )
            gl.inspection_id = insp.id
    grn.status, grn.posting_id = G.POSTED.value, receipt.posting.id
    grn.posted_at, grn.posted_by = uow.now(), uow.actor.user_id
    uow.flush()
    recompute_status(uow, po)
    uow.emit(
        ev.GRN_POSTED,
        aggregate_id=grn.id,
        aggregate_version=grn.version,
        payload={
            "goods_receipt_id": str(grn.id),
            "purchase_order_id": str(po.id),
            "line_ids": [str(gl.id) for gl in lines],
        },
    )
    uow.audit(
        "procurement.goods_receipt.post",
        resource_type="procurement.goods_receipt",
        resource_id=grn.id,
        resource_label=grn.grn_number,
        details={"posting_id": str(receipt.posting.id)},
    )
    return grn


def cancel_draft(uow: UnitOfWork, grn_id: uuid.UUID, expected_version: int) -> GoodsReceipt:
    grn = uow.repo(GoodsReceipt).get(grn_id, for_update=True)
    require_warehouse(uow, grn.warehouse_id, GRN_POST)
    uow.repo(GoodsReceipt).require_action(grn, "post")
    uow.expect_version(grn, expected_version)
    if grn.status != G.DRAFT.value:
        raise Conflict("Only a draft receipt is cancelled", code="invalid_status", current_status=grn.status)
    grn.status = G.CANCELLED.value
    uow.flush()
    return grn


def on_inspection_decided(uow: UnitOfWork, insp: object) -> None:
    """Quality callback: the inspected GRN line's accepted / rejected figures move onto its PO line."""
    gl = uow.session.get(GoodsReceiptLine, insp.subject_id)  # type: ignore[attr-defined]
    if gl is None:
        return
    pl = uow.session.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.id == gl.po_line_id).with_for_update()
    ).one()
    pl.qty_accepted = Decimal(pl.qty_accepted) + Decimal(insp.qty_accepted)  # type: ignore[attr-defined]
    pl.qty_rejected = Decimal(pl.qty_rejected) + Decimal(insp.qty_rejected)  # type: ignore[attr-defined]
    uow.flush()
    po = uow.session.get(PurchaseOrder, pl.purchase_order_id)
    assert po is not None
    recompute_status(uow, po)


# ---- reads ------------------------------------------------------------------------------------------------------------
def _summaries(uow: UnitOfWork, rows: list[GoodsReceipt]) -> list[dict]:  # type: ignore[type-arg]
    pos = (
        {
            r[0]: r
            for r in uow.session.execute(
                select(PurchaseOrder.id, PurchaseOrder.po_number, PurchaseOrder.status).where(
                    PurchaseOrder.id.in_([r.purchase_order_id for r in rows])
                )
            ).all()
        }
        if rows
        else {}
    )
    vendors = party_briefs(uow, [r.vendor_party_id for r in rows])
    whs = warehouse_briefs(uow, [r.warehouse_id for r in rows])
    counts = (
        dict(
            uow.session.execute(
                select(GoodsReceiptLine.goods_receipt_id, func.count())
                .where(GoodsReceiptLine.goods_receipt_id.in_([r.id for r in rows]))
                .group_by(GoodsReceiptLine.goods_receipt_id)
            ).all()
        )
        if rows
        else {}
    )
    from app.modules.quality.models import Inspection

    waiting = (
        dict(
            uow.session.execute(
                select(Inspection.source_id, func.count())
                .where(Inspection.source_id.in_([r.id for r in rows]), Inspection.status == "pending")
                .group_by(Inspection.source_id)
            ).all()
        )
        if rows
        else {}
    )
    return [
        {
            "id": r.id,
            "grn_number": r.grn_number,
            "status": r.status,
            "purchase_order": DocLink(
                id=r.purchase_order_id,
                number=pos[r.purchase_order_id][1],
                status=pos[r.purchase_order_id][2],
                path=f"/operations/purchasing/orders/{r.purchase_order_id}",
            ),
            "vendor": vendors[r.vendor_party_id],
            "warehouse": whs[r.warehouse_id],
            "received_on": r.received_on,
            "line_count": int(counts.get(r.id, 0)),
            "awaiting_qc": int(waiting.get(r.id, 0)),
            "path": path(r.id),
            "version": r.version,
        }
        for r in rows
    ]


def list_receipts(
    uow: UnitOfWork,
    *,
    status: list[str] | None = None,
    purchase_order_id: uuid.UUID | None = None,
    awaiting_qc: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Page[GrnSummary]:
    repo = uow.repo(GoodsReceipt)
    filters = []
    if status:
        filters.append(GoodsReceipt.status.in_(status))
    if purchase_order_id is not None:
        filters.append(GoodsReceipt.purchase_order_id == purchase_order_id)
    if awaiting_qc:
        from app.modules.quality.models import Inspection

        filters.append(
            GoodsReceipt.id.in_(select(Inspection.source_id).where(Inspection.status == "pending"))
        )
    page = repo.list(
        *filters,
        order_by=[GoodsReceipt.created_at.desc(), GoodsReceipt.id.desc()],
        limit=limit,
        offset=offset,
    )
    items = [GrnSummary(**d) for d in _summaries(uow, list(page.items))]
    return Page[GrnSummary](items=items, total=page.total, limit=page.limit, offset=page.offset)


def detail(uow: UnitOfWork, grn: GoodsReceipt) -> GrnDetail:
    from app.modules.inventory.reads import location_refs
    from app.modules.quality.models import Inspection

    lines = grn_lines(uow, grn.id)
    products = product_briefs(uow, [ln.product_id for ln in lines])
    po_line_nos = (
        dict(
            uow.session.execute(
                select(PurchaseOrderLine.id, PurchaseOrderLine.line_no).where(
                    PurchaseOrderLine.id.in_([ln.po_line_id for ln in lines])
                )
            ).all()
        )
        if lines
        else {}
    )
    locs = location_refs(uow, [ln.location_id for ln in lines])
    insps = (
        {
            i.id: i
            for i in uow.session.scalars(
                select(Inspection).where(
                    Inspection.id.in_([ln.inspection_id for ln in lines if ln.inspection_id])
                )
            )
        }
        if any(ln.inspection_id for ln in lines)
        else {}
    )
    users = user_briefs(uow, [grn.posted_by])
    can_post = can_on_warehouse(uow, grn.warehouse_id, GRN_POST) and uow.repo(GoodsReceipt).can(grn, "post")
    draft = grn.status == G.DRAFT.value
    return GrnDetail(
        **_summaries(uow, [grn])[0],
        vendor_challan_ref=grn.vendor_challan_ref,
        vendor_invoice_ref=grn.vendor_invoice_ref,
        notes=grn.notes,
        posting_id=grn.posting_id,
        posted_at=grn.posted_at,
        posted_by=users.get(grn.posted_by) if grn.posted_by else None,
        lines=[
            GrnLineRead(
                id=ln.id,
                line_no=ln.line_no,
                po_line_id=ln.po_line_id,
                po_line_no=po_line_nos.get(ln.po_line_id, 0),
                product=products[ln.product_id],
                quantity=plain(ln.quantity),
                unit=ln.uom_code,
                lot_code=ln.lot_code,
                supplier_lot_ref=ln.supplier_lot_ref,
                lot_id=ln.lot_id,
                location_code=locs[ln.location_id].code if ln.location_id in locs else None,
                qc_required=ln.qc_required,
                inspection=DocLink(
                    id=insps[ln.inspection_id].id,
                    number=insps[ln.inspection_id].inspection_number,
                    status=insps[ln.inspection_id].status,
                    path=f"/operations/quality/{ln.inspection_id}",
                )
                if ln.inspection_id in insps
                else None,
            )
            for ln in lines
        ],
        capabilities={
            "post": cap(can_post and draft, "invalid_status" if can_post else "permission_denied"),
            "cancel": cap(can_post and draft, "invalid_status" if can_post else "permission_denied"),
        },
    )


def get_receipt(uow: UnitOfWork, grn_id: uuid.UUID) -> GrnDetail:
    grn = uow.repo(GoodsReceipt).get(grn_id)
    require_warehouse(uow, grn.warehouse_id)
    return detail(uow, grn)
