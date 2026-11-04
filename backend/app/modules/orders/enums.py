"""Sales order enumerations (varchar + CHECK in the migration; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FulfilmentState(StrEnum):
    NONE = "none"
    PARTIAL = "partial"
    COMPLETE = "complete"


class LineKind(StrEnum):
    CATALOG = "catalog"
    CUSTOM = "custom"
    MANUAL = "manual"
    CHARGE = "charge"


class FulfilmentMode(StrEnum):
    STOCK = "stock"
    MAKE_TO_ORDER = "make_to_order"
    NON_STOCK = "non_stock"


class OrderAction(StrEnum):
    CREATE = "create"
    CONFIRM = "confirm"
    HOLD = "hold"
    RELEASE_HOLD = "release_hold"
    CANCEL = "cancel"
    COMPLETE = "complete"
    CANCEL_LINE = "cancel_line"
    DELIVER = "deliver"
    RETURN = "return"
    REVERSE_DELIVERY = "reverse_delivery"


class HoldReason(StrEnum):
    CREDIT = "credit"
    CUSTOMER_REQUEST = "customer_request"
    STOCK = "stock"
    QUALITY = "quality"
    OTHER = "other"


class CancelReason(StrEnum):
    CUSTOMER_CANCELLED = "customer_cancelled"
    DUPLICATE = "duplicate"
    PRICE = "price"
    STOCK_UNAVAILABLE = "stock_unavailable"
    OTHER = "other"
