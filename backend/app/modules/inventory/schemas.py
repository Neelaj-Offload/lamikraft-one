"""Inventory request and read models (quantities are ``DecimalStr`` in the product's stock unit unless noted)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability
from app.core.money import DecimalStr
from app.modules.inventory.enums import (
    AdjustmentDirection,
    AdjustmentReason,
    AdjustmentStatus,
    CountStatus,
    LocationType,
    LotKind,
    OpeningStatus,
    PickListStatus,
    ReservationStatus,
    TransferStatus,
)

Code = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9-]{0,19}$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{1,39}$")]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


# ---- references -----------------------------------------------------------------------------------------
class WarehouseRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class LocationRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    location_type: LocationType
    warehouse_id: uuid.UUID | None


class ProductRef(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    stock_unit: str | None
    track_lots: bool


class LotRef(BaseModel):
    id: uuid.UUID
    lot_code: str
    lot_kind: LotKind


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


# ---- warehouses and locations -----------------------------------------------------------------------------
class WarehouseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    name: Name
    branch_id: uuid.UUID | None = None
    address: Note | None = None


class BinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    name: Name | None = None


class WarehouseRead(WarehouseRef):
    branch_id: uuid.UUID | None
    address: str | None
    is_active: bool
    locations: list[LocationRef]
    capabilities: dict[str, Capability]


class LotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    lot_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    lot_kind: LotKind = LotKind.STANDARD
    supplier_lot_ref: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


class LotMeasure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length_mm: DecimalStr = Field(gt=0)
    width_mm: DecimalStr = Field(gt=0)
    thickness_mm: DecimalStr | None = Field(default=None, gt=0)
    grain_axis: Literal["length", "width", "none"] | None = None


class LotRead(LotRef):
    product: ProductRef
    supplier_lot_ref: str | None
    length_mm: DecimalStr | None
    width_mm: DecimalStr | None
    thickness_mm: DecimalStr | None
    grain_axis: str | None
    verification_status: str
    on_hand: DecimalStr


# ---- positions and availability -------------------------------------------------------------------------------
class StockRow(BaseModel):
    """One product at one warehouse: available stock is company-owned stock in the warehouse's bins."""

    product: ProductRef
    warehouse: WarehouseRef
    on_hand: DecimalStr
    reserved: DecimalStr
    available: DecimalStr
    qc_hold: DecimalStr
    rejected: DecimalStr
    unit: str | None
    shortage: DecimalStr | None
    reorder_min: DecimalStr | None
    below_reorder: bool
    version: int


class StockTotals(BaseModel):
    products: int
    short_products: int
    below_reorder: int


class StockPage(BaseModel):
    items: list[StockRow]
    total: int
    limit: int
    offset: int
    totals: StockTotals


class BalanceRead(BaseModel):
    location: LocationRef
    lot: LotRef | None
    owner_party_id: uuid.UUID | None
    owner_name: str | None
    quantity: DecimalStr
    last_movement_at: datetime | None


class ProductPosition(BaseModel):
    """Where a product is: by warehouse and location, plus external holdings, in transit and party-owned stock."""

    product: ProductRef
    unit: str | None
    warehouses: list[StockRow]
    balances: list[BalanceRead]
    external: DecimalStr
    in_transit: DecimalStr


