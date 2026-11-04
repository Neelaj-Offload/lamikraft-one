"""Finance request and read models. Money travels as ``Money`` (decimal strings + currency); quantities as
``DecimalStr``. Margin figures are restricted (``pricing.cost.read``, never exposed to a model)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import CurrencyCode, DecimalStr, Money
from app.modules.finance.enums import (
    AccountingAdapterKind,
    DocType,
    ExportStatus,
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
from app.platform.authz.redaction import Restricted

COST_GUARD = Restricted("pricing.cost.read", model_exposure="deny")
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]
_Body = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinanceUserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class FinancePartyRef(BaseModel):
    id: uuid.UUID
    party_number: str | None
    display_name: str


class FinanceDocRef(BaseModel):
    id: uuid.UUID
    kind: str
    number: str
    path: str


# =====================================================================================================
# tax profiles
# =====================================================================================================
class TaxProfileCreate(BaseModel):
    model_config = _Body

    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    scenario: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    rate_percent: DecimalStr = Field(ge=Decimal(0), le=Decimal(100))
    requires_e_invoice: bool = True
    source_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class TaxProfileRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    scenario: str
    rate_percent: DecimalStr
    requires_e_invoice: bool
    source_reference: str
    status: TaxProfileStatus
    author: FinanceUserRef | None
    verified_by: FinanceUserRef | None
    verified_at: datetime | None
    version: int
    capabilities: dict[str, Capability] = Field(default_factory=dict)


class Versioned(BaseModel):
    model_config = _Body

    expected_version: int = Field(ge=1)


# =====================================================================================================
# invoices and credit notes
# =====================================================================================================
class InvoiceLineIn(BaseModel):
    model_config = _Body

    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    quantity: DecimalStr = Field(gt=Decimal(0))
    uom_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]
    unit_price: DecimalStr = Field(ge=Decimal(0))
    hsn_sac: Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)] | None = None
    product_id: uuid.UUID | None = None
    so_line_id: uuid.UUID | None = None


class InvoiceCreate(BaseModel):
    """A manual draft (lines entered), or a draft from an issued delivery challan / an order's delivered quantity."""

    model_config = _Body

    party_id: uuid.UUID | None = None
    currency: CurrencyCode | None = None
    challan_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    suggestion_id: uuid.UUID | None = None
    tax_profile_id: uuid.UUID | None = None
    payment_due_days: int | None = Field(default=None, ge=0, le=365)
    customer_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    lines: list[InvoiceLineIn] = Field(default_factory=list, max_length=200)


class InvoiceUpdate(Versioned):
    tax_profile_id: uuid.UUID | None = None
    clear_tax_profile: bool = False
    payment_due_days: int | None = Field(default=None, ge=0, le=365)
    customer_reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    #: replace every line (drafts only); totals are recomputed by the server
    lines: list[InvoiceLineIn] | None = Field(default=None, max_length=200)


class CreditNoteLineIn(BaseModel):
    model_config = _Body

    invoice_line_id: uuid.UUID
    quantity: DecimalStr = Field(gt=Decimal(0))


class CreditNoteCreate(BaseModel):
    model_config = _Body

    original_invoice_id: uuid.UUID
    reason_code: Code
    lines: list[CreditNoteLineIn] = Field(min_length=1, max_length=200)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class InvoiceTransition(Versioned):
    action: Literal["submit", "approve", "reject", "issue", "cancel"]
    reason_code: Code | None = None
    reason: Reason | None = None


class InvoiceLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    description: str
    item_code: str | None
    hsn_sac: str | None
    quantity: DecimalStr
    uom_code: str
    unit_price: Money
    amount: Money
    tax_rate_percent: DecimalStr | None
    tax_amount: Money | None
    so_line_id: uuid.UUID | None
    challan_id: uuid.UUID | None
    challan_line_id: uuid.UUID | None
    credited_line_id: uuid.UUID | None
    product_id: uuid.UUID | None
    #: credit notes: what can still be credited against this invoice line
    creditable_quantity: DecimalStr | None = None


class InvoiceHistoryRead(BaseModel):
    action: str
    from_status: str
    to_status: str
    actor: FinanceUserRef | None
    reason_code: str | None
    reason: str | None
    blocker_codes: list[str]
    occurred_at: datetime


class GateBlocker(BaseModel):
    code: str
    #: what the user can do about it (plain copy is in the web messages; this names the place)
    fix_path: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)


class IssueGate(BaseModel):
    """The issue gate, evaluated now (``finance.issuance_gate.check``)."""

    can_issue: bool
    blockers: list[GateBlocker]
    #: the label drafts carry while any configuration blocker remains
    label: str | None


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    doc_type: DocType
    draft_ref: str
    document_number: str | None
    status: InvoiceStatus
    party: FinancePartyRef
    currency: CurrencyCode
    document_date: date | None
    due_date: date | None
    total: Money
    outstanding: Money | None
    is_overdue: bool
    tax_status: TaxStatus
    label: str | None
    owner: FinanceUserRef | None
    sales_order_id: uuid.UUID | None
    original_invoice_id: uuid.UUID | None
    created_at: datetime


