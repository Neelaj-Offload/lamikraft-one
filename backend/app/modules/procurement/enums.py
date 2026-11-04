"""Procurement enumerations (varchar + CHECK in the migration, mirrored here; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class RequisitionStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ISSUED = "issued"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


#: statuses in which the vendor still owes goods (receiving and the overdue sweep look only at these)
PO_OPEN_FOR_RECEIPT = frozenset(
    {PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.ISSUED, PurchaseOrderStatus.PARTIALLY_RECEIVED}
)


class GoodsReceiptStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    CANCELLED = "cancelled"


class VendorBillStatus(StrEnum):
    DRAFT = "draft"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    HANDED_OFF = "handed_off"
    CANCELLED = "cancelled"


class MatchStatus(StrEnum):
    PENDING = "pending"
    MATCHED = "matched"
    QTY_MISMATCH = "qty_mismatch"
    PRICE_VARIANCE = "price_variance"
    AMOUNT_MISMATCH = "amount_mismatch"


class PoTransitionAction(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    ISSUE = "issue"
    CLOSE = "close"
    CANCEL = "cancel"


class RequisitionAction(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    CLOSE = "close"