class Availability(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    on_hand: DecimalStr
    reserved: DecimalStr
    available: DecimalStr
    unit: str | None


# ---- ledger ---------------------------------------------------------------------------------------------------
class MovementRead(BaseModel):
    id: uuid.UUID
    seq: int
    posting_id: uuid.UUID
    line_no: int
    product: ProductRef
    lot: LotRef | None
    from_location: LocationRef
    to_location: LocationRef
    quantity: DecimalStr
    unit: str
    entered_quantity: DecimalStr
    entered_unit: str
    owner_party_id: uuid.UUID | None
    counterparty_party_id: uuid.UUID | None
    reservation_id: uuid.UUID | None
    source_type: str
    source_id: uuid.UUID
    source_label: str | None
    source_path: str | None
    purpose: str
    posted_at: datetime
    is_reversal: bool


class MovementPage(BaseModel):
    items: list[MovementRead]
    total: int
    limit: int
    offset: int


class PostingRead(BaseModel):
    id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    source_label: str | None
    source_path: str | None
    purpose: str
    reason_code: str | None
    reason: str | None
    posted_at: datetime
    posted_by: UserRef | None
    reverses_posting_id: uuid.UUID | None
    reversed_by_posting_id: uuid.UUID | None
    movements: list[MovementRead]
    capabilities: dict[str, Capability]


class ReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: ReasonCode
    reason: Reason | None = None


class RelocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: DecimalStr = Field(gt=0)
    unit: Unit
    lot_id: uuid.UUID | None = None


# ---- reservations and shortages -------------------------------------------------------------------------------
class ReservationRead(BaseModel):
    id: uuid.UUID
    product: ProductRef
    warehouse: WarehouseRef
    quantity: DecimalStr
    consumed: DecimalStr
    released: DecimalStr
    remaining: DecimalStr
    unit: str
    status: ReservationStatus
    demand_type: str
    demand_id: uuid.UUID
    demand_parent_id: uuid.UUID | None
    demand_label: str | None
    demand_path: str | None
    created_at: datetime
    released_at: datetime | None
    capabilities: dict[str, Capability]


class ReservationPage(BaseModel):
    items: list[ReservationRead]
    total: int
    limit: int
    offset: int


class ReservationRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: DecimalStr | None = Field(default=None, gt=0)
    reason_code: ReasonCode = "manual_release"


class CauseRef(BaseModel):
    type: str
    id: uuid.UUID
    label: str | None
    path: str | None


class ShortageRead(BaseModel):
    id: uuid.UUID
    product: ProductRef
    warehouse: WarehouseRef
    status: str
    demand: DecimalStr
    free: DecimalStr
    shortfall: DecimalStr
    unit: str | None
    caused_by: list[CauseRef]
    version: int
    detected_at: datetime
    resolved_at: datetime | None


# ---- documents ------------------------------------------------------------------------------------------------
class DocLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: DecimalStr = Field(gt=0)
    unit: Unit | None = None
    location_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None


class AdjustmentLineIn(DocLineIn):
    direction: AdjustmentDirection


class AdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: uuid.UUID
    reason_code: AdjustmentReason
    reason: Reason | None = None
    notes: Note | None = None
    lines: list[AdjustmentLineIn] = Field(min_length=1, max_length=200)


class DocLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product: ProductRef
    location: LocationRef | None
    lot: LotRef | None
    quantity: DecimalStr
    unit: str
    direction: AdjustmentDirection | None = None
    lot_code: str | None = None
    late_opening: bool | None = None


class DocumentRead(BaseModel):
    """An adjustment, opening batch or transfer: header, lines, decision trail and what the caller may do."""

    id: uuid.UUID
    kind: Literal["adjustment", "opening_batch", "transfer"]
    number: str
    status: str
    warehouse: WarehouseRef
    to_warehouse: WarehouseRef | None = None
    reason_code: str | None = None
    reason: str | None = None
    notes: str | None
    created_by: UserRef | None
    created_at: datetime
    decided_by: UserRef | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    posting_id: uuid.UUID | None
    second_posting_id: uuid.UUID | None = None
    lines: list[DocLineRead]
    version: int
    capabilities: dict[str, Capability]


class DocumentSummary(BaseModel):
    id: uuid.UUID
    kind: Literal["adjustment", "opening_batch", "transfer", "stock_count", "pick_list"]
    number: str
    status: str
    warehouse: WarehouseRef
    line_count: int
    created_by: UserRef | None
    created_at: datetime
    path: str


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    note: Reason | None = None


class Versioned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int


class OpeningLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: DecimalStr = Field(gt=0)
    unit: Unit | None = None
    location_id: uuid.UUID | None = None
    lot_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = (
        None
    )
    source_row_ref: Annotated[str, StringConstraints(max_length=60)] | None = None
    late_opening: bool = False


class OpeningBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: uuid.UUID
    notes: Note | None = None
    source_file_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    lines: list[OpeningLineIn] = Field(min_length=1, max_length=500)


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    notes: Note | None = None
    lines: list[DocLineIn] = Field(min_length=1, max_length=200)


# ---- stock counts -----------------------------------------------------------------------------------------
class CountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: uuid.UUID
    location_id: uuid.UUID | None = None
    notes: Note | None = None


class CountEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    counted_quantity: DecimalStr = Field(ge=0)


class CountEntries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    entries: list[CountEntry] = Field(min_length=1, max_length=500)


class CountLineAdd(BaseModel):
    """A product found during the count that the snapshot did not list (system quantity 0)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    product_id: uuid.UUID
    location_id: uuid.UUID
    lot_id: uuid.UUID | None = None
    counted_quantity: DecimalStr = Field(ge=0)


class CountLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product: ProductRef
    location: LocationRef
    lot: LotRef | None
    system_quantity: DecimalStr
    counted_quantity: DecimalStr | None
    variance: DecimalStr | None
    unit: str


class CountRead(BaseModel):
    id: uuid.UUID
    number: str
    status: CountStatus
    warehouse: WarehouseRef
    location: LocationRef | None
    snapshot_seq: int | None
    frozen_at: datetime | None
    frozen_by: UserRef | None
    submitted_by: UserRef | None
    approved_by: UserRef | None
    approved_at: datetime | None
    posting_id: uuid.UUID | None
    notes: str | None
    lines: list[CountLineRead]
    counted_lines: int
    variance_lines: int
    created_at: datetime
    created_by: UserRef | None
    version: int
    capabilities: dict[str, Capability]


# ---- pick lists -------------------------------------------------------------------------------------------------
class PickListCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    assignee_user_id: uuid.UUID | None = None


class PickEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    picked_quantity: DecimalStr = Field(ge=0)


class PickConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    entries: list[PickEntry] = Field(min_length=1, max_length=200)


class PickLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    order_line_id: uuid.UUID
    reservation_id: uuid.UUID
    product: ProductRef
    location: LocationRef
    lot: LotRef | None
    requested: DecimalStr
    picked: DecimalStr | None
    unit: str
    status: str


class PickListRead(BaseModel):
    id: uuid.UUID
    number: str
    status: PickListStatus
    warehouse: WarehouseRef
    order_id: uuid.UUID
    order_number: str
    assignee: UserRef | None
    released_at: datetime | None
    picked_at: datetime | None
    challan_id: uuid.UUID | None
    challan_number: str | None
    lines: list[PickLineRead]
    created_at: datetime
    version: int
    capabilities: dict[str, Capability]


# ---- reorder rules -------------------------------------------------------------------------------------------
class ReorderRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    min_quantity: DecimalStr = Field(ge=0)
    max_quantity: DecimalStr = Field(ge=0)
    reorder_quantity: DecimalStr = Field(gt=0)
    is_active: bool = True


class ReorderRuleRead(BaseModel):
    id: uuid.UUID
    product: ProductRef
    warehouse: WarehouseRef
    min_quantity: DecimalStr
    max_quantity: DecimalStr
    reorder_quantity: DecimalStr
    is_active: bool
    available: DecimalStr
    below_min: bool
    suggested_quantity: DecimalStr
    version: int


__all__ = [
    "AdjustmentStatus",
    "CountStatus",
    "OpeningStatus",
    "PickListStatus",
    "TransferStatus",
]
