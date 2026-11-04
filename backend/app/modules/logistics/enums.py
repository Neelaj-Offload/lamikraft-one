"""Logistics enumerations (varchar + CHECK in the migration; contract-tested)."""

from __future__ import annotations

from enum import StrEnum


class PackingListStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    PLANNED = "planned"
    BOOKED = "booked"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class ShipmentMode(StrEnum):
    ROAD = "road"
    SEA = "sea"
    AIR = "air"
    COURIER = "courier"
    HAND = "hand"


class ShipmentAction(StrEnum):
    BOOK = "book"
    DISPATCH = "dispatch"
    IN_TRANSIT = "in_transit"
    DELIVER = "deliver"
    RECORD_EXCEPTION = "record_exception"
    RESOLVE_EXCEPTION = "resolve_exception"
    CANCEL = "cancel"


class EvidenceKind(StrEnum):
    SIGNED_POD = "signed_pod"
    PHOTO = "photo"
    COURIER_CONFIRMATION = "courier_confirmation"
    CUSTOMER_CONFIRMATION = "customer_confirmation"


class ExceptionCode(StrEnum):
    DELAYED = "delayed"
    DAMAGED = "damaged"
    LOST = "lost"
    REFUSED = "refused"
    ADDRESS_ISSUE = "address_issue"
    OTHER = "other"


class TrackingRefType(StrEnum):
    AWB = "awb"
    BL = "bl"
    LR = "lr"
    CONTAINER = "container"
    SEAL = "seal"
    OTHER = "other"
