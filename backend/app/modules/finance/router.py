"""Finance API (``/api/v1/finance``): the hub summary, invoices and credit notes (drafts, edits, transitions with the
issue gate, PDFs, CSV), invoice suggestions, receipts and allocations, ageing, the exceptions list, tax profiles,
the accounting handoff (status, exports, journal CSV, reconciliation) and the restricted quote margin.

Commands accept ``Idempotency-Key`` (replays answer ``Idempotent-Replayed: true``). Every route declares its
permission; services enforce scope and object rules (404 for an invisible record, 403 for a visible one the actor
may not change). A refused issue is not an error: it is recorded and answered ``issued: false`` with the blockers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.core.errors import NotFound
from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.finance import accounting, ageing, config, documents, invoices, margin, receipts, suggestions
from app.modules.finance import common as c
from app.modules.finance.enums import DocType, InvoiceStatus, ReceiptStatus, SuggestionStatus
from app.modules.finance.models import Invoice, Receipt
from app.modules.finance.schemas import (
    AccountingStatus,
    AgeingReport,
    AllocationCreate,
    AllocationRead,
    AllocationReverse,
    CreditAllocationCreate,
    CreditNoteCreate,
    ExceptionsRead,
    ExportRead,
    ExportRequest,
    FinanceSummary,
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilters,
    InvoiceSummary,
    InvoiceTransition,
    InvoiceTransitionResult,
    InvoiceUpdate,
    QuoteMargin,
    ReceiptCreate,
    ReceiptDetail,
    ReceiptFilters,
    ReceiptReverse,
    ReceiptSummary,
    ReconcileRequest,
    SuggestionDismiss,
    SuggestionRead,
    TaxProfileCreate,
    TaxProfileRead,
    Versioned,
)
from app.platform.idempotency.service import run_idempotent
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/finance", tags=["finance"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
TRANSITION_KEYS = (c.INVOICE_UPDATE, c.INVOICE_APPROVE, c.INVOICE_ISSUE)


def _run[T: BaseModel](
    actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T], model: type[T]
) -> T:
    with UnitOfWork(actor) as uow:
        payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
        out, replayed = run_idempotent(
            uow, key=uow.actor.idempotency_key, operation=operation, body=payload,
            fn=lambda: fn(uow).model_dump(mode="json"),
        )
    if replayed:
        response.headers[REPLAYED] = "true"
    return model.model_validate(out)


def _file(content: bytes, filename: str, media_type: str, *, inline: bool) -> Response:
    disposition = "inline" if inline else "attachment"
    headers = {
        "Content-Disposition": f"{disposition}; filename=\"{filename}\"; filename*=UTF-8''{urlquote(filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if media_type == "application/pdf":
        headers["Content-Security-Policy"] = "sandbox"
    return Response(content=content, media_type=media_type, headers=headers)


# =====================================================================================================
# hub
# =====================================================================================================
@router.get("/summary", openapi_extra=requires(c.INVOICE_READ))
def get_finance_summary(actor: Actor) -> FinanceSummary:
    """Server-computed hub figures per currency (receivable, overdue, unallocated; never summed across currencies),
    counts that need attention, the accounting and e-invoice integration state and the actor's list capabilities."""
    with UnitOfWork(actor) as uow:
        return ageing.summary(uow)


@router.get("/exceptions", openapi_extra=requires(c.INVOICE_READ))
def get_finance_exceptions(actor: Actor) -> ExceptionsRead:
    """Blocked issues, overdue invoices, unallocated receipts, failed exports, reconciliation mismatches and margin
    exceptions (margin figures only for ``pricing.cost.read``)."""
    with UnitOfWork(actor) as uow:
        return ExceptionsRead(items=ageing.exception_items(uow), margin=margin.list_exceptions(uow))


