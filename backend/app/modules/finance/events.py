"""Finance events (docs/architecture/events.md §3.11), sequences and settings.

Payloads carry ids, numbers, enum codes and dates only (never amounts, quantities, margins or bank details).
Numbering follows the April financial year (BUILD_STATE decision 1/14): ``INV-2026-27-0001``; drafts carry a
``FD-NNNNN`` reference that never consumes an invoice number.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.platform.numbering.defs import SequenceDef
from app.platform.org.settings import SettingDef

DRAFT_CREATED = "finance.invoice.draft_created"
SUBMITTED = "finance.invoice.submitted"
APPROVED = "finance.invoice.approved"
REJECTED = "finance.invoice.rejected"
CANCELLED = "finance.invoice.cancelled"
ISSUE_BLOCKED = "finance.invoice.issue_blocked"
ISSUED = "finance.invoice.issued"
BECAME_OVERDUE = "finance.invoice.became_overdue"
CREDIT_NOTE_ISSUED = "finance.credit_note.issued"
RECEIPT_RECORDED = "finance.receipt.recorded"
RECEIPT_REVERSED = "finance.receipt.reversed"
RECEIPT_UNALLOCATED = "finance.receipt.unallocated_detected"
ALLOCATION_CREATED = "finance.allocation.created"
ALLOCATION_REVERSED = "finance.allocation.reversed"
SUGGESTION_CREATED = "finance.invoice_suggestion.created"
SUGGESTION_DISMISSED = "finance.invoice_suggestion.dismissed"
EXPORT_COMPLETED = "finance.accounting_export.completed"
EXPORT_FAILED = "finance.accounting_export.failed"
EXPORT_RECONCILED = "finance.accounting_export.reconciled"
TAX_PROFILE_VERIFIED = "finance.tax_profile.verified"
MARGIN_BELOW_THRESHOLD = "sales.quote.margin_below_threshold"

EMITTED_EVENTS: tuple[str, ...] = (
    DRAFT_CREATED,
    SUBMITTED,
    APPROVED,
    REJECTED,
    CANCELLED,
    ISSUE_BLOCKED,
    ISSUED,
    BECAME_OVERDUE,
    CREDIT_NOTE_ISSUED,
    RECEIPT_RECORDED,
    RECEIPT_REVERSED,
    RECEIPT_UNALLOCATED,
    ALLOCATION_CREATED,
    ALLOCATION_REVERSED,
    SUGGESTION_CREATED,
    SUGGESTION_DISMISSED,
    EXPORT_COMPLETED,
    EXPORT_FAILED,
    EXPORT_RECONCILED,
    TAX_PROFILE_VERIFIED,
    MARGIN_BELOW_THRESHOLD,
)

#: consumer handler keys (events.md §2)
SUGGESTION_HANDLER = "finance.invoice_suggestion"
MARGIN_HANDLER = "finance.margin_check"
#: the challan event that suggests invoices; the quote events that trigger a margin check
SUGGESTION_TRIGGERS: tuple[str, ...] = ("challans.challan.issued",)
MARGIN_TRIGGERS: tuple[str, ...] = ("sales.quote.issued",)

SEQUENCES = [
    SequenceDef(
        key="finance.invoice",
        name="Invoice number (issued only)",
        format_template="INV-{fy}-{seq:04}",
        reset_policy="financial_year",
        resource_type="finance.invoice",
    ),
    SequenceDef(
        key="finance.credit_note",
        name="Credit note number (issued only)",
        format_template="CN-{fy}-{seq:04}",
        reset_policy="financial_year",
        resource_type="finance.invoice",
    ),
    SequenceDef(
        key="finance.draft",
        name="Finance draft reference",
        format_template="FD-{seq:05}",
        reset_policy="never",
        resource_type="finance.invoice",
    ),
    SequenceDef(
        key="finance.receipt",
        name="Receipt number",
        format_template="RCPT-{fy}-{seq:04}",
        reset_policy="financial_year",
        resource_type="finance.receipt",
    ),
    SequenceDef(
        key="finance.accounting_export",
        name="Accounting export batch",
        format_template="AX-{fy}-{seq:04}",
        reset_policy="financial_year",
        resource_type="finance.accounting_export",
    ),
]


class FinancePolicy(BaseModel):
    """Finance defaults (Demo defaults until the owner confirms them; BUILD_STATE §5)."""

    model_config = ConfigDict(extra="forbid")

    #: due date = document date + this many days unless the draft says otherwise
    default_payment_due_days: int = Field(default=30, ge=0, le=365)
    #: quotes whose margin from costs of record is below this percentage become margin exceptions
    margin_threshold_percent: Decimal = Field(default=Decimal("15"), ge=0, le=100)
    #: a receipt still (partly) unallocated this many days after it was received is flagged once
    unallocated_after_days: int = Field(default=3, ge=0, le=90)


class AccountMapping(BaseModel):
    """Account codes the journal export writes (the business's chart of accounts lives in its accounting system).
    A missing code blocks the documents that need it; nothing is invented."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    receivable_account: str | None = Field(default=None, max_length=40)
    sales_account: str | None = Field(default=None, max_length=40)
    tax_account: str | None = Field(default=None, max_length=40)
    sales_returns_account: str | None = Field(default=None, max_length=40)


FINANCE_POLICY = SettingDef(
    key="finance_policy",
    model=FinancePolicy,
    description="Finance defaults: payment due days, the margin threshold, the unallocated-receipt flag",
    read_permission="org.settings.read",
    manage_permission="finance.configuration.manage",
    owner_module="finance",
)
ACCOUNT_MAPPING = SettingDef(
    key="finance_account_mapping",
    model=AccountMapping,
    description="Account codes used by the accounting journal export",
    read_permission="org.settings.read",
    manage_permission="finance.configuration.manage",
    owner_module="finance",
)
SETTINGS = [FINANCE_POLICY, ACCOUNT_MAPPING]
