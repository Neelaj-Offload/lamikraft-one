"""Logistics API (``/api/v1/logistics``): packing lists, shipments with cutoffs, tracking references, container
profiles and load suggestions. Commands accept ``Idempotency-Key``. Records outside the actor's scope are 404."""

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
from app.modules.logistics import packing_lists, shipments
from app.modules.logistics.enums import PackingListStatus, ShipmentStatus
from app.modules.logistics.schemas import (
    ContainerProfileIn,
    ContainerProfileRead,
    LineOverride,
    LoadSuggestion,
    LoadSuggestionRequest,
    PackingListCreate,
    PackingListDetail,
    PackingListSummary,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentSummary,
    ShipmentTransition,
    ShipmentUpdate,
    TrackingRefIn,
    Versioned,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/logistics", tags=["logistics"])
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
PL_READ, SH_READ = "logistics.packing_list.read", "logistics.shipment.read"


def _run[T: BaseModel](
    actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T], model: type[T]
) -> T:
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(uow, operation, body, lambda: fn(uow), model)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out


class ProfileList(BaseModel):
    items: list[ContainerProfileRead]


# ---- packing lists ---------------------------------------------------------------------------------------------
@router.get("/packing-lists", openapi_extra=requires(PL_READ))
def list_packing_lists(
    actor: Actor,
    status: Annotated[list[PackingListStatus] | None, Query()] = None,
    sales_order_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[PackingListSummary]:
    with UnitOfWork(actor) as uow:
        return packing_lists.list_packing_lists(
            uow,
            status=[s.value for s in status or []] or None,
            sales_order_id=sales_order_id,
            limit=limit,
            offset=offset,
        )


@router.post("/packing-lists", status_code=201, openapi_extra=requires("logistics.packing_list.create"))
def create_packing_list(
    actor: Actor, body: PackingListCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PackingListDetail:
    """From an order the actor can read: cartons, inner packs, CBM and weights computed server-side (Decimal)."""
    return _run(
        actor,
        response,
        f"logistics.packing_list.create:{body.sales_order_id}",
        body,
        lambda uow: packing_lists.detail(uow, packing_lists.create_packing_list(uow, body)),
        PackingListDetail,
    )


@router.get("/packing-lists/{packing_list_id}", openapi_extra=requires(PL_READ))
def get_packing_list(actor: Actor, packing_list_id: uuid.UUID) -> PackingListDetail:
    with UnitOfWork(actor) as uow:
        return packing_lists.get_packing_list(uow, packing_list_id)


@router.post(
    "/packing-lists/{packing_list_id}/refresh", openapi_extra=requires("logistics.packing_list.update")
)
def refresh_packing_list(
    actor: Actor,
    packing_list_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PackingListDetail:
    """Re-read the current packaging (clears the stale flag)."""
    return _run(
        actor,
        response,
        f"logistics.packing_list.refresh:{packing_list_id}",
        body,
        lambda uow: packing_lists.detail(
            uow, packing_lists.refresh(uow, packing_list_id, body.expected_version)
        ),
        PackingListDetail,
    )


@router.post(
    "/packing-lists/{packing_list_id}/lines/{line_id}/override",
    openapi_extra=requires("logistics.packing_list.update"),
)
def override_packing_line(
    actor: Actor,
    packing_list_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineOverride,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PackingListDetail:
    return _run(
        actor,
        response,
        f"logistics.packing_list.override:{line_id}",
        body,
        lambda uow: packing_lists.detail(
            uow, packing_lists.override_line(uow, packing_list_id, line_id, body)
        ),
        PackingListDetail,
    )


@router.post(
    "/packing-lists/{packing_list_id}/finalise", openapi_extra=requires("logistics.packing_list.transition")
)
def finalise_packing_list(
    actor: Actor,
    packing_list_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PackingListDetail:
    """Blocked while stale or while a line lacks packaging data (409 with the line numbers)."""
    return _run(
        actor,
        response,
        f"logistics.packing_list.finalise:{packing_list_id}",
        body,
        lambda uow: packing_lists.detail(
            uow, packing_lists.finalise(uow, packing_list_id, body.expected_version)
        ),
        PackingListDetail,
    )


@router.post(
    "/packing-lists/{packing_list_id}/cancel", openapi_extra=requires("logistics.packing_list.transition")
)
def cancel_packing_list(
    actor: Actor,
    packing_list_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PackingListDetail:
    return _run(
        actor,
        response,
        f"logistics.packing_list.cancel:{packing_list_id}",
        body,
        lambda uow: packing_lists.detail(
            uow, packing_lists.cancel(uow, packing_list_id, body.expected_version)
        ),
        PackingListDetail,
    )


# ---- shipments ----------------------------------------------------------------------------------------------------
@router.get("/shipments", openapi_extra=requires(SH_READ))
def list_shipments(
    actor: Actor,
    status: Annotated[list[ShipmentStatus] | None, Query()] = None,
    sales_order_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ShipmentSummary]:
    """Ordered by cutoff (soonest first)."""
    with UnitOfWork(actor) as uow:
        return shipments.list_shipments(
            uow,
            status=[s.value for s in status or []] or None,
            sales_order_id=sales_order_id,
            q=q,
            limit=limit,
            offset=offset,
        )


@router.post("/shipments", status_code=201, openapi_extra=requires("logistics.shipment.create"))
def create_shipment(
    actor: Actor, body: ShipmentCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ShipmentDetail:
    """A planned shipment; a cutoff (company time) schedules the hard-due dispatch task."""
    return _run(
        actor,
        response,
        "logistics.shipment.create",
        body,
        lambda uow: shipments.detail(uow, shipments.create_shipment(uow, body)),
        ShipmentDetail,
    )


@router.get("/shipments/{shipment_id}", openapi_extra=requires(SH_READ))
def get_shipment(actor: Actor, shipment_id: uuid.UUID) -> ShipmentDetail:
    with UnitOfWork(actor) as uow:
        return shipments.get_shipment(uow, shipment_id)


@router.patch("/shipments/{shipment_id}", openapi_extra=requires("logistics.shipment.update"))
def update_shipment(
    actor: Actor,
    shipment_id: uuid.UUID,
    body: ShipmentUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ShipmentDetail:
    """Before dispatch: link the challan / packing list, transporter, planned date, cutoff (re-schedules)."""
    return _run(
        actor,
        response,
        f"logistics.shipment.update:{shipment_id}",
        body,
        lambda uow: shipments.detail(uow, shipments.update_shipment(uow, shipment_id, body)),
        ShipmentDetail,
    )


@router.post("/shipments/{shipment_id}/transitions", openapi_extra=requires("logistics.shipment.transition"))
def transition_shipment(
    actor: Actor,
    shipment_id: uuid.UUID,
    body: ShipmentTransition,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ShipmentDetail:
    """``book``, ``dispatch`` (issues the linked draft challan: the one stock movement), ``in_transit``, ``deliver``
    (evidence required), ``record_exception`` / ``resolve_exception``, ``cancel`` (before dispatch, reason)."""
    return _run(
        actor,
        response,
        f"logistics.shipment.transition:{shipment_id}",
        body,
        lambda uow: shipments.detail(uow, shipments.transition(uow, shipment_id, body)),
        ShipmentDetail,
    )


@router.post("/shipments/{shipment_id}/tracking-refs", openapi_extra=requires("logistics.shipment.update"))
def add_tracking_ref(
    actor: Actor,
    shipment_id: uuid.UUID,
    body: TrackingRefIn,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ShipmentDetail:
    return _run(
        actor,
        response,
        f"logistics.shipment.tracking:{shipment_id}",
        body,
        lambda uow: shipments.detail(uow, shipments.add_tracking_ref(uow, shipment_id, body)),
        ShipmentDetail,
    )


# ---- container profiles and load suggestions ------------------------------------------------------------------------
@router.get(
    "/container-profiles",
    openapi_extra=requires("logistics.load_plan.run", "logistics.container_profile.manage"),
)
def list_container_profiles(actor: Actor) -> ProfileList:
    with UnitOfWork(actor) as uow:
        return ProfileList(items=shipments.list_profiles(uow))


@router.post("/container-profiles", openapi_extra=requires("logistics.container_profile.manage"))
def save_container_profile(
    actor: Actor, body: ContainerProfileIn, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ContainerProfileRead:
    """Create or update a profile by code (entered volume, payload and fill factor; nothing is assumed)."""
    return _run(
        actor,
        response,
        f"logistics.container_profile:{body.code}",
        body,
        lambda uow: shipments.save_profile(uow, body),
        ContainerProfileRead,
    )


@router.post("/load-suggestions", openapi_extra=requires("logistics.load_plan.run"))
def suggest_load(actor: Actor, body: LoadSuggestionRequest) -> LoadSuggestion:
    """Read-only, deterministic: first-fit decreasing by carton CBM, whole cartons, volume and payload only."""
    with UnitOfWork(actor) as uow:
        return shipments.suggest_load(uow, body)