@router.get("/ageing", openapi_extra=requires(c.AGEING_READ))
def get_receivables_ageing(actor: Actor, as_of: date | None = None) -> AgeingReport:
    """Per (party, currency) outstanding in buckets current / 1–30 / 31–60 / 61–90 / over 90 days past due, as of a
    company-local date (default today); invoices without a due date are flagged."""
    with UnitOfWork(actor) as uow:
        return ageing.ageing(uow, as_of)


# =====================================================================================================
# invoices and credit notes
# =====================================================================================================
def _invoice_filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against numbers, party, reference")] = None,
    status: Annotated[list[InvoiceStatus] | None, Query()] = None,
    party_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    open_only: bool = False,
) -> InvoiceFilters:
    return InvoiceFilters(q=q, status=status, party_id=party_id, overdue_only=overdue_only, open_only=open_only)


InvoiceQuery = Annotated[InvoiceFilters, Depends(_invoice_filters)]


def _list(actor: Any, f: InvoiceFilters, doc_type: DocType, limit: int, offset: int) -> Page[InvoiceSummary]:
    with UnitOfWork(actor) as uow:
        return invoices.list_invoices(uow, f.model_copy(update={"doc_type": doc_type}), limit=limit, offset=offset)


def _csv(actor: Any, f: InvoiceFilters, doc_type: DocType) -> Response:
    with UnitOfWork(actor) as uow:
        page = invoices.list_invoices(uow, f.model_copy(update={"doc_type": doc_type}), limit=MAX_LIMIT, offset=0)
        uow.audit("finance.invoice.exported", resource_type="finance.invoice", resource_label=doc_type.value)
    name = "credit-notes.csv" if doc_type == DocType.CREDIT_NOTE else "invoices.csv"
    return _file(documents.list_csv(page.items), name, "text/csv; charset=utf-8", inline=False)


def _pdf(actor: Any, invoice_id: uuid.UUID, doc_type: DocType) -> Response:
    with UnitOfWork(actor) as uow:
        d = invoices.get_invoice(uow, invoice_id, doc_type=doc_type)
        pdf = documents.render(uow, d)
        uow.audit("finance.invoice.document_downloaded", resource_type="finance.invoice", resource_id=d.id,
                  resource_label=d.document_number or d.draft_ref)
    return _file(pdf, documents.filename(d), "application/pdf", inline=True)


def _transition(actor: Any, response: Response, invoice_id: uuid.UUID, body: InvoiceTransition, doc_type: DocType) -> InvoiceTransitionResult:
    def run(uow: UnitOfWork) -> InvoiceTransitionResult:
        inv = uow.repo(Invoice).get(invoice_id)
        if inv.doc_type != doc_type.value:
            raise NotFound(code="not_found", resource_type="finance.invoice")
        out = invoices.transition(uow, invoice_id, body)
        if isinstance(out, invoices.IssueResult):
            return InvoiceTransitionResult(issued=out.issued, blockers=out.blockers, detail=out.detail)
        return InvoiceTransitionResult(issued=None, detail=invoices.detail(uow, out))

    return _run(actor, response, f"finance.invoice.transition:{invoice_id}", body, run, InvoiceTransitionResult)


@router.get("/invoices", openapi_extra=requires(c.INVOICE_READ))
def list_invoices(actor: Actor, filters: InvoiceQuery, limit: Limit = 50, offset: Offset = 0) -> Page[InvoiceSummary]:
    """Invoices within the actor's read scope; ``open_only`` / ``overdue_only`` narrow to issued invoices with an
    outstanding amount. Drafts carry ``label`` "Draft — not valid for trade"."""
    return _list(actor, filters, DocType.INVOICE, limit, offset)


