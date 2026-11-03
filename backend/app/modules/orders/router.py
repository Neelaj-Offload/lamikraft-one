"""Sales order API (``/api/v1/orders/sales-orders``): list, lookup, convert an accepted quote (idempotent), detail,
logistics edits, transitions, line cancellation, reservations, the draft delivery challan and the impact preview.
Commands accept ``Idempotency-Key`` (replays answer ``Idempotent-Replayed: true``)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.inventory.commands import idempotent
from app.modules.orders import service
from app.modules.orders.enums import FulfilmentState, OrderStatus
from app.modules.orders.schemas import (
    ChallanFromOrder,
    ConversionResult,
    ImpactPreview,
    LineCancel,
    OrderFilters,
    OrderTransition,
    OrderUpdate,
    ReleaseRequest,
    ReserveRequest,
    ReserveResponse,
    SalesOrderDetail,
    SalesOrderSummary,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/orders", tags=["orders"])
READ, UPDATE, TRANSITION = service.READ, service.UPDATE, service.TRANSITION
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


class ConvertRequest(BaseModel):
    quote_id: uuid.UUID


class ChallanCreated(BaseModel):
    challan_id: uuid.UUID
    path: str


def _run[T: BaseModel](
    actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T], model: type[T]
) -> T:
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(uow, operation, body, lambda: fn(uow), model)
    if replayed:
        response.headers[REPLAYED] = "true"
    return out


def _filters(
    q: Annotated[
        str | None,
        Query(max_length=200, description="Tokens matched against order number, quote number and party"),
    ] = None,
    status: Annotated[list[OrderStatus] | None, Query()] = None,
    fulfilment_state: Annotated[list[FulfilmentState] | None, Query()] = None,
    party_id: uuid.UUID | None = None,
    source_quote_id: uuid.UUID | None = None,
    scope: Annotated[str, Query(pattern=r"^(mine|all)$")] = "all",
) -> OrderFilters:
    return OrderFilters(
        q=q,
        status=status,
        fulfilment_state=fulfilment_state,
        party_id=party_id,
        source_quote_id=source_quote_id,
        scope=scope,
    )  # type: ignore[arg-type]


Filters = Annotated[OrderFilters, Depends(_filters)]


@router.get("/sales-orders", openapi_extra=requires(READ))
def list_sales_orders(
    actor: Actor, filters: Filters, limit: Limit = 50, offset: Offset = 0
) -> Page[SalesOrderSummary]:
    """Orders within the actor's read scope; filters apply before paging."""
    return service.list_orders(actor, filters, limit=limit, offset=offset)


@router.get("/sales-orders/lookup", openapi_extra=requires(READ))
def get_sales_order_by_number(
    actor: Actor, order_number: Annotated[str, Query(max_length=20)]
) -> SalesOrderDetail:
    return service.get_order_by_number(actor, order_number)


