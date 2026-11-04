"""Quality API (``/api/v1/quality``): inspections of stock in QC hold. Deciding records the checklist and posts the
accepted quantity to stock and the rejected quantity to the rejected location (one posting per inspection)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.inventory.commands import idempotent
from app.modules.quality import service
from app.modules.quality.enums import InspectionStatus
from app.modules.quality.schemas import (
    InspectionCreate,
    InspectionDecision,
    InspectionDetail,
    InspectionSummary,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/quality", tags=["quality"])
READ, CREATE = "quality.inspection.read", "quality.inspection.create"


@router.get("/inspections", openapi_extra=requires(READ))
def list_inspections(
    actor: Actor,
    status: Annotated[list[InspectionStatus] | None, Query()] = None,
    warehouse_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[InspectionSummary]:
    with UnitOfWork(actor) as uow:
        return service.list_inspections(
            uow,
            status=[s.value for s in status or []] or None,
            warehouse_id=warehouse_id,
            source_id=source_id,
            limit=limit,
            offset=offset,
        )


@router.post("/inspections", status_code=201, openapi_extra=requires(CREATE))
def create_inspection(
    actor: Actor, body: InspectionCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> InspectionDetail:
    """Inspect stock that already sits in a warehouse's QC hold (e.g. a customer return)."""
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(
            uow,
            "quality.inspection.create",
            body,
            lambda: service.detail(uow, service.create_inspection(uow, body)),
            InspectionDetail,
        )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out


@router.get("/inspections/{inspection_id}", openapi_extra=requires(READ))
def get_inspection(actor: Actor, inspection_id: uuid.UUID) -> InspectionDetail:
    with UnitOfWork(actor) as uow:
        return service.get_inspection(uow, inspection_id)


@router.post("/inspections/{inspection_id}/decide", openapi_extra=requires(CREATE))
def decide_inspection(
    actor: Actor,
    inspection_id: uuid.UUID,
    body: InspectionDecision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InspectionDetail:
    """Accepted + rejected = the inspected quantity; rejects need a reason code and a failed check or findings."""
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(
            uow,
            f"quality.inspection.decide:{inspection_id}",
            body,
            lambda: service.detail(uow, service.decide_inspection(uow, inspection_id, body)),
            InspectionDetail,
        )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out
