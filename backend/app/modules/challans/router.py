"""Challans API (``/api/v1/challans/challans``): list, summary, create, header, lines, transitions, duplicate, revisions,
the PDF, the print view data and the CSV export. Routers never import models; services enforce scope and state."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.challans import documents, service
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanDetail,
    ChallanDuplicate,
    ChallanFilters,
    ChallanLineAdd,
    ChallanLineUpdate,
    ChallanPrint,
    ChallanRevisionRead,
    ChallanRevisionSummary,
    ChallanStatus,
    ChallanSummary,
    ChallanSummaryRow,
    ChallanTransition,
    ChallanType,
    ChallanUpdate,
    DestinationType,
    Period,
    ReturnType,
)
from app.modules.challans.transitions import transition_challan_command
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/challans", tags=["challans"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
READ, UPDATE, EXPORT = "challans.challan.read", "challans.challan.update", "challans.challan.export"


def _replayed(response: Response, replayed: bool) -> None:
    if replayed:
        response.headers[REPLAYED] = "true"


def _filters(
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Tokens matched against number, destination, shipping name and reference",
        ),
    ] = None,
    status: Annotated[list[ChallanStatus] | None, Query()] = None,
    challan_type: Annotated[list[ChallanType] | None, Query()] = None,
    return_type: ReturnType | None = None,
    destination_type: Annotated[list[DestinationType] | None, Query()] = None,
    party_id: uuid.UUID | None = None,
    destination: Annotated[str | None, Query(max_length=200)] = None,
    period: Period | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    pending_returnable: bool = False,
    scope: Annotated[str, Query(pattern=r"^(mine|all)$")] = "all",
    include_deleted: bool = False,
) -> ChallanFilters:
    return ChallanFilters(
        q=q,
        status=status,
        challan_type=challan_type,
        return_type=return_type,
        destination_type=destination_type,
        party_id=party_id,
        destination=destination,
        period=period,
        date_from=date_from,
        date_to=date_to,
        pending_returnable=pending_returnable,
        scope=scope,
        include_deleted=include_deleted,  # type: ignore[arg-type]
    )


Filters = Annotated[ChallanFilters, Depends(_filters)]


def _pdf_response(pdf: bytes, filename: str, etag: str | None) -> Response:
    headers = {
        "Content-Disposition": f"inline; filename=\"{filename}\"; filename*=UTF-8''{urlquote(filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "sandbox",
        "X-Document-SHA256": documents.sha256_of(pdf),
    }
    if etag:
        headers["ETag"] = f'"{etag}"'
    return Response(content=pdf, media_type="application/pdf", headers=headers)


@router.get("/challans", openapi_extra=requires(READ))
def list_challans(
    actor: Actor, filters: Filters, limit: Limit = 50, offset: Offset = 0
) -> Page[ChallanSummaryRow]:
    """Challans within the actor's read scope (``scope=mine`` narrows to the actor's own); filters apply before paging."""
    return service.list_challans(actor, filters, limit=limit, offset=offset)


@router.get("/challans/summary", openapi_extra=requires(READ))
def get_challan_summary(actor: Actor, filters: Filters) -> ChallanSummary:
    """The summary cards (total, this week, this month, pending returnable, by type / destination / status) over the
    same filters and scope as the list; quantities are totals per unit and never added across units."""
    return service.summary(actor, filters)


@router.get(
    "/challans/export.csv",
    openapi_extra=requires(EXPORT),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_challans_csv(actor: Actor, filters: Filters) -> Response:
    """One row per challan the actor may export (spreadsheet-inert text, UTF-8 with BOM)."""
    with UnitOfWork(actor) as uow:
        rows, lines = service.export_rows(uow, filters)
        body = documents.csv_bytes(uow, rows, lines)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="challans.csv"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/challans/lookup", openapi_extra=requires(READ))
def get_challan_by_number(
    actor: Actor, challan_number: Annotated[str, Query(min_length=5, max_length=20)]
) -> ChallanDetail:
    return service.get_challan_by_number(actor, challan_number)


@router.post("/challans", status_code=201, openapi_extra=requires("challans.challan.create"))
def create_challan(
    actor: Actor, body: ChallanCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ChallanDetail:
    """Create a draft; ``DC-YYYY-NNNN`` is allocated atomically (yearly by the challan date) and never reused."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_challan_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/challans/{challan_id}", openapi_extra=requires(READ))
def get_challan(actor: Actor, challan_id: uuid.UUID) -> ChallanDetail:
    """Detail with lines, return links, history, ``capabilities`` and ``allowed_transitions``."""
    return service.get_challan(actor, challan_id)