@router.post("/sales-orders/convert", openapi_extra=requires("orders.sales_order.create"))
def convert_quote_to_order(
    actor: Actor, body: ConvertRequest, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ConversionResult:
    """Convert a won quote's accepted revision into an order: idempotent under concurrency and retries (one order per
    quote; a repeat answers ``created: false`` with the same order)."""
    out = _run(
        actor,
        response,
        f"orders.convert:{body.quote_id}",
        body,
        lambda uow: service.convert_quote_command(uow, body.quote_id),
        ConversionResult,
    )
    response.status_code = 201 if out.created else 200
    return out


@router.get("/sales-orders/by-quote/{quote_id}", openapi_extra=requires(READ))
def get_sales_order_for_quote(actor: Actor, quote_id: uuid.UUID) -> SalesOrderSummary | None:
    """The order converted from a quote (null when none or not visible): the quote workspace's link."""
    with UnitOfWork(actor) as uow:
        order = service.order_for_quote(uow, quote_id)
        if order is None:
            return None
        return SalesOrderSummary.model_validate(service.detail(uow, order).model_dump())


@router.get("/sales-orders/{order_id}", openapi_extra=requires(READ))
def get_sales_order(actor: Actor, order_id: uuid.UUID) -> SalesOrderDetail:
    """Detail with lines (ordered, reserved, delivered, returned, cancelled, remaining), reservations, documents,
    history, ``capabilities`` and ``allowed_transitions``."""
    return service.get_order(actor, order_id)


@router.patch("/sales-orders/{order_id}", openapi_extra=requires(UPDATE))
def update_sales_order(
    actor: Actor,
    order_id: uuid.UUID,
    body: OrderUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> SalesOrderDetail:
    """Logistics fields only (dates, warehouse, ship-to); commercial figures never change on an order."""
    return _run(
        actor,
        response,
        f"orders.update:{order_id}",
        body,
        lambda uow: service.detail(uow, service.update_order(uow, order_id, body)),
        SalesOrderDetail,
    )


@router.post("/sales-orders/{order_id}/transitions", openapi_extra=requires(TRANSITION))
def transition_sales_order(
    actor: Actor,
    order_id: uuid.UUID,
    body: OrderTransition,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> SalesOrderDetail:
    """``confirm``, ``hold`` (reason), ``release_hold``, ``cancel`` (reason; releases reservations; refused once anything
    was delivered). Anything else is 409 ``invalid_transition`` with ``allowed_transitions``."""
    return _run(
        actor,
        response,
        f"orders.transition:{order_id}",
        body,
        lambda uow: service.detail(uow, service.transition_order(uow, order_id, body)),
        SalesOrderDetail,
    )


@router.post("/sales-orders/{order_id}/lines/{line_id}/cancel", openapi_extra=requires(TRANSITION))
def cancel_sales_order_line(
    actor: Actor,
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineCancel,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> SalesOrderDetail:
    """Cancel (part of) a line's remaining quantity with a reason; reservations beyond the new need are released."""
    return _run(
        actor,
        response,
        f"orders.cancel_line:{line_id}",
        body,
        lambda uow: service.detail(uow, service.cancel_line(uow, order_id, line_id, body)),
        SalesOrderDetail,
    )


@router.post("/sales-orders/{order_id}/reserve", openapi_extra=requires("inventory.stock.reserve"))
def reserve_sales_order(
    actor: Actor,
    order_id: uuid.UUID,
    body: ReserveRequest,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReserveResponse:
    """Reserve the unreserved remainder of the stock lines (``partial`` or ``all_or_nothing``); never oversells; a
    shortfall is reported per line and emitted as ``inventory.reservation.shortfall_detected``."""
    return _run(
        actor,
        response,
        f"orders.reserve:{order_id}",
        body,
        lambda uow: service.reserve_order(uow, order_id, body),
        ReserveResponse,
    )


@router.post(
    "/sales-orders/{order_id}/release-reservations", openapi_extra=requires("inventory.stock.reserve")
)
def release_sales_order_reservations(
    actor: Actor,
    order_id: uuid.UUID,
    body: ReleaseRequest,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> SalesOrderDetail:
    return _run(
        actor,
        response,
        f"orders.release:{order_id}",
        body,
        lambda uow: service.detail(uow, service.release_order_reservations(uow, order_id, body)),
        SalesOrderDetail,
    )


@router.post(
    "/sales-orders/{order_id}/challans", status_code=201, openapi_extra=requires("challans.challan.create")
)
def create_challan_for_sales_order(
    actor: Actor,
    order_id: uuid.UUID,
    body: ChallanFromOrder,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanCreated:
    """A draft Outward challan to the customer with the reserved (or chosen) quantities, linked to the order lines;
    issuing it is the one stock movement and records the delivery."""

    def make(uow: UnitOfWork) -> ChallanCreated:
        challan_id = service.create_challan_for_order(uow, order_id, body)
        return ChallanCreated(challan_id=challan_id, path=f"/operations/challans/{challan_id}")

    return _run(actor, response, f"orders.challan:{order_id}", body, make, ChallanCreated)


@router.get("/sales-orders/{order_id}/impact-preview", openapi_extra=requires(READ))
def preview_sales_order_impact(actor: Actor, order_id: uuid.UUID) -> ImpactPreview:
    """Read-only: per line what a reservation would get now and the shortfall."""
    with UnitOfWork(actor) as uow:
        return service.impact_preview(uow, order_id)