@router.get(
    "/invoices/export.csv", openapi_extra=requires(c.INVOICE_READ), response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_invoices_csv(actor: Actor, filters: InvoiceQuery) -> Response:
    """The filtered invoice list as spreadsheet-inert CSV (UTF-8 with BOM); drafts carry their label."""
    return _csv(actor, filters, DocType.INVOICE)


@router.post("/invoices", status_code=201, openapi_extra=requires(c.INVOICE_CREATE))
def create_invoice(
    actor: Actor, body: InvoiceCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> InvoiceDetail:
    """A draft from an issued Outward challan (``challan_id`` / ``suggestion_id``: its not-yet-invoiced quantities at the
    order's prices), from an order's delivered-but-not-invoiced quantities (``sales_order_id``), or manual lines.
    Totals are server-computed; no number is consumed until issue."""
    return _run(actor, response, "finance.invoice.create", body,
                lambda uow: invoices.detail(uow, invoices.create_invoice(uow, body)), InvoiceDetail)


@router.get("/invoices/{invoice_id}", openapi_extra=requires(c.INVOICE_READ))
def get_invoice(actor: Actor, invoice_id: uuid.UUID) -> InvoiceDetail:
    """Detail with lines, totals, the live issue gate (blockers with fix paths), allocations, related documents,
    history, ``capabilities`` and ``allowed_transitions``."""
    with UnitOfWork(actor) as uow:
        return invoices.get_invoice(uow, invoice_id, doc_type=DocType.INVOICE)


@router.patch("/invoices/{invoice_id}", openapi_extra=requires(c.INVOICE_UPDATE))
def update_invoice(
    actor: Actor, invoice_id: uuid.UUID, body: InvoiceUpdate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InvoiceDetail:
    """Edit a draft (lines, tax profile, payment days, reference, notes); totals are recomputed."""
    return _run(actor, response, f"finance.invoice.update:{invoice_id}", body,
                lambda uow: invoices.detail(uow, invoices.update_invoice(uow, invoice_id, body)), InvoiceDetail)


@router.post("/invoices/{invoice_id}/transitions", openapi_extra=requires(*TRANSITION_KEYS))
def transition_invoice(
    actor: Actor, invoice_id: uuid.UUID, body: InvoiceTransition, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InvoiceTransitionResult:
    """``submit``, ``approve`` (never by the creator), ``reject`` (reason), ``issue`` (recent sign-in; the issue gate
    runs again in the transaction and the number is assigned only here), ``cancel`` (reason; not once issued)."""
    return _transition(actor, response, invoice_id, body, DocType.INVOICE)


@router.get(
    "/invoices/{invoice_id}/document.pdf", openapi_extra=requires(c.INVOICE_READ), response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_invoice_pdf(actor: Actor, invoice_id: uuid.UUID) -> Response:
    """The invoice PDF: company identity, bank details and terms from the settings (labelled placeholders when not
    configured); a draft is watermarked and labelled "Draft — not valid for trade"."""
    return _pdf(actor, invoice_id, DocType.INVOICE)


@router.get("/credit-notes", openapi_extra=requires(c.INVOICE_READ))
def list_credit_notes(actor: Actor, filters: InvoiceQuery, limit: Limit = 50, offset: Offset = 0) -> Page[InvoiceSummary]:
    return _list(actor, filters, DocType.CREDIT_NOTE, limit, offset)


@router.get(
    "/credit-notes/export.csv", openapi_extra=requires(c.INVOICE_READ), response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_credit_notes_csv(actor: Actor, filters: InvoiceQuery) -> Response:
    return _csv(actor, filters, DocType.CREDIT_NOTE)


@router.post("/credit-notes", status_code=201, openapi_extra=requires(c.INVOICE_CREATE))
def create_credit_note(
    actor: Actor, body: CreditNoteCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> InvoiceDetail:
    """A draft credit note against an issued invoice's lines (never more than is still creditable); on issue it
    settles the original invoice first."""
    return _run(actor, response, "finance.credit_note.create", body,
                lambda uow: invoices.detail(uow, invoices.create_credit_note(uow, body)), InvoiceDetail)


@router.get("/credit-notes/{credit_note_id}", openapi_extra=requires(c.INVOICE_READ))
def get_credit_note(actor: Actor, credit_note_id: uuid.UUID) -> InvoiceDetail:
    with UnitOfWork(actor) as uow:
        return invoices.get_invoice(uow, credit_note_id, doc_type=DocType.CREDIT_NOTE)


@router.patch("/credit-notes/{credit_note_id}", openapi_extra=requires(c.INVOICE_UPDATE))
def update_credit_note(
    actor: Actor, credit_note_id: uuid.UUID, body: InvoiceUpdate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InvoiceDetail:
    return _run(actor, response, f"finance.invoice.update:{credit_note_id}", body,
                lambda uow: invoices.detail(uow, invoices.update_invoice(uow, credit_note_id, body)), InvoiceDetail)


@router.post("/credit-notes/{credit_note_id}/transitions", openapi_extra=requires(*TRANSITION_KEYS))
def transition_credit_note(
    actor: Actor, credit_note_id: uuid.UUID, body: InvoiceTransition, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InvoiceTransitionResult:
    return _transition(actor, response, credit_note_id, body, DocType.CREDIT_NOTE)


@router.get(
    "/credit-notes/{credit_note_id}/document.pdf", openapi_extra=requires(c.INVOICE_READ), response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_credit_note_pdf(actor: Actor, credit_note_id: uuid.UUID) -> Response:
    return _pdf(actor, credit_note_id, DocType.CREDIT_NOTE)


@router.post("/credit-notes/{credit_note_id}/allocations", status_code=201, openapi_extra=requires(c.ALLOCATION_CREATE))
def allocate_credit_note(
    actor: Actor, credit_note_id: uuid.UUID, body: CreditAllocationCreate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> InvoiceDetail:
    """Settle another issued invoice of the same party and currency from an issued credit note's remaining amount."""

    def run(uow: UnitOfWork) -> InvoiceDetail:
        receipts.allocate_credit_note(uow, credit_note_id, body)
        return invoices.detail(uow, uow.repo(Invoice).get(credit_note_id))

    return _run(actor, response, f"finance.credit_note.allocate:{credit_note_id}", body, run, InvoiceDetail)


# =====================================================================================================
# invoice suggestions
# =====================================================================================================
@router.get("/invoice-suggestions", openapi_extra=requires(c.INVOICE_READ))
def list_invoice_suggestions(actor: Actor, status: SuggestionStatus | None = SuggestionStatus.OPEN) -> list[SuggestionRead]:
    """One suggestion per issued Outward challan to a customer; draft from it (``POST /invoices`` with
    ``suggestion_id``) or dismiss it with a reason."""
    with UnitOfWork(actor) as uow:
        return suggestions.list_suggestions(uow, status=status)


@router.post("/invoice-suggestions/{suggestion_id}/dismiss", openapi_extra=requires(c.INVOICE_CREATE))
def dismiss_invoice_suggestion(
    actor: Actor, suggestion_id: uuid.UUID, body: SuggestionDismiss, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> SuggestionRead:
    return _run(actor, response, f"finance.suggestion.dismiss:{suggestion_id}", body,
                lambda uow: suggestions.dismiss(uow, suggestion_id, body), SuggestionRead)


# =====================================================================================================
# receipts and allocations
# =====================================================================================================
def _receipt_filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    party_id: uuid.UUID | None = None,
    status: Annotated[list[ReceiptStatus] | None, Query()] = None,
    unallocated_only: bool = False,
) -> ReceiptFilters:
    return ReceiptFilters(q=q, party_id=party_id, status=status, unallocated_only=unallocated_only)


@router.get("/receipts", openapi_extra=requires(c.RECEIPT_READ))
def list_receipts(
    actor: Actor, filters: Annotated[ReceiptFilters, Depends(_receipt_filters)], limit: Limit = 50, offset: Offset = 0
) -> Page[ReceiptSummary]:
    with UnitOfWork(actor) as uow:
        return receipts.list_receipts(uow, filters, limit=limit, offset=offset)


@router.post("/receipts", status_code=201, openapi_extra=requires(c.RECEIPT_CREATE))
def record_receipt(
    actor: Actor, body: ReceiptCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ReceiptDetail:
    """Record money received (``RCPT-{fy}-NNNN``); allocate it to the party's open invoices afterwards."""
    return _run(actor, response, "finance.receipt.create", body,
                lambda uow: receipts.receipt_detail(uow, receipts.record_receipt(uow, body)), ReceiptDetail)


@router.get("/receipts/{receipt_id}", openapi_extra=requires(c.RECEIPT_READ))
def get_receipt(actor: Actor, receipt_id: uuid.UUID) -> ReceiptDetail:
    """Detail with allocations, the party's open invoices in the same currency and ``capabilities``."""
    with UnitOfWork(actor) as uow:
        return receipts.get_receipt(uow, receipt_id)


@router.post("/receipts/{receipt_id}/reverse", openapi_extra=requires(c.RECEIPT_REVERSE))
def reverse_receipt(
    actor: Actor, receipt_id: uuid.UUID, body: ReceiptReverse, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReceiptDetail:
    """Void a receipt (recent sign-in, reason): it is kept as reversed and its allocations are reversed with it."""
    return _run(actor, response, f"finance.receipt.reverse:{receipt_id}", body,
                lambda uow: receipts.receipt_detail(uow, receipts.reverse_receipt(uow, receipt_id, body)), ReceiptDetail)


@router.post("/receipts/{receipt_id}/allocations", status_code=201, openapi_extra=requires(c.ALLOCATION_CREATE))
def allocate_receipt(
    actor: Actor, receipt_id: uuid.UUID, body: AllocationCreate, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReceiptDetail:
    """Allocate (part of) a receipt to an issued invoice of the same party and currency. Over-allocation of either side
    is refused (409 ``over_allocation`` with what is still available)."""

    def run(uow: UnitOfWork) -> ReceiptDetail:
        receipts.allocate_receipt(uow, receipt_id, body)
        return receipts.receipt_detail(uow, uow.repo(Receipt).get(receipt_id))

    return _run(actor, response, f"finance.receipt.allocate:{receipt_id}", body, run, ReceiptDetail)


@router.post("/allocations/{allocation_id}/reverse", openapi_extra=requires(c.ALLOCATION_CREATE))
def reverse_allocation(
    actor: Actor, allocation_id: uuid.UUID, body: AllocationReverse, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> AllocationRead:
    """Reverse an allocation once (a new row with the negated amount; the original is kept)."""

    def run(uow: UnitOfWork) -> AllocationRead:
        row = receipts.reverse_allocation(uow, allocation_id, body)
        return invoices.allocation_reads(uow, [row])[0]

    return _run(actor, response, f"finance.allocation.reverse:{allocation_id}", body, run, AllocationRead)


# =====================================================================================================
# configuration: tax profiles
# =====================================================================================================
@router.get("/tax-profiles", openapi_extra=requires(c.INVOICE_READ))
def list_tax_profiles(actor: Actor) -> list[TaxProfileRead]:
    """Business-entered tax scenarios (rate + source reference); usable for issue only once verified by a second
    person. No rate is ever invented by the system."""
    with UnitOfWork(actor) as uow:
        return config.list_tax_profiles(uow)


@router.post("/tax-profiles", status_code=201, openapi_extra=requires(c.CONFIG_MANAGE))
def create_tax_profile(
    actor: Actor, body: TaxProfileCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> TaxProfileRead:
    return _run(actor, response, "finance.tax_profile.create", body,
                lambda uow: config.tax_profile_read(uow, config.create_tax_profile(uow, body)), TaxProfileRead)


@router.post("/tax-profiles/{profile_id}/verify", openapi_extra=requires(c.TAX_PROFILE_APPROVE))
def verify_tax_profile(
    actor: Actor, profile_id: uuid.UUID, body: Versioned, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> TaxProfileRead:
    """A second person confirms the rate and its source (MFA; never the author)."""

    def run(uow: UnitOfWork) -> TaxProfileRead:
        return config.tax_profile_read(uow, config.verify_tax_profile(uow, profile_id, body))

    return _run(actor, response, f"finance.tax_profile.verify:{profile_id}", body, run, TaxProfileRead)


# =====================================================================================================
# accounting handoff
# =====================================================================================================
@router.get("/accounting/status", openapi_extra=requires(c.INVOICE_READ))
def get_accounting_status(actor: Actor) -> AccountingStatus:
    """Integration ``accounting`` (Demo / not connected until a live adapter exists), the account mapping, the last
    export and how many issued documents wait to be exported."""
    with UnitOfWork(actor) as uow:
        return accounting.status(uow)


@router.get("/accounting/exports", openapi_extra=requires(c.INVOICE_READ))
def list_accounting_exports(actor: Actor, limit: Limit = 20, offset: Offset = 0) -> Page[ExportRead]:
    with UnitOfWork(actor) as uow:
        return accounting.list_exports(uow, limit=limit, offset=offset)


@router.post("/accounting/exports", status_code=201, openapi_extra=requires(c.EXPORT_RUN))
def run_accounting_export(
    actor: Actor, body: ExportRequest, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ExportRead:
    """Export issued documents not yet exported through the ``csv`` adapter (journal file) or the ``demo`` adapter
    (labelled simulated acknowledgement; nothing is posted anywhere). A missing account code blocks documents."""

    def run(uow: UnitOfWork) -> ExportRead:
        return accounting.export_read(uow, accounting.run_export(uow, body))

    return _run(actor, response, "finance.accounting_export.run", body, run, ExportRead)


@router.get("/accounting/exports/{export_id}", openapi_extra=requires(c.INVOICE_READ))
def get_accounting_export(actor: Actor, export_id: uuid.UUID) -> ExportRead:
    with UnitOfWork(actor) as uow:
        return accounting.get_export(uow, export_id)


@router.get(
    "/accounting/exports/{export_id}/journal.csv", openapi_extra=requires(c.EXPORT_RUN), response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def download_accounting_journal(actor: Actor, export_id: uuid.UUID) -> Response:
    """The journal exactly as exported (formula-inert); its SHA-256 is on the export."""
    with UnitOfWork(actor) as uow:
        name, content = accounting.export_content(uow, export_id)
    return _file(content, name, "text/csv; charset=utf-8", inline=False)


@router.post("/accounting/exports/{export_id}/reconcile", openapi_extra=requires(c.EXPORT_RUN))
def reconcile_accounting_export(
    actor: Actor, export_id: uuid.UUID, body: ReconcileRequest, response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ExportRead:
    """Compare the export with the accounting side's references and totals and list every mismatch (Demo exports
    reconcile against their simulated acknowledgement when no lines are given)."""

    def run(uow: UnitOfWork) -> ExportRead:
        return accounting.export_read(uow, accounting.reconcile(uow, export_id, body))

    return _run(actor, response, f"finance.accounting_export.reconcile:{export_id}", body, run, ExportRead)


# =====================================================================================================
# margin
# =====================================================================================================
@router.get("/quotes/{quote_id}/margin", openapi_extra=requires("sales.quote.read"))
def get_quote_margin(actor: Actor, quote_id: uuid.UUID) -> QuoteMargin:
    """A visible quote's margin from the costs of record; revenue, cost and margin are null (``redacted_fields``)
    without ``pricing.cost.read``. Never exposed to a model."""
    with UnitOfWork(actor) as uow:
        return margin.quote_margin(uow, quote_id)


__all__ = ["router"]