class InvoiceDetail(InvoiceSummary):
    billing: dict[str, object]
    payment_due_days: int | None
    tax_profile: TaxProfileRead | None
    subtotal: Money
    tax: Money | None
    allocated: Money
    credited: Money
    customer_reference: str | None
    notes: str | None
    reason_code: str | None
    lines: list[InvoiceLineRead]
    history: list[InvoiceHistoryRead]
    allocations: list[AllocationRead]
    related: list[FinanceDocRef]
    approved_by: FinanceUserRef | None
    approved_at: datetime | None
    approved_version: int | None
    issued_by: FinanceUserRef | None
    issued_at: datetime | None
    last_blockers: list[str]
    gate: IssueGate
    version: int
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


class InvoiceTransitionResult(BaseModel):
    """The answer to a transition. ``issue`` that the gate refuses is recorded (history, ``finance.invoice.issue_blocked``)
    and answered with ``issued: false`` and the blockers; nothing else changes."""

    issued: bool | None = None
    blockers: list[GateBlocker] = Field(default_factory=list)
    detail: InvoiceDetail


class InvoiceFilters(BaseModel):
    q: str | None = None
    doc_type: DocType = DocType.INVOICE
    status: list[InvoiceStatus] | None = None
    party_id: uuid.UUID | None = None
    overdue_only: bool = False
    open_only: bool = False


# =====================================================================================================
# receipts and allocations
# =====================================================================================================
class ReceiptCreate(BaseModel):
    model_config = _Body

    party_id: uuid.UUID
    amount: DecimalStr = Field(gt=Decimal(0))
    currency: CurrencyCode
    received_on: date
    method: ReceiptMethod = ReceiptMethod.BANK_TRANSFER
    reference: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    bank_account_label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class ReceiptReverse(Versioned):
    reason_code: Code
    reason: Reason | None = None


class AllocationCreate(BaseModel):
    model_config = _Body

    invoice_id: uuid.UUID
    amount: DecimalStr = Field(gt=Decimal(0))


class CreditAllocationCreate(BaseModel):
    model_config = _Body

    invoice_id: uuid.UUID
    amount: DecimalStr = Field(gt=Decimal(0))


class AllocationReverse(BaseModel):
    model_config = _Body

    reason_code: Code


class AllocationRead(BaseModel):
    id: uuid.UUID
    source_type: str
    receipt_id: uuid.UUID | None
    receipt_number: str | None
    credit_note_id: uuid.UUID | None
    credit_note_number: str | None
    invoice_id: uuid.UUID
    invoice_number: str | None
    amount: Money
    allocated_on: date
    reverses_allocation_id: uuid.UUID | None
    reversed: bool
    actor: FinanceUserRef | None
    created_at: datetime


class ReceiptSummary(BaseModel):
    id: uuid.UUID
    receipt_number: str
    party: FinancePartyRef
    amount: Money
    allocated: Money
    unallocated: Money
    received_on: date
    method: ReceiptMethod
    reference: str | None
    status: ReceiptStatus
    owner: FinanceUserRef | None


class OpenInvoiceRef(BaseModel):
    id: uuid.UUID
    document_number: str
    due_date: date | None
    outstanding: Money


class ReceiptDetail(ReceiptSummary):
    bank_account_label: str | None
    notes: str | None
    allocations: list[AllocationRead]
    #: the party's issued invoices in this currency that still have something outstanding
    open_invoices: list[OpenInvoiceRef]
    reversed_at: datetime | None
    reverse_reason_code: str | None
    version: int
    capabilities: dict[str, Capability]


class ReceiptFilters(BaseModel):
    q: str | None = None
    party_id: uuid.UUID | None = None
    status: list[ReceiptStatus] | None = None
    unallocated_only: bool = False


# =====================================================================================================
# ageing, summary, suggestions, exceptions
# =====================================================================================================
class AgeingBuckets(BaseModel):
    current: Money
    days_1_30: Money
    days_31_60: Money
    days_61_90: Money
    days_over_90: Money
    total: Money


class AgeingRow(BaseModel):
    party: FinancePartyRef
    currency: CurrencyCode
    buckets: AgeingBuckets
    invoice_count: int
    no_due_date_count: int
    unallocated_receipts: Money


class AgeingReport(BaseModel):
    as_of: date
    time_zone: str
    rows: list[AgeingRow]
    #: per currency (never summed across currencies)
    totals: list[AgeingBuckets]
    no_due_date_invoices: list[OpenInvoiceRef]


class CurrencyFigure(BaseModel):
    currency: CurrencyCode
    receivable: Money
    overdue: Money
    unallocated: Money


