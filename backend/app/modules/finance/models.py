"""Finance tables (operations.md §9; conventions: ``finance_`` prefix). Money is NUMERIC(18,4) + currency; amounts in
different currencies are never summed.

- ``finance_invoice`` holds invoices and credit notes (``doc_type``). ``document_number`` is assigned **only at issue**
  (UNIQUE(company, doc_type, number)); drafts carry a ``draft_ref`` that never consumes an invoice number. Approval
  is never by the creator (CHECK ``approved_by <> owner_user_id``); an issued document always has a number and a date.
- ``finance_invoice_line`` links to the order line and the delivery-challan line it bills; tax figures come from the
  chosen tax profile only (never invented).
- ``finance_allocation`` is append-only (trigger): a correction is a reversal row with a negative amount pointing at
  the original (UNIQUE ``reverses_allocation_id``); over-allocation is refused under row locks on both sides.
- ``finance_accounting_export`` / ``finance_accounting_sync_item``: the handoff batches (CSV or Demo adapter) and the
  per-document reconciliation state.
- ``finance_margin_exception``: quotes whose margin from costs of record fell below the policy threshold; the margin
  figures are restricted values (``pricing.cost.read``) and never leave through events, readers or the model.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, BranchMixin, IdMixin, TenantEntity, TenantMixin, VersionMixin
from app.modules.finance.enums import (
    AccountingAdapterKind,
    AllocationSource,
    DocType,
    ExportStatus,
    InvoiceAction,
    InvoiceStatus,
    MarginExceptionStatus,
    ReceiptMethod,
    ReceiptStatus,
    ReconciliationStatus,
    SuggestionStatus,
    SyncStatus,
    TaxProfileStatus,
    TaxStatus,
)

_CURRENCIES = "('INR', 'EUR', 'USD', 'GBP')"


def _user_fk() -> Any:
    return ForeignKey("app_user.id", ondelete="RESTRICT")


class TaxProfile(TenantEntity, VersionMixin, Base):
    """A business-entered tax scenario with its rate and source reference; usable for issue only once verified by a
    second person (``finance.tax_profile.approve``, never the author)."""

    __tablename__ = "finance_tax_profile"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario: Mapped[str] = mapped_column(String(200), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    requires_e_invoice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_reference: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": TaxProfileStatus}
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_finance_tax_profile_code"),
        CheckConstraint("rate_percent >= 0 AND rate_percent <= 100", name="rate_range"),
        CheckConstraint("verified_by IS NULL OR verified_by <> author_user_id", name="verifier_not_author"),
        CheckConstraint(
            "(status <> 'verified') OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name="verified_has_verifier",
        ),
    )


class Invoice(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "finance_invoice"

    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": DocType})
    draft_ref: Mapped[str] = mapped_column(String(20), nullable=False)
    #: INV-{fy}-NNNN / CN-{fy}-NNNN, assigned in the issue transaction only
    document_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": InvoiceStatus}
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: legal name, billing address lines, tax identifiers as of drafting (refreshed while a draft)
    billing_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order.id", ondelete="RESTRICT"), nullable=True
    )
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=True
    )
    suggestion_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_tax_profile.id", ondelete="RESTRICT"), nullable=True
    )
    tax_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_configured", info={"enum": TaxStatus}
    )
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    customer_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: the creator: never the approver
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: the version the approval covers; any later change invalidates it
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: blocker codes of the last refused issue attempt (cleared when issued)
    last_blockers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    overdue_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: user | agent | seed | suggestion
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "draft_ref", name="uq_finance_invoice_draft_ref"),
        UniqueConstraint("company_id", "doc_type", "document_number", name="uq_finance_invoice_number"),
        Index("ix_finance_invoice_status", "company_id", "doc_type", "status"),
        Index("ix_finance_invoice_party", "company_id", "party_id", "currency"),
        Index("ix_finance_invoice_due", "company_id", "status", "due_date"),
        Index(
            "ix_finance_invoice_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("approved_by IS NULL OR approved_by <> owner_user_id", name="approver_not_creator"),
        CheckConstraint(
            "(status <> 'issued') OR (document_number IS NOT NULL AND document_date IS NOT NULL "
            "AND issued_at IS NOT NULL)",
            name="issued_has_number",
        ),
        CheckConstraint(
            "(status IN ('issued', 'cancelled')) OR document_number IS NULL", name="number_only_when_issued"
        ),
        CheckConstraint(
            "(doc_type <> 'credit_note') OR original_invoice_id IS NOT NULL", name="credit_note_has_original"
        ),
        CheckConstraint("payment_due_days IS NULL OR payment_due_days BETWEEN 0 AND 365", name="due_days_range"),
        CheckConstraint("subtotal_amount >= 0 AND total_amount >= 0", name="amounts_non_negative"),
        CheckConstraint("(status <> 'cancelled') OR cancel_reason_code IS NOT NULL", name="cancelled_has_reason"),
    )


class InvoiceLine(TenantEntity, Base):
    __tablename__ = "finance_invoice_line"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    so_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order_line.id", ondelete="RESTRICT"), nullable=True
    )
    challan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=True
    )
    challan_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan_line.id", ondelete="RESTRICT"), nullable=True
    )
    #: credit-note line -> the invoice line it credits
    credited_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice_line.id", ondelete="RESTRICT"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    item_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(12), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_finance_invoice_line_no"),
        Index("ix_finance_invoice_line_so_line", "company_id", "so_line_id"),
        Index("ix_finance_invoice_line_challan_line", "company_id", "challan_line_id"),
        ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_finance_invoice_line_uom",
            ondelete="RESTRICT",
        ),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND amount >= 0", name="amounts_non_negative"),
    )


class InvoiceStatusHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "finance_invoice_status_history"
    __append_only__ = True

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": InvoiceAction})
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blocker_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invoice_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_finance_invoice_status_history_invoice", "invoice_id", "occurred_at"),)


class Receipt(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "finance_receipt"

    receipt_number: Mapped[str] = mapped_column(String(30), nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": ReceiptMethod})
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: the company bank account label it was received into (never the account number)
    bank_account_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="recorded", info={"enum": ReceiptStatus}
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=False)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverse_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reverse_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unallocated_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "receipt_number", name="uq_finance_receipt_number"),
        Index("ix_finance_receipt_party", "company_id", "party_id", "currency"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(status <> 'reversed') OR (reversed_at IS NOT NULL AND reverse_reason_code IS NOT NULL)",
            name="reversed_has_reason",
        ),
    )


class Allocation(IdMixin, TenantMixin, Base):
    """Append-only. Positive rows allocate; a reversal row has the negated amount and ``reverses_allocation_id``."""

    __tablename__ = "finance_allocation"
    __append_only__ = True

    source_type: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": AllocationSource})
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_receipt.id", ondelete="RESTRICT"), nullable=True
    )
    credit_note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    reverses_allocation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_allocation.id", ondelete="RESTRICT"), nullable=True
    )
    allocated_on: Mapped[date] = mapped_column(Date, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("reverses_allocation_id", name="uq_finance_allocation_reverses"),
        Index("ix_finance_allocation_invoice", "company_id", "invoice_id"),
        Index("ix_finance_allocation_receipt", "company_id", "receipt_id"),
        Index("ix_finance_allocation_credit_note", "company_id", "credit_note_id"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint(
            "(source_type = 'receipt' AND receipt_id IS NOT NULL AND credit_note_id IS NULL) OR "
            "(source_type = 'credit_note' AND credit_note_id IS NOT NULL AND receipt_id IS NULL)",
            name="one_source",
        ),
        CheckConstraint(
            "(reverses_allocation_id IS NULL AND amount > 0) OR (reverses_allocation_id IS NOT NULL AND amount < 0)",
            name="sign_matches_kind",
        ),
    )


class InvoiceSuggestion(TenantEntity, VersionMixin, BranchMixin, Base):
    """One per issued delivery challan to a customer (the ``finance.invoice_suggestion`` consumer)."""

    __tablename__ = "finance_invoice_suggestion"

    challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    challan_number: Mapped[str] = mapped_column(String(30), nullable=False)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order.id", ondelete="RESTRICT"), nullable=True
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", info={"enum": SuggestionStatus}
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=True
    )
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)
    dismiss_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "challan_id", name="uq_finance_invoice_suggestion_challan"),
        Index("ix_finance_invoice_suggestion_status", "company_id", "status"),
        CheckConstraint("(status <> 'drafted') OR invoice_id IS NOT NULL", name="drafted_has_invoice"),
    )


class AccountingExport(TenantEntity, Base):
    __tablename__ = "finance_accounting_export"

    export_number: Mapped[str] = mapped_column(String(30), nullable=False)
    adapter: Mapped[str] = mapped_column(String(10), nullable=False, info={"enum": AccountingAdapterKind})
    status: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": ExportStatus})
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: the journal CSV exactly as produced (formula-inert) and its hash
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Demo adapter: the simulated acknowledgement reference (labelled Demo); CSV: set by reconciliation
    acknowledgement_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_reconciled", info={"enum": ReconciliationStatus}
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: documents left out of this batch and why (e.g. a missing account code): [{invoice_id, document_number, reason}]
    blocked_documents: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "export_number", name="uq_finance_accounting_export_number"),
        CheckConstraint("document_count >= 0 AND blocked_count >= 0", name="counts_non_negative"),
        CheckConstraint("(status <> 'failed') OR error_code IS NOT NULL", name="failed_has_error"),
    )


class AccountingSyncItem(TenantEntity, Base):
    __tablename__ = "finance_accounting_sync_item"

    export_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_accounting_export.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("finance_invoice.id", ondelete="RESTRICT"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": DocType})
    document_number: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": SyncStatus})
    external_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    acknowledged_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mismatch_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)

    __table_args__ = (
        UniqueConstraint("export_id", "invoice_id", name="uq_finance_accounting_sync_item_doc"),
        Index("ix_finance_accounting_sync_item_invoice", "company_id", "invoice_id"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
    )


class MarginException(TenantEntity, VersionMixin, Base):
    __tablename__ = "finance_margin_exception"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    quote_number: Mapped[str] = mapped_column(String(30), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), _user_fk(), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    #: restricted values (``pricing.cost.read``): never in events, readers, logs or model context
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    lines_without_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", info={"enum": MarginExceptionStatus}
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "quote_id", "revision_no", name="uq_finance_margin_exception_revision"),
        Index("ix_finance_margin_exception_status", "company_id", "status"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
    )


__all__ = [
    "AccountingExport",
    "AccountingSyncItem",
    "Allocation",
    "Invoice",
    "InvoiceLine",
    "InvoiceStatusHistory",
    "InvoiceSuggestion",
    "MarginException",
    "Receipt",
    "TaxProfile",
]
