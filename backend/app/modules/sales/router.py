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
from app.modules.sales.configurator import ConfiguratorRequest, ConfiguratorResult
from app.modules.sales.schemas import (
    ChangeOwner,
    CostingCreate,
    CostingRead,
    CurrencyChange,
    CurrencyChangePreview,
    CustomerMessageCreate,
    CustomerMessageFilters,
    CustomerMessageRead,
    CustomerMessageUpdate,
    CustomHistoryRead,
    CustomProductArchive,
    CustomProductCreate,
    CustomProductDetail,
    CustomProductFilters,
    CustomProductStatus,
    CustomProductSummary,
    CustomProductTransition,
    CustomProductUpdate,
    CustomType,
    DuplicateQuote,
    EnquiryCreate,
    EnquiryFilters,
    EnquiryRead,
    EnquiryStatus,
    EnquiryUpdate,
    MarkReplied,
    MessageStatus,
    PromotionRead,
    PromotionRequest,
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
    QuoteSettingsRead,
    QuoteSettingsUpdate,
    QuoteStatus,
    QuoteSummary,
    QuoteTransition,
    QuoteUpdate,
    RefreshSnapshots,
    RestoreRevision,
    RevisionCompare,
    SampleCreate,
    SampleFilters,
    SampleRead,
    SampleStatus,
    SampleTransition,
    SampleUpdate,
    SpecOutcomeIn,
    SpecRevisionCreate,
    SpecRevisionRead,
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
    currency: Annotated[str | None, Query(pattern=r"^(INR|EUR|USD|GBP)$")] = None,
    include_deleted: bool = False,
) -> QuoteFilters:
    return QuoteFilters(q=q, status=status, scope=scope, owner_user_id=owner_user_id, party_id=party_id,  # type: ignore[arg-type]
                        currency=currency, include_deleted=include_deleted)  # type: ignore[arg-type]


def _csv(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{urlquote(filename)}"},
    )


