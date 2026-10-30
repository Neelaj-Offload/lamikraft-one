"""Sales API (``/api/v1/sales``): quotes, lines, transitions, revisions and their PDF, history, engine preview,
enquiries and customer messages. Routers never import models; services enforce scope and state."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.sales import service
from app.modules.sales.schemas import (
    CustomerMessageCreate,
    CustomerMessageFilters,
    CustomerMessageRead,
    CustomerMessageUpdate,
    EnquiryCreate,
    EnquiryFilters,
    EnquiryRead,
    EnquiryStatus,
    EnquiryUpdate,
    MarkReplied,
    MessageStatus,
    QuoteCreate,
    QuoteDetail,
    QuoteFilters,
    QuoteHistoryRead,
    QuoteLineCreate,
    QuoteLineUpdate,
    QuotePreviewIn,
    QuotePreviewOut,
    QuoteRevisionRead,
    QuoteRevisionSummary,
    QuoteStatus,
    QuoteSummary,
    QuoteTransition,
    QuoteUpdate,
    RefreshSnapshots,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/sales", tags=["sales"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


def _replayed(response: Response, replayed: bool) -> None:
    if replayed:
        response.headers[REPLAYED] = "true"


# =====================================================================================================
# quotes
# =====================================================================================================
def _quote_filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against number, customer name and country")] = None,
    status: Annotated[list[QuoteStatus] | None, Query()] = None,
    scope: Annotated[str, Query(pattern=r"^(mine|all)$")] = "all",
    owner_user_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> QuoteFilters:
    return QuoteFilters(q=q, status=status, scope=scope, owner_user_id=owner_user_id, party_id=party_id,  # type: ignore[arg-type]
                        include_deleted=include_deleted)


@router.get("/quotes", openapi_extra=requires("sales.quote.read"))
def list_quotes(
    actor: Actor, filters: Annotated[QuoteFilters, Depends(_quote_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[QuoteSummary]:
    """Quotes within the actor's read scope (``scope=mine`` narrows to the actor's own); filters apply before paging."""
    return service.list_quotes(actor, filters, limit=limit, offset=offset)


@router.get("/quotes/status-counts", openapi_extra=requires("sales.quote.read"))
def get_quote_status_counts(actor: Actor, filters: Annotated[QuoteFilters, Depends(_quote_filters)]) -> dict[str, int]:
    return service.status_counts(actor, filters)


@router.post("/quotes/calculate", openapi_extra=requires("pricing.price.read"))
def calculate_quote_preview(actor: Actor, body: QuotePreviewIn) -> QuotePreviewOut:
    """Run the commercial engine on proposed lines without persisting anything (live totals in the UI)."""
    return service.calculate_preview(actor, body)


@router.post("/quotes", status_code=201, openapi_extra=requires("sales.quote.create"))
def create_quote(actor: Actor, body: QuoteCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> QuoteDetail:
    """Create a draft; the number ``{brand}-QT-YYYY-NNNN`` is allocated atomically and never reused."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_quote_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/quotes/lookup", openapi_extra=requires("sales.quote.read"))
def get_quote_by_number(actor: Actor, quote_number: Annotated[str, Query(min_length=5, max_length=30)]) -> QuoteDetail:
    return service.get_quote_by_number(actor, quote_number)


@router.get("/quotes/{quote_id}", openapi_extra=requires("sales.quote.read"))
def get_quote(actor: Actor, quote_id: uuid.UUID) -> QuoteDetail:
    """Detail with lines, snapshots, the persisted totals, ``capabilities`` and ``allowed_transitions``."""
    return service.get_quote(actor, quote_id)


