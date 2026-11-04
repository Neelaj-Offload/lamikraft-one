"""Logistics request and read models (quantities, CBM and weights are ``DecimalStr``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability
from app.core.money import DecimalStr
from app.modules.logistics.enums import (
    EvidenceKind,
    ExceptionCode,
    PackingListStatus,
    ShipmentAction,
    ShipmentMode,
    ShipmentStatus,
    TrackingRefType,
)

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Code = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9][A-Z0-9-]{0,19}$")
]
Positive = Annotated[DecimalStr, Field(gt=0)]


class Versioned(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class DocRef(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    path: str


# ---- packing lists ----------------------------------------------------------------------------------------------
class PackingQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_order_line_id: uuid.UUID
    quantity: Positive


class PackingListCreate(BaseModel):
    """From an order: its open stock lines (remaining quantity), the chosen quantities, or a challan's lines."""

    model_config = ConfigDict(extra="forbid")

    sales_order_id: uuid.UUID
    challan_id: uuid.UUID | None = None
    quantities: list[PackingQuantity] | None = Field(default=None, min_length=1, max_length=200)
    notes: Note | None = None


class LineOverride(BaseModel):
    """Entered values for missing or conflicting packaging data; a reason is required."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    cbm: Positive | None = None
    net_kg: Positive | None = None
    gross_kg: Positive | None = None
    reason: Reason


class PackingLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product_id: uuid.UUID
    product_key: str
    description: str
    quantity: DecimalStr
    unit: str
    carton_qty: int | None
    inner_qty: int | None
    carton_dimensions_cm: str | None
    stated_carton_cbm: DecimalStr | None
    unit_weight_kg: DecimalStr | None
    carton_net_kg: DecimalStr | None
    carton_gross_kg: DecimalStr | None
    packing_type: str | None
    is_fragile: bool
    full_cartons: int | None
    loose_qty: DecimalStr | None
    cartons: int | None
    inner_packs: int | None
    is_part_carton: bool
    carton_cbm: DecimalStr | None
    cbm: DecimalStr | None
    net_kg: DecimalStr | None
    gross_kg: DecimalStr | None
    is_estimate: bool
    incomplete_reasons: list[str]
    override_reason: str | None


class PackingListSummary(BaseModel):
    id: uuid.UUID
    packing_list_number: str
    status: PackingListStatus
    order: DocRef
    party_name: str
    total_cartons: int
    total_cbm: DecimalStr
    total_net_kg: DecimalStr
    total_gross_kg: DecimalStr
    totals_partial: bool
    has_estimates: bool
    is_stale: bool
    created_at: datetime
    path: str
    version: int


class PackingListDetail(PackingListSummary):
    challan: DocRef | None
    stale_since: datetime | None
    stale_reason: str | None
    finalised_at: datetime | None
    notes: str | None
    lines: list[PackingLineRead]
    capabilities: dict[str, Capability]


# ---- shipments ---------------------------------------------------------------------------------------------------
class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_order_id: uuid.UUID | None = None
    challan_id: uuid.UUID | None = None
    packing_list_id: uuid.UUID | None = None
    mode: ShipmentMode
    transporter_party_id: uuid.UUID | None = None
    transporter_name: Name | None = None
    planned_dispatch_date: date | None = None
    #: company-local cutoff; without a time the cutoff is the end of that day's shift (company calendar)
    cutoff_date: date | None = None
    cutoff_time: time | None = None
    notes: Note | None = None


class ShipmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    challan_id: uuid.UUID | None = None
    packing_list_id: uuid.UUID | None = None
    transporter_party_id: uuid.UUID | None = None
    transporter_name: Name | None = None
    planned_dispatch_date: date | None = None
    cutoff_date: date | None = None
    cutoff_time: time | None = None
    notes: Note | None = None


class ShipmentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ShipmentAction
    expected_version: int = Field(ge=1)
    evidence_kind: EvidenceKind | None = None
    evidence_file_id: uuid.UUID | None = None
    evidence_note: Note | None = None
    exception_code: ExceptionCode | None = None
    note: Note | None = None
    reason: Reason | None = None


class TrackingRefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref_type: TrackingRefType
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class TrackingRefRead(BaseModel):
    id: uuid.UUID
    ref_type: TrackingRefType
    value: str


class ShipmentSummary(BaseModel):
    id: uuid.UUID
    shipment_number: str
    status: ShipmentStatus
    mode: ShipmentMode
    party_name: str
    order: DocRef | None
    challan: DocRef | None
    transporter_name: str | None
    planned_dispatch_date: date | None
    cutoff_at: datetime | None
    cutoff_local: str | None
    is_past_cutoff: bool
    path: str
    version: int


class ShipmentDetail(ShipmentSummary):
    packing_list: DocRef | None
    dispatched_at: datetime | None
    dispatch_posting_id: uuid.UUID | None
    delivered_at: datetime | None
    evidence_kind: EvidenceKind | None
    evidence_file_id: uuid.UUID | None
    evidence_note: str | None
    exception_code: ExceptionCode | None
    exception_note: str | None
    exception_at: datetime | None
    notes: str | None
    tracking_refs: list[TrackingRefRead]
    allowed_actions: list[ShipmentAction]
    capabilities: dict[str, Capability]


# ---- containers and load suggestions ---------------------------------------------------------------------------------
class ContainerProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    name: Name
    internal_volume_m3: Positive
    max_payload_kg: Positive
    fill_factor: Annotated[DecimalStr, Field(gt=0, le=1)]


class ContainerProfileRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    internal_volume_m3: DecimalStr
    max_payload_kg: DecimalStr
    fill_factor: DecimalStr
    is_active: bool


class LoadSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packing_list_id: uuid.UUID
    container_profile_id: uuid.UUID


class LoadAllocation(BaseModel):
    line_no: int
    product_key: str
    cartons: int


class SuggestedLoad(BaseModel):
    index: int
    cbm: DecimalStr
    gross_kg: DecimalStr
    volume_utilisation_pct: DecimalStr
    payload_utilisation_pct: DecimalStr
    binding_constraint: str
    allocations: list[LoadAllocation]


class UnplannedLine(BaseModel):
    line_no: int
    reason: str


class LoadSuggestion(BaseModel):
    label: str
    container: ContainerProfileRead
    container_count: int
    loads: list[SuggestedLoad]
    unplanned: list[UnplannedLine]
    manual_review_line_nos: list[int]
    totals_partial: bool
