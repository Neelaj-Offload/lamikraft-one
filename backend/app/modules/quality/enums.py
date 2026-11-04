"""Quality enumerations (varchar + CHECK in the migration; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class InspectionStatus(StrEnum):
    #: waiting: the inspected quantity sits in the warehouse's QC hold
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubjectType(StrEnum):
    #: a goods-receipt line (procurement)
    GOODS_RECEIPT_LINE = "procurement.goods_receipt_line"
    #: a work-order output (subject id = the output transaction; ``work_order_id`` names the work order, FK in 0025)
    WORK_ORDER = "production.work_order"
    #: a customer return on a challan line that went to QC hold
    CHALLAN_LINE = "challans.challan_line"
    #: stock already in QC hold, inspected on its own
    STOCK = "inventory.stock"


class CheckResult(StrEnum):
    PASS = "pass"  # noqa: S105 (a check result, not a secret)
    FAIL = "fail"
    NOT_APPLICABLE = "na"


class RejectDisposition(StrEnum):
    #: rejected stock waits in the warehouse's REJ location (returned to vendor on a return challan, or scrapped)
    HOLD_REJECTED = "hold_rejected"
