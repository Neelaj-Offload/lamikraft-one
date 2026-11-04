"""Procurement request and read models (quantities and money are ``DecimalStr``; money is NUMERIC(18,4) + currency)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability
from app.core.money import DecimalStr
from app.modules.procurement.enums import (
    GoodsReceiptStatus,
    MatchStatus,
    PoTransitionAction,
    PurchaseOrderStatus,
    RequisitionAction,
    RequisitionStatus,
    VendorBillStatus,
)

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{1,39}$")]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]
Currency = Annotated[str, StringConstraints(pattern=r"^(INR|EUR|USD|GBP)$")]
LotCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Positive = Annotated[DecimalStr, Field(gt=0)]


class Versioned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


# ---- references -----------------------------------------------------------------------------------------------
class PartyBrief(BaseModel):
    id: uuid.UUID
    party_number: str
    display_name: str


class ProductBrief(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    stock_unit: str | None
    qc_required: bool
    track_lots: bool


class WarehouseBrief(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class UserBrief(BaseModel):
    id: uuid.UUID
    display_name: str | None


class DocLink(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    path: str


# ---- vendor items ---------------------------------------------------------------------------------------------
class VendorItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_party_id: uuid.UUID
    product_id: uuid.UUID
    vendor_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=730)
    unit_price: Positive
    currency: Currency
    price_uom: Unit | None = None
    min_order_qty: Positive | None = None
    valid_from: date | None = None
    notes: Note | None = None


class VendorItemRead(BaseModel):
    id: uuid.UUID
    vendor: PartyBrief
    product: ProductBrief
    vendor_code: str | None
    lead_time_days: int | None
    unit_price: DecimalStr
    currency: str
    price_uom: str
    min_order_qty: DecimalStr | None
    valid_from: date
    valid_to: date | None
    is_active: bool
    superseded_by_id: uuid.UUID | None
    notes: str | None
    version: int


# ---- requisitions -----------------------------------------------------------------------------------------------
class RequisitionLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: Positive
    unit: Unit | None = None
    required_by: date | None = None
    suggested_vendor_item_id: uuid.UUID | None = None
    demand_ref_type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_.]{1,59}$")] | None = None
    demand_ref_id: uuid.UUID | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class RequisitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: uuid.UUID
    required_by: date | None = None
    notes: Note | None = None
    lines: list[RequisitionLineIn] = Field(min_length=1, max_length=200)


class RequisitionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: RequisitionAction
    expected_version: int = Field(ge=1)
    note: Reason | None = None


class RequisitionLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product: ProductBrief
    quantity: DecimalStr
    unit: str
    required_by: date | None
    qty_ordered: DecimalStr
    qty_remaining: DecimalStr
    suggested_vendor_item_id: uuid.UUID | None
    demand_ref_type: str | None
    demand_ref_id: uuid.UUID | None
    notes: str | None


class RequisitionSummary(BaseModel):
    id: uuid.UUID
    requisition_number: str
    status: RequisitionStatus
    warehouse: WarehouseBrief
    owner: UserBrief
    required_by: date | None
    line_count: int
    created_at: datetime
    path: str
    version: int


class RequisitionDetail(RequisitionSummary):
    notes: str | None
    submitted_at: datetime | None
    submitted_by: UserBrief | None
    decided_at: datetime | None
    decided_by: UserBrief | None
    decision_note: str | None
    lines: list[RequisitionLineRead]
    purchase_orders: list[DocLink]
    capabilities: dict[str, Capability]


class ConvertToPo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    vendor_party_id: uuid.UUID
    #: requisition line id -> unit price (when no active vendor item gives one)
    unit_prices: dict[uuid.UUID, Positive] = Field(default_factory=dict)
    line_ids: list[uuid.UUID] | None = None


# ---- purchase orders ----------------------------------------------------------------------------------------------
class PoLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: Positive
    unit: Unit | None = None
    #: defaults to the active vendor item's price; a different price needs ``price_override_reason``
    unit_price: Annotated[DecimalStr, Field(ge=0)] | None = None
    price_override_reason: Reason | None = None
    expected_date: date | None = None
    over_receipt_tolerance_pct: Annotated[DecimalStr, Field(ge=0, le=100)] | None = None
    requisition_line_id: uuid.UUID | None = None


class PoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_party_id: uuid.UUID
    warehouse_id: uuid.UUID
    currency: Currency | None = None
    vendor_reference: Ref | None = None
    notes: Note | None = None
    lines: list[PoLineIn] = Field(min_length=1, max_length=200)


class PoUpdate(BaseModel):
    """Draft edits replace the lines; header fields are optional."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    vendor_reference: Ref | None = None
    notes: Note | None = None
    lines: list[PoLineIn] | None = Field(default=None, min_length=1, max_length=200)


class PoTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PoTransitionAction
    expected_version: int = Field(ge=1)
    reason_code: ReasonCode | None = None
    reason: Reason | None = None


class ExpectedDateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    expected_date: date
    reason: Reason | None = None


class LineCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    quantity: Positive
    reason: Reason


class PoLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product: ProductBrief
    quantity: DecimalStr
    unit: str
    unit_price: DecimalStr
    price_override_reason: str | None
    line_amount: DecimalStr
    lead_time_days_assumed: int | None
    expected_date: date
    is_overdue: bool
    over_receipt_tolerance_pct: DecimalStr
    qty_received: DecimalStr
    qty_accepted: DecimalStr
    qty_rejected: DecimalStr
    qty_pending_qc: DecimalStr
    qty_cancelled: DecimalStr
    qty_billed: DecimalStr
    #: accepted and not yet billed (what a new vendor bill may cover)
    qty_billable: DecimalStr
    qty_outstanding: DecimalStr
    #: what one more receipt may still bring in (tolerance included)
    qty_receivable: DecimalStr
    requisition_line_id: uuid.UUID | None
    version: int


class PoSummary(BaseModel):
    id: uuid.UUID
    po_number: str
    status: PurchaseOrderStatus
    vendor: PartyBrief
    warehouse: WarehouseBrief
    owner: UserBrief
    currency: str
    total_amount: DecimalStr
    order_date: date
    next_expected_date: date | None
    is_overdue: bool
    path: str
    version: int


class PoDetail(PoSummary):
    vendor_reference: str | None
    notes: str | None
    requisition: DocLink | None
    submitted_by: UserBrief | None
    submitted_at: datetime | None
    approved_by: UserBrief | None
    approved_at: datetime | None
    issued_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    status_reason_code: str | None
    status_reason: str | None
    lines: list[PoLineRead]
    receipts: list[DocLink]
    bills: list[DocLink]
    allowed_transitions: list[PoTransitionAction]
    capabilities: dict[str, Capability]


# ---- goods receipts -----------------------------------------------------------------------------------------------------
class GrnLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_line_id: uuid.UUID
    quantity: Positive
    unit: Unit | None = None
    lot_code: LotCode | None = None
    supplier_lot_ref: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    #: a stock bin of the receiving warehouse (QC-required products always go to QC hold)
    location_id: uuid.UUID | None = None


class GrnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_id: uuid.UUID
    #: defaults to the PO's destination warehouse
    warehouse_id: uuid.UUID | None = None
    received_on: date | None = None
    vendor_challan_ref: Ref | None = None
    vendor_invoice_ref: Ref | None = None
    notes: Note | None = None
    lines: list[GrnLineIn] = Field(min_length=1, max_length=200)
    #: post immediately (one command for the common case)
    post: bool = False


class GrnLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    po_line_id: uuid.UUID
    po_line_no: int
    product: ProductBrief
    quantity: DecimalStr
    unit: str
    lot_code: str | None
    supplier_lot_ref: str | None
    lot_id: uuid.UUID | None
    location_code: str | None
    qc_required: bool
    inspection: DocLink | None


class GrnSummary(BaseModel):
    id: uuid.UUID
    grn_number: str
    status: GoodsReceiptStatus
    purchase_order: DocLink
    vendor: PartyBrief
    warehouse: WarehouseBrief
    received_on: date
    line_count: int
    awaiting_qc: int
    path: str
    version: int


class GrnDetail(GrnSummary):
    vendor_challan_ref: str | None
    vendor_invoice_ref: str | None
    notes: str | None
    posting_id: uuid.UUID | None
    posted_at: datetime | None
    posted_by: UserBrief | None
    lines: list[GrnLineRead]
    capabilities: dict[str, Capability]


# ---- vendor bills -----------------------------------------------------------------------------------------------------
class BillLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_line_id: uuid.UUID
    quantity: Positive
    unit_price: Annotated[DecimalStr, Field(ge=0)]
    goods_receipt_line_id: uuid.UUID | None = None


class BillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_id: uuid.UUID
    bill_number: Ref
    bill_date: date
    subtotal_amount: Annotated[DecimalStr, Field(ge=0)]
    tax_amount: Annotated[DecimalStr, Field(ge=0)] = Decimal(0)
    total_amount: Annotated[DecimalStr, Field(ge=0)]
    notes: Note | None = None
    lines: list[BillLineIn] = Field(min_length=1, max_length=200)


class MatchException(BaseModel):
    code: Literal["qty_mismatch", "price_variance", "amount_mismatch", "pending_qc", "currency_mismatch"]
    po_line_id: uuid.UUID | None = None
    line_no: int | None = None
    expected: DecimalStr | None = None
    actual: DecimalStr | None = None


class BillLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    po_line_id: uuid.UUID
    po_line_no: int
    product: ProductBrief
    quantity: DecimalStr
    unit_price: DecimalStr
    line_amount: DecimalStr
    po_unit_price: DecimalStr
    qty_accepted: DecimalStr
    qty_billed_before: DecimalStr


class BillRead(BaseModel):
    id: uuid.UUID
    bill_number: str
    bill_date: date
    vendor: PartyBrief
    purchase_order: DocLink
    currency: str
    subtotal_amount: DecimalStr
    tax_amount: DecimalStr
    total_amount: DecimalStr
    computed_subtotal: DecimalStr
    status: VendorBillStatus
    match_status: MatchStatus
    match_exceptions: list[MatchException]
    matched_at: datetime | None
    handed_off_at: datetime | None
    notes: str | None
    lines: list[BillLineRead]
    capabilities: dict[str, Capability]
    version: int
