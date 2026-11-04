"""Production request and read models. Quantities, minutes and money travel as strings (``DecimalStr`` / ``Money``).

Cost figures (work-centre rates, rollup amounts and lines) are guarded fields: ``COST_GUARD`` =
``Restricted("pricing.cost.read", model_exposure="deny")`` nulls them for actors without the key and removes them
from every model-facing payload even for permitted users.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.http.capabilities import Capability, TransitionRead
from app.core.money import DecimalStr, Money
from app.modules.pricing.schemas import COST_GUARD
from app.modules.production.enums import (
    CancelReason,
    CostRollupStatus,
    FeasibilityOutcome,
    MasterStatus,
    OperationStatus,
    RequirementSource,
    TransactionKind,
    WorkCenterKind,
    WorkOrderStatus,
)

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9._-]+$")]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


def _positive(v: Decimal) -> Decimal:
    if v <= 0:
        raise ValueError("must be greater than zero")
    return v


def _non_negative(v: Decimal) -> Decimal:
    if v < 0:
        raise ValueError("must not be negative")
    return v


# ---- refs ----------------------------------------------------------------------------------------------------------
class ProductionUserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


class ProductionProductRef(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    stock_uom_code: str | None


class ProductionWarehouseRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class WorkCenterRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class CauseRef(BaseModel):
    """A ``caused_by`` reference (shortage, cut plan) with a label for the reader."""

    type: str
    id: uuid.UUID
    label: str | None = None
    path: str | None = None


# ---- work centres ----------------------------------------------------------------------------------------------------
class WorkCenterCreate(BaseModel):
    code: Code
    name: Text200
    kind: WorkCenterKind = WorkCenterKind.INTERNAL
    calendar_id: uuid.UUID | None = None
    machine_count: int = Field(default=1, ge=1, le=500)
    efficiency_pct: DecimalStr = Decimal(100)
    rate_per_hour: Money | None = None
    job_work_party_id: uuid.UUID | None = None
    notes: Notes | None = None

    @field_validator("efficiency_pct")
    @classmethod
    def _eff(cls, v: Decimal) -> Decimal:
        if not (0 < v <= 100):
            raise ValueError("efficiency is a percentage above 0 and at most 100")
        return v


class WorkCenterUpdate(BaseModel):
    expected_version: int
    name: Text200 | None = None
    calendar_id: uuid.UUID | None = None
    machine_count: int | None = Field(default=None, ge=1, le=500)
    efficiency_pct: DecimalStr | None = None
    rate_per_hour: Money | None = None
    clear_rate: bool = False
    is_active: bool | None = None
    notes: Notes | None = None

    @field_validator("efficiency_pct")
    @classmethod
    def _eff(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not (0 < v <= 100):
            raise ValueError("efficiency is a percentage above 0 and at most 100")
        return v


class CapacityExceptionIn(BaseModel):
    exception_date: date
    available_minutes: int = Field(ge=0, le=1_440_000)
    reason: Text200


class CapacityExceptionRead(BaseModel):
    id: uuid.UUID
    exception_date: date
    available_minutes: int
    reason: str


class CalendarRef(BaseModel):
    id: uuid.UUID | None
    code: str
    name: str
    source: Literal["work_centre", "company_default", "built_in"]


class ShiftMinutes(BaseModel):
    code: str
    name: str
    start: str
    end: str
    minutes: int


class WorkCenterSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: WorkCenterKind
    machine_count: int
    efficiency_pct: DecimalStr
    is_active: bool
    #: minutes on a normal working day (shifts x machines x efficiency)
    standard_day_minutes: DecimalStr
    rate_per_hour: Annotated[Money | None, COST_GUARD] = None
    redacted_fields: list[str] = Field(default_factory=list)


class WorkCenterRead(WorkCenterSummary):
    calendar: CalendarRef
    shifts: list[ShiftMinutes]
    job_work_party_id: uuid.UUID | None
    notes: str | None
    exceptions: list[CapacityExceptionRead]
    version: int
    capabilities: dict[str, Capability]


# ---- BOMs and routings -----------------------------------------------------------------------------------------------
class BomLineIn(BaseModel):
    line_no: int | None = Field(default=None, ge=1, le=9999)
    component_product_id: uuid.UUID
    qty_per: DecimalStr
    uom_code: str | None = None
    scrap_pct: DecimalStr = Decimal(0)
    is_sheet_material: bool = False
    alternate_for_line_no: int | None = Field(default=None, ge=1, le=9999)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None

    _qty = field_validator("qty_per")(_positive)

    @field_validator("scrap_pct")
    @classmethod
    def _scrap(cls, v: Decimal) -> Decimal:
        if not (0 <= v < 100):
            raise ValueError("scrap is a percentage from 0 to below 100")
        return v


class BomCreate(BaseModel):
    product_id: uuid.UUID
    notes: Notes | None = None
    lines: list[BomLineIn] = Field(default_factory=list, max_length=500)
    #: start from an existing version's lines (a new draft version of the same product)
    copy_from_id: uuid.UUID | None = None


class BomUpdate(BaseModel):
    expected_version: int
    notes: Notes | None = None
    lines: list[BomLineIn] | None = Field(default=None, max_length=500)


class MasterCommand(BaseModel):
    expected_version: int
    reason: Reason | None = None


class BomLineRead(BaseModel):
    id: uuid.UUID
    line_no: int
    component: ProductionProductRef
    qty_per: DecimalStr
    uom_code: str
    scrap_pct: DecimalStr
    is_sheet_material: bool
    alternate_for_line_no: int | None
    has_approved_bom: bool
    notes: str | None


class MasterSummary(BaseModel):
    id: uuid.UUID
    product: ProductionProductRef
    version_no: int
    status: MasterStatus
    author: ProductionUserRef | None
    approved_by: ProductionUserRef | None
    approved_at: datetime | None
    updated_at: datetime
    line_count: int


class BomRead(MasterSummary):
    notes: str | None
    lines: list[BomLineRead]
    retired_at: datetime | None
    version: int
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


class RoutingOperationIn(BaseModel):
    seq: int = Field(ge=1, le=9999)
    name: Text200
    work_center_id: uuid.UUID
    setup_minutes: DecimalStr = Decimal(0)
    run_minutes_per_unit: DecimalStr = Decimal(0)
    is_board_cutting: bool = False
    is_job_work: bool = False

    _setup = field_validator("setup_minutes", "run_minutes_per_unit")(_non_negative)


class RoutingCreate(BaseModel):
    product_id: uuid.UUID
    standard_batch_qty: DecimalStr = Decimal(1)
    notes: Notes | None = None
    operations: list[RoutingOperationIn] = Field(default_factory=list, max_length=200)
    copy_from_id: uuid.UUID | None = None

    _batch = field_validator("standard_batch_qty")(_positive)


class RoutingUpdate(BaseModel):
    expected_version: int
    standard_batch_qty: DecimalStr | None = None
    notes: Notes | None = None
    operations: list[RoutingOperationIn] | None = Field(default=None, max_length=200)


class RoutingOperationRead(BaseModel):
    id: uuid.UUID
    seq: int
    name: str
    work_center: WorkCenterRef
    setup_minutes: DecimalStr
    run_minutes_per_unit: DecimalStr
    is_board_cutting: bool
    is_job_work: bool


class RoutingRead(MasterSummary):
    standard_batch_qty: DecimalStr
    notes: str | None
    operations: list[RoutingOperationRead]
    retired_at: datetime | None
    version: int
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


# ---- work orders -------------------------------------------------------------------------------------------------------
class WorkOrderCreate(BaseModel):
    product_id: uuid.UUID | None = None
    quantity: DecimalStr | None = None
    uom_code: str | None = None
    warehouse_id: uuid.UUID | None = None
    #: plan from a sales order line (product and the line's remaining quantity are the defaults)
    sales_order_line_id: uuid.UUID | None = None
    bom_id: uuid.UUID | None = None
    routing_id: uuid.UUID | None = None
    planned_start_date: date | None = None
    due_date: date | None = None
    notes: Notes | None = None

    @field_validator("quantity")
    @classmethod
    def _q(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _positive(v)


class WorkOrderUpdate(BaseModel):
    expected_version: int
    quantity: DecimalStr | None = None
    planned_start_date: date | None = None
    due_date: date | None = None
    notes: Notes | None = None

    @field_validator("quantity")
    @classmethod
    def _q(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _positive(v)


class WorkOrderTransition(BaseModel):
    action: Literal["release", "complete", "close", "cancel"]
    expected_version: int
    reason_code: CancelReason | None = None
    reason: Reason | None = None


class Versioned(BaseModel):
    expected_version: int


class IssueLine(BaseModel):
    material_id: uuid.UUID
    quantity: DecimalStr
    lot_id: uuid.UUID | None = None
    #: a bin of the work order's warehouse (default: its stock location)
    from_location_id: uuid.UUID | None = None

    _q = field_validator("quantity")(_positive)


class IssueRequest(BaseModel):
    expected_version: int
    lines: list[IssueLine] = Field(min_length=1, max_length=200)
    reason: Reason | None = None


class WipLine(BaseModel):
    material_id: uuid.UUID
    quantity: DecimalStr
    #: the lot moved; default: the lots issued to this material, oldest first
    lot_id: uuid.UUID | None = None

    _q = field_validator("quantity")(_positive)


class WipRequest(BaseModel):
    expected_version: int
    lines: list[WipLine] = Field(min_length=1, max_length=200)
    reason: Reason | None = None


class OutputRequest(BaseModel):
    expected_version: int
    qty_good: DecimalStr
    qty_scrap: DecimalStr = Decimal(0)
    lot_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    reason: Reason | None = None

    _good = field_validator("qty_good")(_positive)
    _scrap = field_validator("qty_scrap")(_non_negative)


class OperationComplete(BaseModel):
    expected_version: int
    actual_minutes: DecimalStr | None = None

    @field_validator("actual_minutes")
    @classmethod
    def _m(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _non_negative(v)


class OperationSchedule(BaseModel):
    expected_version: int
    planned_date: date


class CutPlanLink(BaseModel):
    expected_version: int
    cut_plan_id: uuid.UUID
    #: the sheet material the plan's boards replace (default: the only sheet material)
    material_id: uuid.UUID | None = None


class OffcutRecord(BaseModel):
    expected_version: int
    #: the sheet material the offcut is cut from (its product becomes the offcut lot's product)
    material_id: uuid.UUID
    operation_id: uuid.UUID | None = None
    length_mm: DecimalStr
    width_mm: DecimalStr
    thickness_mm: DecimalStr | None = None
    grain_axis: Literal["length", "width", "none"] | None = None
    lot_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    #: the board lot the offcut came from
    parent_lot_id: uuid.UUID | None = None
    #: a predicted offcut of the linked plan's calculation this measurement confirms
    predicted_offcut_id: uuid.UUID | None = None

    _dims = field_validator("length_mm", "width_mm")(_positive)


class MaterialRead(BaseModel):
    id: uuid.UUID
    line_no: int
    component: ProductionProductRef
    uom_code: str
    qty_required: DecimalStr
    qty_required_bom: DecimalStr
    qty_reserved: DecimalStr
    qty_issued: DecimalStr
    qty_consumed: DecimalStr
    qty_returned: DecimalStr
    #: issued, not yet consumed or returned (sits in WIP)
    qty_in_wip: DecimalStr
    #: still to issue: required - (issued - returned)
    qty_to_issue: DecimalStr
    #: free stock now at the work order's warehouse (available on hand minus reservations)
    qty_free: DecimalStr
    short: bool
    requirement_source: RequirementSource
    is_sheet_material: bool
    cut_plan_id: uuid.UUID | None
    alternates: list[ProductionProductRef]
    version: int


class PredictedOffcut(BaseModel):
    id: uuid.UUID
    board_no: int
    length_mm: DecimalStr
    width_mm: DecimalStr


class CutPlanRef(BaseModel):
    id: uuid.UUID
    plan_number: str
    name: str
    status: str
    calculation_id: uuid.UUID | None
    boards: int | None
    stale: bool
    requires_verification: bool
    verified: bool
    ready: bool
    reason_code: str | None
    path: str


class OperationRead(BaseModel):
    id: uuid.UUID
    seq: int
    name: str
    work_center: WorkCenterRef
    setup_minutes: DecimalStr
    run_minutes_per_unit: DecimalStr
    planned_minutes: DecimalStr
    planned_date: date | None
    actual_minutes: DecimalStr | None
    status: OperationStatus
    is_board_cutting: bool
    cut_plan: CutPlanRef | None
    predicted_offcuts: list[PredictedOffcut]
    completed_at: datetime | None
    completed_by: ProductionUserRef | None
    version: int


class TransactionLineRead(BaseModel):
    material_id: uuid.UUID | None
    product: ProductionProductRef
    quantity: DecimalStr
    uom_code: str
    lot_code: str | None
    from_location: str | None
    to_location: str | None


class TransactionRead(BaseModel):
    id: uuid.UUID
    kind: TransactionKind
    posting_id: uuid.UUID
    lot_id: uuid.UUID | None
    lines: list[TransactionLineRead]
    qty_good: DecimalStr | None
    qty_scrap: DecimalStr | None
    reason: str | None
    created_at: datetime
    created_by: ProductionUserRef | None


class OrderLineRef(BaseModel):
    order_id: uuid.UUID
    order_number: str
    line_id: uuid.UUID | None
    line_no: int | None
    path: str


class WorkOrderSummary(BaseModel):
    id: uuid.UUID
    wo_number: str
    product: ProductionProductRef
    qty_planned: DecimalStr
    uom_code: str
    qty_good: DecimalStr
    status: WorkOrderStatus
    is_blocked: bool
    warehouse: ProductionWarehouseRef
    owner: ProductionUserRef | None
    planned_start_date: date | None
    due_date: date | None
    sales_order: OrderLineRef | None
    updated_at: datetime


class WorkOrderRead(WorkOrderSummary):
    bom: MasterSummary
    routing: MasterSummary
    qty_scrap: DecimalStr
    blocked_causes: list[CauseRef]
    blocked_since: datetime | None
    notes: str | None
    materials: list[MaterialRead]
    operations: list[OperationRead]
    transactions: list[TransactionRead]
    released_at: datetime | None
    completed_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason_code: str | None
    cancel_reason: str | None
    version: int
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]


class WorkOrderFilters(BaseModel):
    q: str | None = None
    status: list[WorkOrderStatus] | None = None
    blocked: bool | None = None
    product_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    scope: Literal["mine", "all"] = "all"


# ---- capacity --------------------------------------------------------------------------------------------------------
class CapacityDay(BaseModel):
    day: date
    day_type: Literal["working", "non_working", "holiday"]
    capacity_minutes: DecimalStr
    load_minutes: DecimalStr
    utilisation_pct: DecimalStr | None
    overloaded: bool
    exception_reason: str | None
    work_orders: list[str]


class CapacityRow(BaseModel):
    work_center: WorkCenterRef
    days: list[CapacityDay]
    total_capacity_minutes: DecimalStr
    total_load_minutes: DecimalStr
    unscheduled_minutes: DecimalStr


class CapacityRead(BaseModel):
    date_from: date
    date_to: date
    rows: list[CapacityRow]
    overloaded_days: int


# ---- cost rollups ----------------------------------------------------------------------------------------------------
class CostRollupRequest(BaseModel):
    product_id: uuid.UUID
    as_of: date | None = None
    currency: Literal["INR", "EUR", "USD", "GBP"] | None = None
    batch_qty: DecimalStr | None = None

    @field_validator("batch_qty")
    @classmethod
    def _b(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _positive(v)


class CostLine(BaseModel):
    kind: Literal["material", "operation"]
    #: where the line sits in the exploded BOM (``LK-WB-1800`` or ``SUB-1 > LK-WB-1800``)
    path: str
    label: str
    quantity: DecimalStr
    uom_code: str
    unit_cost: Money
    amount: Money
    source: str


class MissingInput(BaseModel):
    kind: Literal["material_cost", "fx_rate", "uom_conversion", "work_centre_rate", "bom", "routing"]
    ref_type: str
    ref_id: uuid.UUID | None
    label: str
    reason_code: str


class CostRollupRead(BaseModel):
    id: uuid.UUID
    product: ProductionProductRef
    bom_id: uuid.UUID | None
    routing_id: uuid.UUID | None
    as_of: date
    currency: str
    batch_qty: DecimalStr
    input_hash: str
    status: CostRollupStatus
    missing_inputs: list[MissingInput]
    material_total: Annotated[Money | None, COST_GUARD] = None
    operation_total: Annotated[Money | None, COST_GUARD] = None
    total: Annotated[Money | None, COST_GUARD] = None
    lines: Annotated[list[CostLine] | None, COST_GUARD] = None
    computed_at: datetime
    computed_by: ProductionUserRef | None
    #: the same inputs were already rolled up: this is the stored result
    reused: bool = False
    redacted_fields: list[str] = Field(default_factory=list)


# ---- feasibility and what-if --------------------------------------------------------------------------------------------
class FeasibilityRequest(BaseModel):
    product_id: uuid.UUID
    quantity: DecimalStr
    need_by: date
    warehouse_id: uuid.UUID | None = None

    _q = field_validator("quantity")(_positive)


class EvidenceItem(BaseModel):
    kind: Literal["stock", "purchase_supply", "components", "capacity", "routing", "bom", "lead_time"]
    status: Literal["ok", "short", "missing", "late", "info"]
    label: str
    facts: dict[str, str] = Field(default_factory=dict)


class FeasibilityRead(BaseModel):
    outcome: FeasibilityOutcome
    product: ProductionProductRef
    quantity: DecimalStr
    uom_code: str
    warehouse: ProductionWarehouseRef
    need_by: date
    from_stock: DecimalStr
    to_make: DecimalStr
    earliest_completion: date | None
    evidence: list[EvidenceItem]
    missing_inputs: list[str]
    computed_at: datetime
    #: always true: nothing was reserved, posted or saved
    read_only: bool = True


class StockChange(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    #: added to (or, when negative, removed from) the free stock in the simulation only
    delta: DecimalStr


class CapacityChange(BaseModel):
    work_center_id: uuid.UUID
    #: replaces the work centre's machine count in the simulation only
    machine_count: int | None = Field(default=None, ge=1, le=500)
    #: extra minutes per working day (negative removes) in the simulation only
    extra_minutes_per_day: int | None = Field(default=None, ge=-100_000, le=100_000)


class SimulationRequest(BaseModel):
    checks: list[FeasibilityRequest] = Field(min_length=1, max_length=20)
    stock_changes: list[StockChange] = Field(default_factory=list, max_length=50)
    capacity_changes: list[CapacityChange] = Field(default_factory=list, max_length=50)


class SimulationRead(BaseModel):
    simulation: Literal[True] = True
    label: str = "What-if simulation: nothing was reserved, posted or saved"
    baseline: list[FeasibilityRead]
    scenario: list[FeasibilityRead]
    computed_at: datetime