@router.get("/quotes", openapi_extra=requires("sales.quote.read"))
def list_quotes(
    actor: Actor, filters: Annotated[QuoteFilters, Depends(_quote_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[QuoteSummary]:
    """Quotes within the actor's read scope (``scope=mine`` narrows to the actor's own); filters apply before paging."""
    return service.list_quotes(actor, filters, limit=limit, offset=offset)


@router.get(
    "/quotes/export.csv",
    openapi_extra=requires("sales.quote.export"),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_quotes_csv(actor: Actor, filters: Annotated[QuoteFilters, Depends(_quote_filters)]) -> Response:
    """The filtered quote list as CSV, bounded by the actor's export scope (never other owners' quotes for sales)."""
    return _csv(service.export_quotes_csv(actor, filters), "quotes.csv")


@router.get("/quote-settings", openapi_extra=requires("sales.quote.read"))
def get_quote_settings(actor: Actor) -> QuoteSettingsRead:
    """Quote defaults plus previews of the next quote, custom-product and sample numbers (never allocated)."""
    return service.get_quote_settings(actor)


@router.put("/quote-settings", openapi_extra=requires("sales.quote_settings.manage"))
def update_quote_settings(actor: Actor, body: QuoteSettingsUpdate) -> QuoteSettingsRead:
    """Validated write of the quote defaults (``sales.quote_settings.manage``, recent sign-in); 409 when stale."""
    with UnitOfWork(actor) as uow:
        return service.update_quote_settings(uow, body)


@router.get("/quotes/status-counts", openapi_extra=requires("sales.quote.read"))
def get_quote_status_counts(actor: Actor, filters: Annotated[QuoteFilters, Depends(_quote_filters)]) -> dict[str, int]:
    return service.status_counts(actor, filters)


@router.post("/quotes/configurator/resolve", openapi_extra=requires("sales.quote.read"))
def resolve_quote_configurator(actor: Actor, body: ConfiguratorRequest) -> ConfiguratorResult:
    """Search-first product finder for a quote: filters before paging, narrowed facets, ``exact_match``, and each row
    priced for the customer (agreement -> type -> standard, approved FX when needed) with its recommendation."""
    return service.configurator_resolve(actor, body)


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


@router.post(
    "/quotes/{quote_id}/transitions",
    openapi_extra=requires("sales.quote.transition", "sales.quote.issue", "sales.quote.archive", "sales.quote.correct"),
)
def transition_quote(
    actor: Actor, quote_id: uuid.UUID, body: QuoteTransition, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Apply a state-machine action: submit_review, withdraw_review, mark_sent, revise, discard_revision,
    extend_validity, mark_won, mark_lost, cancel, archive, unarchive, correct_status.

    An action that is unknown or not allowed in the current status is 409 ``invalid_transition`` with
    ``allowed_transitions``. Issue-like and closing actions require ``Idempotency-Key``."""
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


@router.get("/quotes/{quote_id}/revisions/compare", openapi_extra=requires("sales.quote.read"))
def compare_quote_revisions(
    actor: Actor, quote_id: uuid.UUID, from_revision_no: Annotated[int, Query(ge=1)],
    to_revision_no: Annotated[int | None, Query(ge=1)] = None,
) -> RevisionCompare:
    """Header, lines by ``line_key`` and totals between two issued revisions (or a revision and the working copy)."""
    return service.compare_revisions(actor, quote_id, from_revision_no, to_revision_no)


@router.post("/quotes/{quote_id}/revisions/{revision_no}/restore", openapi_extra=requires("sales.quote.update", "sales.quote.transition"))
def restore_quote_revision(
    actor: Actor, quote_id: uuid.UUID, revision_no: int, body: RestoreRevision, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> QuoteDetail:
    """Copy an issued revision into the working copy (a sent quote is revised first); issued revisions never change."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.restore_revision_command(uow, quote_id, revision_no, body)
    _replayed(response, replayed)
    return detail


@router.post("/quotes/{quote_id}/duplicate", status_code=201, openapi_extra=requires("sales.quote.create"))
def duplicate_quote(
    actor: Actor, quote_id: uuid.UUID, body: DuplicateQuote, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """A new draft from this quote (or one of its revisions) with real totals and the customer reference cleared."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.duplicate_quote_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.get("/quotes/{quote_id}/currency-change", openapi_extra=requires("sales.quote.read"))
def preview_quote_currency_change(
    actor: Actor, quote_id: uuid.UUID, to_currency: Annotated[str, Query(pattern=r"^(INR|EUR|USD|GBP)$")]
) -> CurrencyChangePreview:
    """Per line: the new price from a list in that currency, the custom product's own price, or an approved FX rate."""
    return service.preview_currency_change(actor, quote_id, to_currency)


@router.post("/quotes/{quote_id}/currency-change", openapi_extra=requires("sales.quote.update"))
def change_quote_currency(
    actor: Actor, quote_id: uuid.UUID, body: CurrencyChange, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    """Apply a currency change atomically; 409 ``currency_change_blocked`` (with lines) when a line has no price."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.change_currency_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.put("/quotes/{quote_id}/owner", openapi_extra=requires("sales.quote.assign"))
def change_quote_owner(
    actor: Actor, quote_id: uuid.UUID, body: ChangeOwner, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> QuoteDetail:
    with UnitOfWork(actor) as uow:
        detail, replayed = service.change_owner_command(uow, quote_id, body)
    _replayed(response, replayed)
    return detail


@router.get(
    "/quotes/{quote_id}/lines.csv",
    openapi_extra=requires("sales.quote.export"),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_quote_lines_csv(actor: Actor, quote_id: uuid.UUID) -> Response:
    filename, content = service.export_quote_lines_csv(actor, quote_id)
    return _csv(content, filename)


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
            # the route sets its own policy; the request-context middleware adds its defaults only when absent
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
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


# =====================================================================================================
# custom products
# =====================================================================================================
def _custom_filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against product name, code, decor, customer")] = None,
    status: Annotated[list[CustomProductStatus] | None, Query()] = None,
    custom_type: CustomType | None = None,
    party_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    scope: Annotated[str, Query(pattern=r"^(mine|all)$")] = "all",
    include_archived: bool = False,
) -> CustomProductFilters:
    return CustomProductFilters(q=q, status=status, custom_type=custom_type, party_id=party_id, category_id=category_id,
                                scope=scope, include_archived=include_archived)  # type: ignore[arg-type]


@router.get("/custom-products", openapi_extra=requires("sales.custom_product.read"))
def list_custom_products(
    actor: Actor, filters: Annotated[CustomProductFilters, Depends(_custom_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[CustomProductSummary]:
    return service.list_custom_products(actor, filters, limit=limit, offset=offset)


@router.get("/custom-products/status-counts", openapi_extra=requires("sales.custom_product.read"))
def get_custom_product_status_counts(actor: Actor, filters: Annotated[CustomProductFilters, Depends(_custom_filters)]) -> dict[str, int]:
    return service.custom_status_counts(actor, filters)


@router.get(
    "/custom-products/export.csv",
    openapi_extra=requires("sales.custom_product.export"),
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_custom_products_csv(
    actor: Actor, filters: Annotated[CustomProductFilters, Depends(_custom_filters)], include_costing: bool = False
) -> Response:
    """Custom products as CSV within the export scope; costing columns only with ``pricing.cost.read`` and the flag."""
    return _csv(service.export_custom_products_csv(actor, filters, include_costing=include_costing), "custom-products.csv")


@router.post("/custom-products", status_code=201, openapi_extra=requires("sales.custom_product.create"))
def create_custom_product(
    actor: Actor, body: CustomProductCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CustomProductDetail:
    """Create a custom product; ``CP-NNNN`` is allocated atomically and never reused."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_custom_product_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/custom-products/{custom_product_id}", openapi_extra=requires("sales.custom_product.read"))
def get_custom_product(actor: Actor, custom_product_id: uuid.UUID) -> CustomProductDetail:
    """Every legacy field, spec revisions, promotions, quotes using it, capabilities (never costing)."""
    return service.get_custom_product(actor, custom_product_id)


@router.patch("/custom-products/{custom_product_id}", openapi_extra=requires("sales.custom_product.update"))
def update_custom_product(actor: Actor, custom_product_id: uuid.UUID, body: CustomProductUpdate) -> CustomProductDetail:
    with UnitOfWork(actor) as uow:
        custom = service.update_custom_product(uow, custom_product_id, body)
        return service.custom_product_detail(uow, custom)


@router.post("/custom-products/{custom_product_id}/transitions", openapi_extra=requires("sales.custom_product.transition"))
def transition_custom_product(actor: Actor, custom_product_id: uuid.UUID, body: CustomProductTransition) -> CustomProductDetail:
    """develop, sample, quote, approve (needs an approved spec revision), reject/park/reopen (reason), reactivate."""
    with UnitOfWork(actor) as uow:
        custom = service.transition_custom_product(uow, custom_product_id, body)
        return service.custom_product_detail(uow, custom)


@router.post("/custom-products/{custom_product_id}/duplicate", status_code=201, openapi_extra=requires("sales.custom_product.create"))
def duplicate_custom_product(
    actor: Actor, custom_product_id: uuid.UUID, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CustomProductDetail:
    """A new inquiry with a new code and the product name "X (Copy)"; costing and history are not copied."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.duplicate_custom_product_command(uow, custom_product_id)
    _replayed(response, replayed)
    return detail


@router.post("/custom-products/{custom_product_id}/archive", openapi_extra=requires("sales.custom_product.archive"))
def archive_custom_product(actor: Actor, custom_product_id: uuid.UUID, body: CustomProductArchive) -> CustomProductDetail:
    """Archive (rejected, dormant, converted or never quoted); the code is never reused."""
    with UnitOfWork(actor) as uow:
        custom = service.archive_custom_product(uow, custom_product_id, body)
        return service.custom_product_detail(uow, custom)


@router.post("/custom-products/{custom_product_id}/unarchive", openapi_extra=requires("sales.custom_product.archive"))
def unarchive_custom_product(actor: Actor, custom_product_id: uuid.UUID, body: CustomProductArchive) -> CustomProductDetail:
    with UnitOfWork(actor) as uow:
        custom = service.unarchive_custom_product(uow, custom_product_id, body)
        return service.custom_product_detail(uow, custom)


@router.get("/custom-products/{custom_product_id}/history", openapi_extra=requires("sales.custom_product.read"))
def list_custom_product_history(actor: Actor, custom_product_id: uuid.UUID) -> list[CustomHistoryRead]:
    return service.custom_history(actor, custom_product_id)


@router.get("/custom-products/{custom_product_id}/costing", openapi_extra=requires("pricing.cost.read"))
def list_custom_product_costing(actor: Actor, custom_product_id: uuid.UUID) -> list[CostingRead]:
    """Protected costing versions (``pricing.cost.read``; every read is audited)."""
    return service.list_costing(actor, custom_product_id)


@router.post("/custom-products/{custom_product_id}/costing", status_code=201, openapi_extra=requires("pricing.cost.update"))
def create_custom_product_costing(actor: Actor, custom_product_id: uuid.UUID, body: CostingCreate) -> CostingRead:
    with UnitOfWork(actor) as uow:
        return service.record_costing(uow, custom_product_id, body)


@router.post("/custom-products/{custom_product_id}/spec-revisions", status_code=201, openapi_extra=requires("sales.custom_product.update"))
def create_custom_product_spec_revision(actor: Actor, custom_product_id: uuid.UUID, body: SpecRevisionCreate) -> SpecRevisionRead:
    """Record the current specification (optionally with its sample) as the next spec revision."""
    with UnitOfWork(actor) as uow:
        row = service.record_spec_revision(uow, custom_product_id, body)
        return next(r for r in service.custom_product_detail(uow, service.custom_product_row(uow, custom_product_id)).spec_revisions
                    if r.id == row.id)


@router.post(
    "/custom-products/{custom_product_id}/spec-revisions/{revision_id}/outcome",
    openapi_extra=requires("sales.custom_product.update"),
)
def decide_custom_product_spec_revision(
    actor: Actor, custom_product_id: uuid.UUID, revision_id: uuid.UUID, body: SpecOutcomeIn
) -> CustomProductDetail:
    with UnitOfWork(actor) as uow:
        service.decide_spec_revision(uow, custom_product_id, revision_id, body)
        return service.custom_product_detail(uow, service.custom_product_row(uow, custom_product_id))


@router.post("/custom-products/{custom_product_id}/promotion", status_code=201, openapi_extra=requires("sales.custom_product.promote"))
def request_custom_product_promotion(actor: Actor, custom_product_id: uuid.UUID, body: PromotionRequest) -> PromotionRead:
    """Request promotion to a catalogue product (validated, bound to an approval by its payload hash)."""
    with UnitOfWork(actor) as uow:
        promo = service.request_promotion(uow, custom_product_id, body)
        detail = service.custom_product_detail(uow, service.custom_product_row(uow, custom_product_id))
        return next(p for p in detail.promotions if p.id == promo.id)


@router.post(
    "/custom-products/{custom_product_id}/promotions/{promotion_id}/execute",
    openapi_extra=requires("catalogue.product.create"),
)
def execute_custom_product_promotion(actor: Actor, custom_product_id: uuid.UUID, promotion_id: uuid.UUID) -> PromotionRead:
    """Create the master product for an approved promotion (idempotent; a failed one is retried)."""
    with UnitOfWork(actor) as uow:
        promo = service.execute_promotion(uow, custom_product_id, promotion_id)
        detail = service.custom_product_detail(uow, service.custom_product_row(uow, custom_product_id))
        return next(p for p in detail.promotions if p.id == promo.id)


# =====================================================================================================
# samples
# =====================================================================================================
def _sample_filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[SampleStatus] | None, Query()] = None,
    party_id: uuid.UUID | None = None,
    quote_id: uuid.UUID | None = None,
    custom_product_id: uuid.UUID | None = None,
) -> SampleFilters:
    return SampleFilters(q=q, status=status, party_id=party_id, quote_id=quote_id, custom_product_id=custom_product_id)


@router.get("/samples", openapi_extra=requires("sales.sample.read"))
def list_samples(actor: Actor, filters: Annotated[SampleFilters, Depends(_sample_filters)], limit: Limit = 50, offset: Offset = 0) -> Page[SampleRead]:
    return service.list_samples(actor, filters, limit=limit, offset=offset)


@router.get("/samples/status-counts", openapi_extra=requires("sales.sample.read"))
def get_sample_status_counts(actor: Actor, filters: Annotated[SampleFilters, Depends(_sample_filters)]) -> dict[str, int]:
    return service.sample_status_counts(actor, filters)


@router.post("/samples", status_code=201, openapi_extra=requires("sales.sample.create"))
def create_sample(actor: Actor, body: SampleCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> SampleRead:
    """Record a sample request; ``SMP-YYYY-NNNN`` is allocated atomically (yearly reset)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_sample_command(uow, body)
    _replayed(response, replayed)
    return detail


@router.get("/samples/{sample_id}", openapi_extra=requires("sales.sample.read"))
def get_sample(actor: Actor, sample_id: uuid.UUID) -> SampleRead:
    return service.get_sample(actor, sample_id)


@router.patch("/samples/{sample_id}", openapi_extra=requires("sales.sample.update"))
def update_sample(actor: Actor, sample_id: uuid.UUID, body: SampleUpdate) -> SampleRead:
    with UnitOfWork(actor) as uow:
        return service.sample_read(uow, service.update_sample(uow, sample_id, body))


@router.post("/samples/{sample_id}/transitions", openapi_extra=requires("sales.sample.transition"))
def transition_sample(
    actor: Actor, sample_id: uuid.UUID, body: SampleTransition, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> SampleRead:
    """dispatch (courier reference or challan), deliver (evidence), record_feedback, close, cancel (reason)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.sample_transition_command(uow, sample_id, body)
    _replayed(response, replayed)
    return detail
