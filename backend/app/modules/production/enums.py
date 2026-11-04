"""Production enumerations (varchar + CHECK in the migration, mirrored here; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class WorkCenterKind(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class MasterStatus(StrEnum):
    """BOM and routing versions: a draft is edited by its author, approved by someone else, later retired."""

    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class WorkOrderStatus(StrEnum):
    DRAFT = "draft"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class RequirementSource(StrEnum):
    BOM = "bom"
    CUT_PLAN = "cut_plan"


class OperationStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"


class TransactionKind(StrEnum):
    """One row per stock event of a work order; its id is the posting source id (one posting per event)."""

    ISSUE = "issue"
    CONSUME = "consume"
    RETURN = "return"
    OUTPUT = "output"
    OFFCUT = "offcut"


class CostRollupStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class OverloadStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class FeasibilityOutcome(StrEnum):
    FEASIBLE = "feasible"
    AT_RISK = "at_risk"
    NOT_FEASIBLE = "not_feasible"
    ESTIMATE = "estimate"


class CancelReason(StrEnum):
    NOT_NEEDED = "not_needed"
    ORDER_CANCELLED = "order_cancelled"
    REPLANNED = "replanned"
    DATA_ERROR = "data_error"
    OTHER = "other"


#: posting purpose per transaction kind (the inventory ``PostingPurpose`` values)
POSTING_PURPOSE = {
    TransactionKind.ISSUE: "issue",
    TransactionKind.CONSUME: "consume",
    TransactionKind.RETURN: "return",
    TransactionKind.OUTPUT: "output",
    TransactionKind.OFFCUT: "output",
}
