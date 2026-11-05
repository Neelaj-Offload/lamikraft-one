"""Finance enumerations (varchar + CHECK in the migration; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class DocType(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ISSUED = "issued"
    CANCELLED = "cancelled"


class InvoiceAction(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    ISSUE = "issue"
    ISSUE_BLOCKED = "issue_blocked"
    CANCEL = "cancel"
    OVERDUE = "overdue"


class TaxStatus(StrEnum):
    #: no tax profile chosen: no tax is calculated and the draft is labelled
    NOT_CONFIGURED = "not_configured"
    #: a profile is chosen but not verified by a second person: tax shown as a labelled draft figure
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class TaxProfileStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"


class ReceiptStatus(StrEnum):
    RECORDED = "recorded"
    REVERSED = "reversed"


class ReceiptMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class AllocationSource(StrEnum):
    RECEIPT = "receipt"
    CREDIT_NOTE = "credit_note"


class SuggestionStatus(StrEnum):
    OPEN = "open"
    DRAFTED = "drafted"
    DISMISSED = "dismissed"


class AccountingAdapterKind(StrEnum):
    CSV = "csv"
    DEMO = "demo"


class ExportStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class SyncStatus(StrEnum):
    PENDING = "pending"
    EXPORTED = "exported"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    MISMATCH = "mismatch"


class ReconciliationStatus(StrEnum):
    NOT_RECONCILED = "not_reconciled"
    MATCHED = "matched"
    MISMATCH = "mismatch"


class MarginExceptionStatus(StrEnum):
    OPEN = "open"
    CLEARED = "cleared"


#: issue-gate blocker codes (plain copy for each lives in the web messages; tested to be stable)
class Blocker(StrEnum):
    NOT_APPROVED = "not_approved"
    APPROVAL_STALE = "approval_stale"
    COMPANY_IDENTITY_INCOMPLETE = "company_identity_incomplete"
    PARTY_BILLING_INCOMPLETE = "party_billing_incomplete"
    TAX_PROFILE_MISSING = "tax_profile_missing"
    TAX_PROFILE_UNVERIFIED = "tax_profile_unverified"
    E_INVOICE_PROVIDER_NOT_VERIFIED = "e_invoice_provider_not_verified"
    TOTALS_CHANGED = "totals_changed"
    QUANTITY_EXCEEDS_DELIVERED = "quantity_exceeds_delivered"
    QUANTITY_EXCEEDS_CREDITABLE = "quantity_exceeds_creditable"
    NO_LINES = "no_lines"
    ZERO_TOTAL = "zero_total"