@router.patch("/challans/{challan_id}", openapi_extra=requires(UPDATE))
def update_challan(
    actor: Actor,
    challan_id: uuid.UUID,
    body: ChallanUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """Header fields of a draft (dirty fields plus ``expected_version``; 409 ``version_conflict`` when stale,
    409 ``challan_not_editable`` once issued)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_challan_command(uow, challan_id, body)
    _replayed(response, replayed)
    return detail


@router.delete("/challans/{challan_id}", openapi_extra=requires("challans.challan.delete"))
def delete_challan(
    actor: Actor,
    challan_id: uuid.UUID,
    response: Response,
    expected_version: int | None = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """Soft-delete a draft (admin template only); the number stays reserved."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.delete_challan_command(uow, challan_id, expected_version)
    _replayed(response, replayed)
    return detail


@router.post("/challans/{challan_id}/lines", status_code=201, openapi_extra=requires(UPDATE))
def create_challan_line(
    actor: Actor,
    challan_id: uuid.UUID,
    body: ChallanLineAdd,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """Add a catalog line (code, name, HSN/SAC and unit from the product), a custom line or a manual line."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.add_line_command(uow, challan_id, body)
    _replayed(response, replayed)
    return detail


@router.patch("/challans/{challan_id}/lines/{line_id}", openapi_extra=requires(UPDATE))
def update_challan_line(
    actor: Actor,
    challan_id: uuid.UUID,
    line_id: uuid.UUID,
    body: ChallanLineUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_line_command(uow, challan_id, line_id, body)
    _replayed(response, replayed)
    return detail


@router.delete("/challans/{challan_id}/lines/{line_id}", openapi_extra=requires(UPDATE))
def delete_challan_line(
    actor: Actor,
    challan_id: uuid.UUID,
    line_id: uuid.UUID,
    response: Response,
    expected_version: int | None = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """Remove a line; the remaining lines are renumbered in the same transaction."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.remove_line_command(uow, challan_id, line_id, expected_version)
    _replayed(response, replayed)
    return detail


@router.post(
    "/challans/{challan_id}/transitions",
    openapi_extra=requires(
        "challans.challan.transition", "challans.challan.issue", "challans.challan.reverse"
    ),
)
def transition_challan(
    actor: Actor,
    challan_id: uuid.UUID,
    body: ChallanTransition,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """Apply a state-machine action (issue, close, cancel). An action that is unknown or not allowed in the current
    status is 409 ``invalid_transition`` with ``allowed_transitions``. ``issue`` and the cancel of an issued challan
    require ``Idempotency-Key``."""
    with UnitOfWork(actor) as uow:
        detail, replayed = transition_challan_command(uow, challan_id, body)
    _replayed(response, replayed)
    return detail


@router.post(
    "/challans/{challan_id}/duplicate", status_code=201, openapi_extra=requires("challans.challan.create")
)
def duplicate_challan(
    actor: Actor,
    challan_id: uuid.UUID,
    body: ChallanDuplicate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChallanDetail:
    """A new draft with a new number copying the header and the lines."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.duplicate_challan_command(uow, challan_id, body)
    _replayed(response, replayed)
    return detail


@router.get("/challans/{challan_id}/revisions", openapi_extra=requires(READ))
def list_challan_revisions(actor: Actor, challan_id: uuid.UUID) -> list[ChallanRevisionSummary]:
    return service.list_revisions(actor, challan_id)


@router.get("/challans/{challan_id}/revisions/{revision_no}", openapi_extra=requires(READ))
def get_challan_revision(actor: Actor, challan_id: uuid.UUID, revision_no: int) -> ChallanRevisionRead:
    return service.get_revision(actor, challan_id, revision_no)


@router.get("/challans/{challan_id}/print", openapi_extra=requires(EXPORT))
def get_challan_print(actor: Actor, challan_id: uuid.UUID) -> ChallanPrint:
    """Everything the browser print view shows: the same data the PDF renders from; internal notes are never included."""
    with UnitOfWork(actor) as uow:
        challan, lines = service.exportable(uow, challan_id)
        snapshot, _digest = documents.current_snapshot(uow, challan, lines)
        return documents.print_data(snapshot)


@router.get(
    "/challans/{challan_id}/document.pdf",
    openapi_extra=requires(EXPORT),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_challan_pdf(actor: Actor, challan_id: uuid.UUID) -> Response:
    """The current document: the issued revision rendered deterministically from its snapshot, or a DRAFT-watermarked
    live render of a draft (inline, nosniff, sandboxed)."""
    with UnitOfWork(actor) as uow:
        challan, lines = service.exportable(uow, challan_id)
        snapshot, digest = documents.current_snapshot(uow, challan, lines)
    pdf = documents.render_pdf(snapshot)
    return _pdf_response(pdf, documents.document_filename(snapshot), digest)


@router.get(
    "/challans/{challan_id}/revisions/{revision_no}/document.pdf",
    openapi_extra=requires(EXPORT),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_challan_revision_pdf(actor: Actor, challan_id: uuid.UUID, revision_no: int) -> Response:
    with UnitOfWork(actor) as uow:
        challan, _lines = service.exportable(uow, challan_id)
        row = service.revision_row(uow, challan, revision_no)
        snapshot, digest = dict(row.snapshot), row.document_sha256
    pdf = documents.render_pdf(snapshot)
    return _pdf_response(pdf, documents.document_filename(snapshot), digest)
