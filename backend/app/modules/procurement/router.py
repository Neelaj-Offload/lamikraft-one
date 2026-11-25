"""Procurement API (``/api/v1/procurement``): vendor items, requisitions, purchase orders, goods receipts and vendor
bills. Commands accept ``Idempotency-Key`` (replays answer ``Idempotent-Replayed: true``). Scope is enforced in the
services: a document, warehouse or vendor outside the actor's scope is a 404; an action without the key is a 403."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.inventory.commands import idempotent
from app.modules.procurement import (
    factory,
    matching,
    purchase_orders,
    receiving,
    requisitions,
    service,
    vendor_items,
)
from app.modules.procurement.enums import GoodsReceiptStatus, PurchaseOrderStatus, RequisitionStatus
from app.modules.procurement.schemas import (
    BillCreate,
    BillRead,
    ConvertToPo,
    ExpectedDateChange,
    GrnCreate,
    GrnDetail,
    GrnSummary,
    LineCancel,
    PoCreate,
    PoDetail,
    PoSummary,
    PoTransition,
    PoUpdate,
    RequisitionCreate,
    RequisitionDecision,
    RequisitionDetail,
    RequisitionSummary,
    VendorItemIn,
    VendorItemRead,
    Versioned,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/procurement", tags=["procurement"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
Search = Annotated[str | None, Query(max_length=200)]
PR_READ, PO_READ, GRN_READ = (
    "procurement.requisition.read",
    "procurement.purchase_order.read",
    "procurement.goods_receipt.read",
)


def _run[T: BaseModel](
    actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T], model: type[T]
) -> T:
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(uow, operation, body, lambda: fn(uow), model)
    if replayed:
        response.headers[REPLAYED] = "true"
    return out


class VendorItemList(BaseModel):
    items: list[VendorItemRead]


class BillList(BaseModel):
    items: list[BillRead]


# ---- vendor items ---------------------------------------------------------------------------------------------------
@router.get("/vendor-items", openapi_extra=requires("procurement.vendor_item.read"))
def list_vendor_items(
    actor: Actor,
    vendor_party_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    include_history: bool = False,
) -> VendorItemList:
    """Active vendor items (or the full price history); a vendor filter needs the vendor to be visible."""
    with UnitOfWork(actor) as uow:
        return VendorItemList(
            items=vendor_items.list_vendor_items(
                uow, vendor_party_id=vendor_party_id, product_id=product_id, include_history=include_history
            )
        )


@router.post("/vendor-items", status_code=201, openapi_extra=requires("procurement.vendor_item.manage"))
def save_vendor_item(
    actor: Actor, body: VendorItemIn, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> VendorItemRead:
    """Create a vendor item, or a new version superseding the active one for the same vendor and product."""

    def make(uow: UnitOfWork) -> VendorItemRead:
        return vendor_items.reads(uow, [vendor_items.save_vendor_item(uow, body)])[0]

    return _run(
        actor,
        response,
        f"procurement.vendor_item:{body.vendor_party_id}:{body.product_id}",
        body,
        make,
        VendorItemRead,
    )


# ---- requisitions -----------------------------------------------------------------------------------------------------
@router.get("/requisitions", openapi_extra=requires(PR_READ))
def list_requisitions(
    actor: Actor,
    status: Annotated[list[RequisitionStatus] | None, Query()] = None,
    q: Search = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[RequisitionSummary]:
    with UnitOfWork(actor) as uow:
        return requisitions.list_requisitions(
            uow, status=[s.value for s in status or []] or None, q=q, limit=limit, offset=offset
        )


@router.post("/requisitions", status_code=201, openapi_extra=requires("procurement.requisition.create"))
def create_requisition(
    actor: Actor, body: RequisitionCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> RequisitionDetail:
    return _run(
        actor,
        response,
        "procurement.requisition.create",
        body,
        lambda uow: requisitions.detail(uow, requisitions.create_requisition(uow, body)),
        RequisitionDetail,
    )


@router.get("/requisitions/{requisition_id}", openapi_extra=requires(PR_READ))
def get_requisition(actor: Actor, requisition_id: uuid.UUID) -> RequisitionDetail:
    with UnitOfWork(actor) as uow:
        return requisitions.get_requisition(uow, requisition_id)


@router.post(
    "/requisitions/{requisition_id}/transitions",
    openapi_extra=requires("procurement.requisition.update", "procurement.requisition.approve"),
)
def transition_requisition(
    actor: Actor,
    requisition_id: uuid.UUID,
    body: RequisitionDecision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> RequisitionDetail:
    """``submit``, ``approve`` / ``reject`` (never by the requester or submitter; reject needs a note), ``cancel``,
    ``close``."""
    return _run(
        actor,
        response,
        f"procurement.requisition.transition:{requisition_id}",
        body,
        lambda uow: requisitions.detail(uow, requisitions.decide(uow, requisition_id, body)),
        RequisitionDetail,
    )


@router.post(
    "/requisitions/{requisition_id}/convert",
    status_code=201,
    openapi_extra=requires("procurement.purchase_order.create"),
)
def convert_requisition(
    actor: Actor,
    requisition_id: uuid.UUID,
    body: ConvertToPo,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PoDetail:
    """A draft purchase order for one vendor from the approved requisition's unordered remainder."""
    return _run(
        actor,
        response,
        f"procurement.requisition.convert:{requisition_id}",
        body,
        lambda uow: purchase_orders.detail(
            uow, purchase_orders.convert_requisition(uow, requisition_id, body)
        ),
        PoDetail,
    )


