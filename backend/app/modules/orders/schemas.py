"""Sales order request and read models (quantities and money are strings: ``DecimalStr`` / ``Money``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import DecimalStr, Money
from app.modules.inventory.enums import ReservePolicy
from app.modules.orders.enums import (
    CancelReason,
    FulfilmentMode,
    FulfilmentState,
    HoldReason,
    LineKind,
    OrderStatus,
)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class OrderUserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class OrderPartyRef(BaseModel):
    id: uuid.UUID
    party_number: str | None
    display_name: str


class OrderQuoteRef(BaseModel):
    id: uuid.UUID
    quote_number: str
    revision_no: int


class OrderWarehouseRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SalesOrderSummary(BaseModel):
    id: uuid.UUID
    order_number: str
    order_date: date
    party: OrderPartyRef
    quote: OrderQuoteRef
    status: OrderStatus
    fulfilment_state: FulfilmentState
    total: Money | None
    line_count: int
    requested_delivery_date: date | None
    promised_date: date | None
    owner: OrderUserRef
    branch_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    path: str


class OrderLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    line_kind: LineKind
    fulfilment_mode: FulfilmentMode
    product_id: uuid.UUID | None
    product_key: str | None
    description: str
    unit: str
    unit_price: Money | None
    line_total: Money | None
    qty_ordered: DecimalStr
    #: active reservations, converted back to the line unit
    qty_reserved: DecimalStr
    qty_delivered: DecimalStr
    qty_returned: DecimalStr
    qty_cancelled: DecimalStr
    qty_remaining: DecimalStr
    #: remaining quantity not yet covered by a reservation (stock lines)
    qty_unreserved: DecimalStr
    cancel_reason_code: str | None
    version: int


class OrderReservationRead(BaseModel):
    id: uuid.UUID
    line_id: uuid.UUID
    warehouse: OrderWarehouseRef
    quantity: DecimalStr
    remaining: DecimalStr
    unit: str
    status: str
    created_at: datetime


class OrderHistoryRead(BaseModel):
    action: str
    from_status: str
    to_status: str
    line_id: uuid.UUID | None
    actor: OrderUserRef | None
    reason_code: str | None
    reason: str | None
    reference: str | None
    occurred_at: datetime


class OrderDocumentRef(BaseModel):
    kind: Literal["challan", "pick_list"]
    id: uuid.UUID
    number: str
    status: str
    path: str


class SalesOrderDetail(SalesOrderSummary):
    currency: str
    subtotal: Money
    surcharge: Money
    terms: dict[str, object]
    snapshot_hash: str
    default_warehouse: OrderWarehouseRef | None
    ship_to: str | None
    customer_reference: str | None
    confirmed_at: datetime | None
    hold_reason_code: str | None
    hold_reason: str | None
    cancelled_at: datetime | None
    cancel_reason_code: str | None
    cancel_reason: str | None
    completed_at: datetime | None
    lines: list[OrderLineRead]
    reservations: list[OrderReservationRead]
    documents: list[OrderDocumentRef]
    history: list[OrderHistoryRead]
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


class ConversionResult(BaseModel):
    created: bool
    order: SalesOrderDetail


class OrderFilters(BaseModel):
    q: str | None = None
    status: list[OrderStatus] | None = None
    fulfilment_state: list[FulfilmentState] | None = None
    party_id: uuid.UUID | None = None
    source_quote_id: uuid.UUID | None = None
    scope: Literal["mine", "all"] = "all"


class OrderUpdate(BaseModel):
    """Logistics fields only: commercial fields come from the accepted revision and never change on the order."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    requested_delivery_date: date | None = None
    promised_date: date | None = None
    default_warehouse_id: uuid.UUID | None = None
    ship_to: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class OrderTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "hold", "release_hold", "cancel"]
    expected_version: int
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{1,39}$")] | None = None
    reason: Reason | None = None


class LineCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    #: in the line unit; default: everything still remaining
    quantity: DecimalStr | None = Field(default=None, gt=0)
    reason_code: CancelReason
    reason: Reason | None = None


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: default: every stock line with an unreserved remainder
    line_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    policy: ReservePolicy = ReservePolicy.PARTIAL
    warehouse_id: uuid.UUID | None = None


class LineReserveOutcome(BaseModel):
    line_id: uuid.UUID
    requested: DecimalStr
    granted: DecimalStr
    shortfall: DecimalStr
    unit: str


class ReserveResponse(BaseModel):
    order: SalesOrderDetail
    outcomes: list[LineReserveOutcome]


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{1,39}$")] = "manual_release"


class ChallanFromOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: line id -> quantity in the line unit; default: the reserved (else remaining) quantity of every stock line
    quantities: dict[uuid.UUID, DecimalStr] | None = None
    warehouse_id: uuid.UUID | None = None


class ImpactLine(BaseModel):
    line_id: uuid.UUID
    product_key: str | None
    unit: str
    remaining: DecimalStr
    reserved: DecimalStr
    available_now: DecimalStr | None
    outcome: Literal["covered", "partial", "short", "not_stock"]
    shortfall: DecimalStr


class ImpactPreview(BaseModel):
    order_id: uuid.UUID
    warehouse: OrderWarehouseRef | None
    lines: list[ImpactLine]


HoldReasonCode = HoldReason
