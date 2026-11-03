"""Inventory enumerations (varchar + CHECK in the migration, mirrored here; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class LocationType(StrEnum):
    INTERNAL = "internal"
    QC_HOLD = "qc_hold"
    REJECTED = "rejected"
    WIP = "wip"
    OFFICE = "office"
    IN_TRANSIT = "in_transit"
    EXTERNAL_HOLDING = "external_holding"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    PRODUCTION = "production"
    SCRAP = "scrap"
    ADJUSTMENT = "adjustment"
    OPENING = "opening"
    SAMPLE_CONSUMPTION = "sample_consumption"


#: stock-bearing locations hold real goods: their balance can never go below zero
STOCK_BEARING = frozenset(
    {
        LocationType.INTERNAL,
        LocationType.QC_HOLD,
        LocationType.REJECTED,
        LocationType.WIP,
        LocationType.OFFICE,
        LocationType.IN_TRANSIT,
        LocationType.EXTERNAL_HOLDING,
    }
)
#: only internal (warehouse bin) stock counts as available to promise
COUNTS_AVAILABLE = frozenset({LocationType.INTERNAL})
#: one each per company, no warehouse (virtual locations may go negative)
COMPANY_LOCATIONS = (
    LocationType.SUPPLIER,
    LocationType.CUSTOMER,
    LocationType.PRODUCTION,
    LocationType.SCRAP,
    LocationType.ADJUSTMENT,
    LocationType.OPENING,
    LocationType.SAMPLE_CONSUMPTION,
    LocationType.IN_TRANSIT,
)
#: created with every warehouse (code, type, name); STOCK is the default pick/put-away location
WAREHOUSE_LOCATIONS = (
    ("STOCK", LocationType.INTERNAL, "Stock"),
    ("QC", LocationType.QC_HOLD, "QC hold"),
    ("REJ", LocationType.REJECTED, "Rejected"),
)


class LotKind(StrEnum):
    STANDARD = "standard"
    BOARD_LOT = "board_lot"
    OFFCUT = "offcut"


class LotVerification(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class SourceType(StrEnum):
    """What a posting comes from: exactly one posting per (source_type, source_id, purpose)."""

    CHALLAN = "challan"
    ADJUSTMENT = "adjustment"
    STOCK_COUNT = "stock_count"
    OPENING_BATCH = "opening_batch"
    TRANSFER = "transfer"
    RELOCATION = "relocation"
    REVERSAL = "reversal"
    GOODS_RECEIPT = "goods_receipt"
    WORK_ORDER = "work_order"
    QC_INSPECTION = "qc_inspection"


class PostingPurpose(StrEnum):
    ISSUE = "issue"
    RETURN = "return"
    CANCEL = "cancel"
    ADJUST = "adjust"
    COUNT = "count"
    OPENING = "opening"
    DISPATCH = "dispatch"
    RECEIVE = "receive"
    RELOCATE = "relocate"
    REVERSE = "reverse"
    CONSUME = "consume"
    OUTPUT = "output"
    WRITE_OFF = "write_off"
    QC = "qc"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    RELEASED = "released"
    CANCELLED = "cancelled"


class DemandType(StrEnum):
    SO_LINE = "so_line"
    WO_MATERIAL = "wo_material"
    TRANSFER_LINE = "transfer_line"


class ReservePolicy(StrEnum):
    PARTIAL = "partial"
    ALL_OR_NOTHING = "all_or_nothing"


class ShortageStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class PickListStatus(StrEnum):
    DRAFT = "draft"
    RELEASED = "released"
    PICKED = "picked"
    CANCELLED = "cancelled"


class PickLineStatus(StrEnum):
    OPEN = "open"
    PICKED = "picked"
    SHORT = "short"


class CountStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    SUBMITTED = "submitted"
    POSTED = "posted"
    CANCELLED = "cancelled"


class AdjustmentStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    POSTED = "posted"
    REJECTED = "rejected"


class AdjustmentDirection(StrEnum):
    IN = "in"
    OUT = "out"


class AdjustmentReason(StrEnum):
    DAMAGE = "damage"
    LOSS = "loss"
    FOUND = "found"
    CORRECTION = "correction"
    SCRAP = "scrap"
    OTHER = "other"


class OpeningStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    POSTED = "posted"
    REJECTED = "rejected"


class TransferStatus(StrEnum):
    DRAFT = "draft"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    CANCELLED = "cancelled"