@router.patch("/quotes/{quote_id}", openapi_extra=requires("sales.quote.update"))
def update_quote(
    actor: Actor, quote_id: uuid.UUID, body: QuoteUpdate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Header fields of a draft (dirty fields plus ``expected_version``; 409 ``version_conflict`` when stale)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_quote_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.delete("/quotes/{quote_id}", openapi_extra=requires("sales.quote.delete"))
def delete_quote(
    actor: Actor, quote_id: uuid.UUID, response: Response, expected_version: int | None = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> QuoteDetail:
    """Soft-delete a never-issued draft (``sales.quote.delete``); the number stays reserved."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.delete_quote_command(uow, quote_id, expected_version)
    _replayed(response, replayed)
    return detail


@router.post("/quotes/{quote_id}/lines", status_code=201, openapi_extra=requires("sales.quote.update"))
def create_quote_line(
    actor: Actor, quote_id: uuid.UUID, body: QuoteLineCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Add a catalog line (priced through the price lists, snapshots taken) or a manual line; totals are recomputed."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.add_line_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.patch("/quotes/{quote_id}/lines/{line_id}", openapi_extra=requires("sales.quote.update"))
def update_quote_line(
    actor: Actor, quote_id: uuid.UUID, line_id: uuid.UUID, body: QuoteLineUpdate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> QuoteDetail:
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_line_command(uow, quote_id, line_id, body)
    _replayed(response, replayed)
    return detail


@router.delete("/quotes/{quote_id}/lines/{line_id}", openapi_extra=requires("sales.quote.update"))
def delete_quote_line(
    actor: Actor, quote_id: uuid.UUID, line_id: uuid.UUID, response: Response, expected_version: int | None = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> QuoteDetail:
    """Remove a line; the remaining lines are renumbered and totals recomputed in the same transaction."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.remove_line_command(uow, quote_id, line_id, expected_version)
    _replayed(response, replayed)
    return detail


@router.post("/quotes/{quote_id}/refresh-snapshots", openapi_extra=requires("sales.quote.update"))
def refresh_quote_snapshots(
    actor: Actor, quote_id: uuid.UUID, body: RefreshSnapshots, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Explicitly re-read the catalogue and current prices into the catalog lines of a draft."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.refresh_snapshots_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.post("/quotes/{quote_id}/transitions", openapi_extra=requires("sales.quote.transition", "sales.quote.issue"))
def transition_quote(
    actor: Actor, quote_id: uuid.UUID, body: QuoteTransition, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Apply a state-machine action (submit_review, withdraw_review, mark_sent, mark_won, mark_lost, cancel).

    An action that is unknown or not allowed in the current status is 409 ``invalid_transition`` with
    ``allowed_transitions``. ``mark_sent``, ``mark_won``, ``mark_lost`` and ``cancel`` require ``Idempotency-Key``."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.transition_quote_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.get("/quotes/{quote_id}/history", openapi_extra=requires("sales.quote.read"))
def list_quote_history(actor: Actor, quote_id: uuid.UUID) -> list[QuoteHistoryRead]:
    return service.list_status_history(actor, quote_id)


@router.get("/quotes/{quote_id}/revisions", openapi_extra=requires("sales.quote.read"))
def list_quote_revisions(actor: Actor, quote_id: uuid.UUID) -> list[QuoteRevisionSummary]:
    return service.list_revisions(actor, quote_id)


@router.get("/quotes/{quote_id}/revisions/{revision_no}", openapi_extra=requires("sales.quote.read"))
def get_quote_revision(actor: Actor, quote_id: uuid.UUID, revision_no: int) -> QuoteRevisionRead:
    return service.get_revision(actor, quote_id, revision_no)


@router.get(
    "/quotes/{quote_id}/revisions/{revision_no}/document.pdf",
    openapi_extra=requires("sales.quote.export"),
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_quote_revision_pdf(actor: Actor, quote_id: uuid.UUID, revision_no: int) -> Response:
    """The issued revision as PDF, rendered deterministically from its snapshot (inline, nosniff, sandboxed)."""
    snapshot, expected = service.revision_document(actor, quote_id, revision_no)
    pdf = service.render_quote_pdf(snapshot)
    filename = service.document_filename(snapshot)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{filename}\"; filename*=UTF-8''{urlquote(filename)}",
            # X-Content-Type-Options: nosniff and Cache-Control: no-store come from the request-context middleware
            # (it appends them to every response; setting them here too duplicated the headers)
            "Content-Security-Policy": "sandbox",
            "ETag": f'"{expected}"',
            "X-Document-SHA256": service.sha256_of(pdf),
        },
    )


# =====================================================================================================
# enquiries
# =====================================================================================================
def _enquiry_filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[EnquiryStatus] | None, Query()] = None,
    owner_user_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> EnquiryFilters:
    return EnquiryFilters(q=q, status=status, owner_user_id=owner_user_id, party_id=party_id)


@router.get("/enquiries", openapi_extra=requires("sales.enquiry.read"))
def list_enquiries(
    actor: Actor, filters: Annotated[EnquiryFilters, Depends(_enquiry_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[EnquiryRead]:
    return service.list_enquiries(actor, filters, limit=limit, offset=offset)


@router.post("/enquiries", status_code=201, openapi_extra=requires("sales.enquiry.create"))
def create_enquiry(actor: Actor, body: EnquiryCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> EnquiryRead:
    """Record an enquiry; ``ENQ-YYYY-NNNN`` is allocated atomically (yearly reset)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_enquiry_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/enquiries/{enquiry_id}", openapi_extra=requires("sales.enquiry.read"))
def get_enquiry(actor: Actor, enquiry_id: uuid.UUID) -> EnquiryRead:
    return service.get_enquiry(actor, enquiry_id)


@router.patch("/enquiries/{enquiry_id}", openapi_extra=requires("sales.enquiry.update"))
def update_enquiry(
    actor: Actor, enquiry_id: uuid.UUID, body: EnquiryUpdate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> EnquiryRead:
    """Dirty fields plus ``expected_version``; ``owner_user_id`` assigns, ``status=closed`` with ``outcome_code`` closes."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_enquiry_command(uow, enquiry_id, body)
    _replayed(response, replayed)
    return detail


# =====================================================================================================
# customer messages
# =====================================================================================================
def _message_filters(
    status: Annotated[list[MessageStatus] | None, Query()] = None,
    assignee_user_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    quote_id: uuid.UUID | None = None,
) -> CustomerMessageFilters:
    return CustomerMessageFilters(status=status, assignee_user_id=assignee_user_id, party_id=party_id, quote_id=quote_id)


@router.get("/customer-messages", openapi_extra=requires("sales.customer_message.read"))
def list_customer_messages(
    actor: Actor, filters: Annotated[CustomerMessageFilters, Depends(_message_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[CustomerMessageRead]:
    return service.list_customer_messages(actor, filters, limit=limit, offset=offset)


@router.post("/customer-messages", status_code=201, openapi_extra=requires("sales.customer_message.create"))
def create_customer_message(
    actor: Actor, body: CustomerMessageCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CustomerMessageRead:
    """Record an inbound customer message (the body is external content and never becomes a rule fact)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_customer_message_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/customer-messages/{message_id}", openapi_extra=requires("sales.customer_message.read"))
def get_customer_message(actor: Actor, message_id: uuid.UUID) -> CustomerMessageRead:
    return service.get_customer_message(actor, message_id)


@router.patch("/customer-messages/{message_id}", openapi_extra=requires("sales.customer_message.update"))
def update_customer_message(
    actor: Actor, message_id: uuid.UUID, body: CustomerMessageUpdate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CustomerMessageRead:
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_customer_message_command(uow, message_id, body)
    _replayed(response, replayed)
    return detail


@router.post("/customer-messages/{message_id}/replied", openapi_extra=requires("sales.customer_message.update"))
def transition_customer_message(
    actor: Actor, message_id: uuid.UUID, body: MarkReplied, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CustomerMessageRead:
    """Mark a message replied (``reply_ref_type``/``reply_ref_id`` point at the reply); emits ``replied``."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.mark_replied_command(uow, message_id, body)
    _replayed(response, replayed)
    return detail