# ---- purchase orders ----------------------------------------------------------------------------------------------------
@router.get("/purchase-orders", openapi_extra=requires(PO_READ))
def list_purchase_orders(
    actor: Actor,
    status: Annotated[list[PurchaseOrderStatus] | None, Query()] = None,
    vendor_party_id: uuid.UUID | None = None,
    overdue: bool = False,
    q: Search = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[PoSummary]:
    with UnitOfWork(actor) as uow:
        return purchase_orders.list_purchase_orders(
            uow,
            status=[s.value for s in status or []] or None,
            vendor_party_id=vendor_party_id,
            overdue_only=overdue,
            q=q,
            limit=limit,
            offset=offset,
        )


@router.post("/purchase-orders", status_code=201, openapi_extra=requires("procurement.purchase_order.create"))
def create_purchase_order(
    actor: Actor, body: PoCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PoDetail:
    return _run(
        actor,
        response,
        "procurement.purchase_order.create",
        body,
        lambda uow: purchase_orders.detail(uow, purchase_orders.create_purchase_order(uow, body)),
        PoDetail,
    )


@router.get("/purchase-orders/lookup", openapi_extra=requires(PO_READ))
def get_purchase_order_by_number(actor: Actor, po_number: Annotated[str, Query(max_length=20)]) -> PoDetail:
    with UnitOfWork(actor) as uow:
        return purchase_orders.get_by_number(uow, po_number)


@router.get("/purchase-orders/{po_id}", openapi_extra=requires(PO_READ))
def get_purchase_order(actor: Actor, po_id: uuid.UUID) -> PoDetail:
    """Detail with lines (ordered, received, accepted, rejected, pending QC, cancelled, billed, outstanding),
    receipts, bills, ``allowed_transitions`` and ``capabilities``."""
    with UnitOfWork(actor) as uow:
        return purchase_orders.get_purchase_order(uow, po_id)


@router.patch("/purchase-orders/{po_id}", openapi_extra=requires("procurement.purchase_order.update"))
def update_purchase_order(
    actor: Actor,
    po_id: uuid.UUID,
    body: PoUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PoDetail:
    """Draft only: header notes and a full replacement of the lines."""
    return _run(
        actor,
        response,
        f"procurement.purchase_order.update:{po_id}",
        body,
        lambda uow: purchase_orders.detail(uow, purchase_orders.update_purchase_order(uow, po_id, body)),
        PoDetail,
    )


@router.post(
    "/purchase-orders/{po_id}/transitions",
    openapi_extra=requires(
        "procurement.purchase_order.update",
        "procurement.purchase_order.approve",
        "procurement.purchase_order.issue",
        "procurement.purchase_order.transition",
    ),
)
def transition_purchase_order(
    actor: Actor,
    po_id: uuid.UUID,
    body: PoTransition,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PoDetail:
    """``submit``, ``approve`` / ``reject`` (never by the submitter), ``issue``, ``close`` (short-close needs a
    reason), ``cancel`` (reason; refused once goods were received)."""
    return _run(
        actor,
        response,
        f"procurement.purchase_order.transition:{po_id}",
        body,
        lambda uow: purchase_orders.detail(uow, purchase_orders.transition(uow, po_id, body)),
        PoDetail,
    )


@router.post(
    "/purchase-orders/{po_id}/lines/{line_id}/expected-date",
    openapi_extra=requires("procurement.purchase_order.update"),
)
def change_expected_date(
    actor: Actor,
    po_id: uuid.UUID,
    line_id: uuid.UUID,
    body: ExpectedDateChange,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PoDetail:
    return _run(
        actor,
        response,
        f"procurement.purchase_order.expected_date:{line_id}",
        body,
        lambda uow: purchase_orders.detail(
            uow, purchase_orders.change_expected_date(uow, po_id, line_id, body)
        ),
        PoDetail,
    )


@router.post(
    "/purchase-orders/{po_id}/lines/{line_id}/cancel",
    openapi_extra=requires("procurement.purchase_order.transition"),
)
def cancel_purchase_order_line(
    actor: Actor,
    po_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineCancel,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PoDetail:
    return _run(
        actor,
        response,
        f"procurement.purchase_order.cancel_line:{line_id}",
        body,
        lambda uow: purchase_orders.detail(
            uow, purchase_orders.cancel_line_quantity(uow, po_id, line_id, body)
        ),
        PoDetail,
    )


@router.get("/purchase-orders/{po_id}/bills", openapi_extra=requires("procurement.vendor_bill.read"))
def list_purchase_order_bills(actor: Actor, po_id: uuid.UUID) -> BillList:
    with UnitOfWork(actor) as uow:
        return BillList(items=matching.list_bills(uow, po_id))


# ---- goods receipts ------------------------------------------------------------------------------------------------------
@router.get("/goods-receipts", openapi_extra=requires(GRN_READ))
def list_goods_receipts(
    actor: Actor,
    status: Annotated[list[GoodsReceiptStatus] | None, Query()] = None,
    purchase_order_id: uuid.UUID | None = None,
    awaiting_qc: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[GrnSummary]:
    with UnitOfWork(actor) as uow:
        return receiving.list_receipts(
            uow,
            status=[s.value for s in status or []] or None,
            purchase_order_id=purchase_order_id,
            awaiting_qc=awaiting_qc,
            limit=limit,
            offset=offset,
        )


@router.post("/goods-receipts", status_code=201, openapi_extra=requires("procurement.goods_receipt.post"))
def create_goods_receipt(
    actor: Actor, body: GrnCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> GrnDetail:
    """A draft receipt against a PO (``post: true`` posts it in the same command)."""

    def make(uow: UnitOfWork) -> GrnDetail:
        grn = receiving.create_receipt(uow, body)
        if body.post:
            grn = receiving.post_receipt(uow, grn.id)
        return receiving.detail(uow, grn)

    return _run(
        actor, response, f"procurement.goods_receipt.create:{body.purchase_order_id}", body, make, GrnDetail
    )


@router.get("/goods-receipts/{grn_id}", openapi_extra=requires(GRN_READ))
def get_goods_receipt(actor: Actor, grn_id: uuid.UUID) -> GrnDetail:
    with UnitOfWork(actor) as uow:
        return receiving.get_receipt(uow, grn_id)


@router.post("/goods-receipts/{grn_id}/post", openapi_extra=requires("procurement.goods_receipt.post"))
def post_goods_receipt(
    actor: Actor,
    grn_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> GrnDetail:
    """Post the stock movement (one posting per receipt): QC-required products go to QC hold with an inspection."""
    return _run(
        actor,
        response,
        f"procurement.goods_receipt.post:{grn_id}",
        body,
        lambda uow: receiving.detail(
            uow, receiving.post_receipt(uow, grn_id, expected_version=body.expected_version)
        ),
        GrnDetail,
    )


@router.post("/goods-receipts/{grn_id}/cancel", openapi_extra=requires("procurement.goods_receipt.post"))
def cancel_goods_receipt(
    actor: Actor,
    grn_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> GrnDetail:
    return _run(
        actor,
        response,
        f"procurement.goods_receipt.cancel:{grn_id}",
        body,
        lambda uow: receiving.detail(uow, receiving.cancel_draft(uow, grn_id, body.expected_version)),
        GrnDetail,
    )


# ---- vendor bills ---------------------------------------------------------------------------------------------------------
@router.post("/vendor-bills", status_code=201, openapi_extra=requires("procurement.vendor_bill.create"))
def create_vendor_bill(
    actor: Actor, body: BillCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> BillRead:
    """Record a vendor bill against a PO and run the three-way match at once."""
    return _run(
        actor,
        response,
        f"procurement.vendor_bill.create:{body.purchase_order_id}:{body.bill_number}",
        body,
        lambda uow: matching.read(uow, matching.create_bill(uow, body)),
        BillRead,
    )


@router.get("/vendor-bills/{bill_id}", openapi_extra=requires("procurement.vendor_bill.read"))
def get_vendor_bill(actor: Actor, bill_id: uuid.UUID) -> BillRead:
    with UnitOfWork(actor) as uow:
        return matching.get_bill(uow, bill_id)


@router.post("/vendor-bills/{bill_id}/match", openapi_extra=requires("procurement.vendor_bill.create"))
def match_vendor_bill(
    actor: Actor,
    bill_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> BillRead:
    """Re-run the match (after QC decisions or corrections)."""
    return _run(
        actor,
        response,
        f"procurement.vendor_bill.match:{bill_id}",
        body,
        lambda uow: matching.read(
            uow, matching.match_bill(uow, bill_id, expected_version=body.expected_version)
        ),
        BillRead,
    )


@router.post("/vendor-bills/{bill_id}/hand-off", openapi_extra=requires("procurement.vendor_bill.create"))
def hand_off_vendor_bill(
    actor: Actor,
    bill_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> BillRead:
    """Hand a matched bill to finance (an event in Slice 4; the accounting adapter arrives in Slice 5)."""
    return _run(
        actor,
        response,
        f"procurement.vendor_bill.hand_off:{bill_id}",
        body,
        lambda uow: matching.read(uow, matching.hand_off(uow, bill_id, body.expected_version)),
        BillRead,
    )


__all__ = ["router", "service"]


# ---- factory orders as stock work in progress (module 4) ------------------------------------------------------------
@router.get("/factory-orders", openapi_extra=requires("procurement.purchase_order.read"))
def list_factory_orders(
    actor: Actor,
    product_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[factory.FactoryOrderLine]:
    """Open purchase-order lines for finished products: what the factories still have to deliver."""
    return factory.factory_orders(actor, product_id=product_id, limit=limit, offset=offset)