class FinanceSummary(BaseModel):
    as_of: date
    drafts: int
    pending_approval: int
    issue_blocked: int
    issued_open: int
    overdue: int
    open_suggestions: int
    unallocated_receipts: int
    margin_exceptions: int
    sync_attention: int
    by_currency: list[CurrencyFigure]
    accounting_mode: str
    accounting_state: str
    e_invoice_state: str
    tax_profiles_verified: int
    #: list-level controls for the hub (create invoice, record receipt, run export, manage configuration, ...)
    capabilities: dict[str, Capability] = Field(default_factory=dict)


class SuggestionRead(BaseModel):
    id: uuid.UUID
    challan_id: uuid.UUID
    challan_number: str
    sales_order_id: uuid.UUID | None
    party: FinancePartyRef
    status: SuggestionStatus
    invoice_id: uuid.UUID | None
    created_at: datetime
    version: int


class SuggestionDismiss(Versioned):
    reason_code: Code


class MarginLine(BaseModel):
    line_no: int
    description: str
    quantity: DecimalStr
    uom_code: str
    revenue: Annotated[Money | None, COST_GUARD] = None
    cost: Annotated[Money | None, COST_GUARD] = None
    cost_status: Literal["ok", "missing", "unit_mismatch", "currency_mismatch", "no_product"]


class QuoteMargin(BaseModel):
    """Margin of a quote from the costs of record (restricted: redacted without ``pricing.cost.read``)."""

    quote_id: uuid.UUID
    quote_number: str
    currency: CurrencyCode
    revenue: Annotated[Money | None, COST_GUARD] = None
    cost: Annotated[Money | None, COST_GUARD] = None
    margin_percent: Annotated[DecimalStr | None, COST_GUARD] = None
    threshold_percent: DecimalStr
    below_threshold: Annotated[bool | None, COST_GUARD] = None
    lines_without_cost: int
    lines: list[MarginLine]
    redacted_fields: list[str] = Field(default_factory=list)


class MarginExceptionRead(BaseModel):
    id: uuid.UUID
    quote_id: uuid.UUID
    quote_number: str
    revision_no: int
    party_name: str
    owner: FinanceUserRef | None
    status: MarginExceptionStatus
    detected_at: datetime
    lines_without_cost: int
    threshold_percent: DecimalStr
    margin_percent: Annotated[DecimalStr | None, COST_GUARD] = None
    revenue: Annotated[Money | None, COST_GUARD] = None
    cost: Annotated[Money | None, COST_GUARD] = None
    redacted_fields: list[str] = Field(default_factory=list)


class FinanceException(BaseModel):
    kind: Literal["issue_blocked", "overdue", "unallocated_receipt", "sync_mismatch", "sync_failed", "margin"]
    ref: FinanceDocRef
    party_name: str | None
    codes: list[str]
    since: datetime | date | None


class ExceptionsRead(BaseModel):
    items: list[FinanceException]
    margin: list[MarginExceptionRead]


# =====================================================================================================
# accounting handoff
# =====================================================================================================
class ExportRequest(BaseModel):
    model_config = _Body

    adapter: AccountingAdapterKind
    period_from: date | None = None
    period_to: date | None = None


class SyncItemRead(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    doc_type: DocType
    document_number: str
    total: Money
    status: SyncStatus
    external_ref: str | None
    acknowledged_total: Money | None
    mismatch_reason: str | None


class ExportRead(BaseModel):
    id: uuid.UUID
    export_number: str
    adapter: AccountingAdapterKind
    status: ExportStatus
    error_code: str | None
    period_from: date | None
    period_to: date | None
    document_count: int
    blocked_count: int
    content_sha256: str | None
    acknowledgement_ref: str | None
    acknowledged_at: datetime | None
    reconciliation_status: ReconciliationStatus
    reconciled_at: datetime | None
    simulated: bool
    actor: FinanceUserRef | None
    created_at: datetime
    items: list[SyncItemRead] = Field(default_factory=list)
    blocked: list[ExportBlocked] = Field(default_factory=list)


class ExportBlocked(BaseModel):
    invoice_id: uuid.UUID
    document_number: str
    reason: str


class AckLine(BaseModel):
    model_config = _Body

    document_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    external_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    total: DecimalStr


class ReconcileRequest(BaseModel):
    """Accounting-side references and totals (CSV adapter: typed in or imported; Demo: taken from the simulated
    acknowledgement when omitted)."""

    model_config = _Body

    lines: list[AckLine] | None = Field(default=None, max_length=1000)


class AccountingStatus(BaseModel):
    integration_key: str
    mode: str
    state: str
    label: str
    adapters: list[str]
    mapping_complete: bool
    missing_mapping: list[str]
    last_export: ExportRead | None
    pending_documents: int


InvoiceDetail.model_rebuild()
InvoiceTransitionResult.model_rebuild()
ExportRead.model_rebuild()
