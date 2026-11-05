"""Cutting request and response models. Dimensions travel as decimal strings in millimetres (at most one decimal
place; the packer works in integer deci-millimetres), areas as exact mm² strings, percentages as strings with two
places. Piece counts are integers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.money import DecimalStr

Mode = Literal["nested", "guillotine"]
GrainRule = Literal["inherit", "locked", "free"]
PlanStatus = Literal["draft", "calculated", "released", "archived"]
CalcStatus = Literal["idle", "queued", "running", "failed"]
UnfitReason = Literal["exceeds_usable_board", "grain_lock_prevents_rotation", "board_supply_exhausted", "max_boards_limit"]

HEURISTIC_NOTE = "Heuristic layout, not guaranteed optimal"
#: largest board edge accepted (mm); the column is NUMERIC(12,3) but no sheet is ten metres long
MAX_EDGE_MM = Decimal("10000")


def _one_place(value: Decimal) -> Decimal:
    if value != value.quantize(Decimal("0.1")):
        raise ValueError("millimetres allow at most one decimal place")
    return value


def _positive(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("must be greater than zero")
    return value


def _non_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("must not be negative")
    return value


def _edge(value: Decimal) -> Decimal:
    if value > MAX_EDGE_MM:
        raise ValueError("must be at most 10000 mm")
    return value


def _pct(value: Decimal) -> Decimal:
    if value < 0 or value > 100:
        raise ValueError("must be between 0 and 100")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("at most two decimal places")
    return value


PositiveMm = Annotated[DecimalStr, AfterValidator(_one_place), AfterValidator(_positive), AfterValidator(_edge)]
NonNegativeMm = Annotated[DecimalStr, AfterValidator(_one_place), AfterValidator(_non_negative), AfterValidator(_edge)]
Thickness = Annotated[DecimalStr, AfterValidator(_positive)]
Percent = Annotated[DecimalStr, AfterValidator(_pct)]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Sku = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Decor = Annotated[str, StringConstraints(max_length=80)]


class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


class TransitionRead(BaseModel):
    action: str
    to_status: str
    requires_reason: bool = False


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str | None


# =====================================================================================================
# settings, machine profiles, grain locks
# =====================================================================================================
class SettingsRead(BaseModel):
    board_length_mm: DecimalStr
    board_width_mm: DecimalStr
    margin_mm: DecimalStr
    gap_mm: DecimalStr
    oversize_mm: DecimalStr
    default_mode: Mode
    default_machine_profile_id: uuid.UUID | None
    max_extra_qty: int
    max_extra_pct: DecimalStr
    min_offcut_mm: DecimalStr
    max_boards_per_group: int
    sync_piece_limit: int
    max_pieces: int
    version: int
    #: False while the company still runs on the built-in legacy defaults (2440 x 1220, margin 5, gap 6)
    customised: bool


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = None
    board_length_mm: PositiveMm | None = None
    board_width_mm: PositiveMm | None = None
    margin_mm: NonNegativeMm | None = None
    gap_mm: NonNegativeMm | None = None
    oversize_mm: NonNegativeMm | None = None
    default_mode: Mode | None = None
    default_machine_profile_id: uuid.UUID | None = None
    max_extra_qty: Annotated[int, Field(ge=0, le=1000)] | None = None
    max_extra_pct: Percent | None = None
    min_offcut_mm: PositiveMm | None = None
    max_boards_per_group: Annotated[int, Field(ge=1, le=5000)] | None = None


class MachineProfileRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    mode: Mode
    gap_mm: DecimalStr | None
    notes: str | None
    archived: bool
    version: int


class MachineProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    mode: Mode
    gap_mm: NonNegativeMm | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class MachineProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    mode: Mode | None = None
    gap_mm: NonNegativeMm | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    archived: bool | None = None


class GrainLockRead(BaseModel):
    id: uuid.UUID
    decor_key: str
    decor_source: str | None
    label: str | None
    updated_at: datetime
    updated_by: UserRef | None


class GrainLockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decor: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    label: Text200 | None = None


class GrainLockReplace(BaseModel):
    """Bulk replace (legacy ``PUT /grain-settings``): the list becomes exactly these decors."""

    model_config = ConfigDict(extra="forbid")

    locks: Annotated[list[GrainLockIn], Field(max_length=2000)]


class GrainLockList(BaseModel):
    items: list[GrainLockRead]
    can_manage: bool
    #: canonicalisation notes per entered decor (``120.0`` was stored as ``120``)
    warnings: list[str] = Field(default_factory=list)


# =====================================================================================================
# plan inputs
# =====================================================================================================
class PlanItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID | None = None
    sku: Sku
    decor: Decor | None = None
    thickness_mm: Thickness
    length_mm: PositiveMm
    width_mm: PositiveMm
    quantity: Annotated[int, Field(ge=1, le=5000)]
    grain_rule: GrainRule = "inherit"
    label: Text200 | None = None


class PlanSettingsIn(BaseModel):
    """Per-plan settings; anything omitted comes from the company settings (or the machine profile's mode/kerf)."""

    model_config = ConfigDict(extra="forbid")

    board_length_mm: PositiveMm | None = None
    board_width_mm: PositiveMm | None = None
    margin_mm: NonNegativeMm | None = None
    gap_mm: NonNegativeMm | None = None
    oversize_enabled: bool | None = None
    oversize_mm: NonNegativeMm | None = None
    mode: Mode | None = None
    machine_profile_id: uuid.UUID | None = None
    overproduction_enabled: bool | None = None
    max_extra_qty: Annotated[int, Field(ge=0, le=1000)] | None = None
    max_extra_pct: Percent | None = None
    min_offcut_mm: PositiveMm | None = None
    max_boards_per_group: Annotated[int, Field(ge=1, le=5000)] | None = None


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None
    items: Annotated[list[PlanItemIn], Field(max_length=500)] = Field(default_factory=list)
    settings: PlanSettingsIn | None = None


class PlanUpdate(BaseModel):
    """Dirty fields plus ``expected_version``; ``items`` replaces the whole cut list when present."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    name: Name | None = None
    notes: Annotated[str, StringConstraints(max_length=4000)] | None = None
    items: Annotated[list[PlanItemIn], Field(max_length=500)] | None = None
    settings: PlanSettingsIn | None = None


class PlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int


class PlanTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["archive"]
    expected_version: int
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class VerifyBoards(BaseModel):
    """Measured raw board size for a plan that assumed the +oversize board (business decision #12)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    measured_length_mm: PositiveMm
    measured_width_mm: PositiveMm
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class CalculateIn(BaseModel):
    """Stateless calculation (legacy ``POST /sheet-optimizer/calculate``): nothing is stored."""

    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[PlanItemIn], Field(min_length=1, max_length=500)]
    settings: PlanSettingsIn | None = None


# =====================================================================================================
# reads
# =====================================================================================================
class PlanItemRead(BaseModel):
    id: uuid.UUID
    line_no: int
    product_id: uuid.UUID | None
    sku: str
    decor: str | None
    decor_key: str
    thickness_mm: DecimalStr
    length_mm: DecimalStr
    width_mm: DecimalStr
    quantity: int
    grain_rule: GrainRule
    label: str | None


class PlanSettingsRead(BaseModel):
    board_length_mm: DecimalStr
    board_width_mm: DecimalStr
    margin_mm: DecimalStr
    gap_mm: DecimalStr
    oversize_enabled: bool
    oversize_mm: DecimalStr
    mode: Mode
    machine_profile_id: uuid.UUID | None
    overproduction_enabled: bool
    max_extra_qty: int
    max_extra_pct: DecimalStr
    min_offcut_mm: DecimalStr
    max_boards_per_group: int
    #: the raw board the packer assumes (board + 2 x oversize when enabled)
    raw_length_mm: DecimalStr
    raw_width_mm: DecimalStr
    usable_length_mm: DecimalStr
    usable_width_mm: DecimalStr


class Areas(BaseModel):
    raw_area_mm2: DecimalStr
    usable_area_mm2: DecimalStr
    placed_area_mm2: DecimalStr
    trim_area_mm2: DecimalStr
    scrap_area_mm2: DecimalStr
    efficiency_usable_pct: DecimalStr
    efficiency_raw_pct: DecimalStr
    scrap_pct: DecimalStr
    #: display values in m² (three places); the mm² values above are exact and reconcile
    raw_area_m2: DecimalStr
    placed_area_m2: DecimalStr
    scrap_area_m2: DecimalStr


class PlacementRead(BaseModel):
    seq: int
    line_no: int
    sku: str
    piece_no: int
    x_mm: DecimalStr
    y_mm: DecimalStr
    along_length_mm: DecimalStr
    along_width_mm: DecimalStr
    rotated: bool
    is_extra: bool


class OffcutRead(BaseModel):
    seq: int
    x_mm: DecimalStr
    y_mm: DecimalStr
    length_mm: DecimalStr
    width_mm: DecimalStr


class CutRead(BaseModel):
    seq: int
    stage: int
    orientation: Literal["horizontal", "vertical"]
    kerf_start_mm: DecimalStr
    extent_start_mm: DecimalStr
    extent_end_mm: DecimalStr
    kerf_mm: DecimalStr


class BoardRead(BaseModel):
    #: 1-based across the whole calculation (group order, then board order); used by the SVG export
    index: int
    board_no: int
    source: Literal["standard", "board_lot", "offcut"]
    raw_length_mm: DecimalStr
    raw_width_mm: DecimalStr
    margin_mm: DecimalStr
    usable_length_mm: DecimalStr
    usable_width_mm: DecimalStr
    placed_area_mm2: DecimalStr
    efficiency_pct: DecimalStr
    placements: list[PlacementRead]
    offcuts: list[OffcutRead]
    cuts: list[CutRead]
    svg_path: str | None = None
    #: the offcut lot this board is (``source = "offcut"``); the code is shown only while the lot is visible
    lot_id: uuid.UUID | None = None
    lot_code: str | None = None


class ItemResultRead(BaseModel):
    line_no: int
    sku: str
    length_mm: DecimalStr
    width_mm: DecimalStr
    rotation_allowed: bool
    required: int
    placed_required: int
    extra: int
    produced: int
    unfit: int
    unfit_reason: UnfitReason | None


class GroupRead(Areas):
    group_no: int
    decor_key: str
    thickness_mm: str
    mode: Mode
    board_count: int
    lower_bound_boards: int
    warnings: list[str]
    items: list[ItemResultRead]
    boards: list[BoardRead]
    #: boards of this group cut from offcut lots (the rest are standard sheets)
    offcut_boards: int = 0


class CalculationTotals(Areas):
    boards: int
    #: of ``boards``, how many are offcut lots (standard sheets = boards - offcut_boards)
    offcut_boards: int = 0
    required: int
    placed_required: int
    extra: int
    produced: int
    unfit: int
    lower_bound_boards: int


class CalculationResult(BaseModel):
    """A packed result; stored calculations add their identity in ``CalculationRead``."""

    algorithm_version: str
    mode: Mode
    input_hash: str
    result_hash: str
    requires_physical_verification: bool
    note: str = HEURISTIC_NOTE
    totals: CalculationTotals
    groups: list[GroupRead]
    settings: PlanSettingsRead
    grain_locked_decors: list[str]


class CalculationRead(CalculationResult):
    id: uuid.UUID
    plan_id: uuid.UUID
    calc_no: int
    origin: Literal["sync", "job"]
    created_at: datetime
    created_by: UserRef | None


class CalculationSummary(BaseModel):
    id: uuid.UUID
    calc_no: int
    created_at: datetime
    created_by: UserRef | None
    origin: Literal["sync", "job"]
    boards: int
    efficiency_usable_pct: DecimalStr
    unfit: int
    requires_physical_verification: bool
    input_hash: str
    result_hash: str


class CalcStateRead(BaseModel):
    status: CalcStatus
    requested_at: datetime | None
    error: dict[str, object] | None
    #: pieces in the current inputs, the synchronous limit and the hard cap
    pieces: int
    sync_piece_limit: int
    max_pieces: int


class VerificationRead(BaseModel):
    required: bool
    verified: bool
    verified_at: datetime | None
    verified_by: UserRef | None
    assumed_length_mm: DecimalStr | None
    assumed_width_mm: DecimalStr | None
    measured: dict[str, object] | None


class PlanSummary(BaseModel):
    id: uuid.UUID
    plan_number: str
    name: str
    status: PlanStatus
    owner: UserRef
    item_count: int
    piece_count: int
    boards: int | None
    efficiency_usable_pct: DecimalStr | None
    requires_physical_verification: bool
    verified: bool
    stale: bool
    calc_status: CalcStatus
    updated_at: datetime
    version: int
    path: str


class PlanDetail(BaseModel):
    id: uuid.UUID
    plan_number: str
    name: str
    notes: str | None
    status: PlanStatus
    owner: UserRef
    branch_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int
    duplicated_from: str | None
    items: list[PlanItemRead]
    settings: PlanSettingsRead
    stale: bool
    calculation: CalcStateRead
    verification: VerificationRead
    latest_calculation: CalculationRead | None
    calculations: list[CalculationSummary]
    capabilities: dict[str, Capability]
    allowed_transitions: list[TransitionRead]
    exports: dict[str, str]
    path: str
    warnings: list[str] = Field(default_factory=list)
    #: measured offcut lots the plan may cut from (Slice 5 offcut reuse)
    offcuts: list[PlanOffcutRead] = Field(default_factory=list)


class PlanFilters(BaseModel):
    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    status: list[PlanStatus] | None = None
    scope: Literal["mine", "all"] = "all"
    include_archived: bool = False


class CuttingProduct(BaseModel):
    """A catalogue product as an autocomplete row: fills decor, thickness and dimensions (when known)."""

    product_id: uuid.UUID
    product_key: str
    display_sku: str
    product_name: str
    decor: str | None
    decor_key: str
    decor_name: str | None
    thickness_mm: DecimalStr | None
    length_mm: DecimalStr | None
    width_mm: DecimalStr | None
    grain_locked: bool


# =====================================================================================================
# offcut reuse (Slice 5)
# =====================================================================================================
GrainAxis = Literal["length", "width", "none"]


class PlanOffcutRead(BaseModel):
    """An offcut lot chosen for the plan, with the size pinned when it was chosen (grain along the length)."""

    seq: int
    lot_id: uuid.UUID
    lot_code: str
    product_id: uuid.UUID
    decor_key: str
    thickness_mm: str
    length_mm: DecimalStr
    width_mm: DecimalStr
    grain_axis: GrainAxis | None
    #: whether the lot is still on hand in a visible warehouse (``None`` when the actor cannot read stock)
    on_hand: bool | None
    #: the latest calculation cut from it
    used: bool
    #: whether a group of the plan has its decor and thickness (otherwise the optimiser cannot use it)
    matches_group: bool


class OffcutCandidate(BaseModel):
    lot_id: uuid.UUID
    lot_code: str
    product_id: uuid.UUID
    product_key: str | None
    product_name: str | None
    warehouse_id: uuid.UUID
    warehouse_code: str
    location_code: str
    #: measured size as recorded on the lot
    length_mm: DecimalStr
    width_mm: DecimalStr
    thickness_mm: DecimalStr | None
    grain_axis: GrainAxis | None
    decor_key: str
    #: normalised thickness the optimiser groups on (``""`` when neither the lot nor the product records one)
    thickness_key: str
    matches_group: bool
    selected: bool
    #: other plans (visible to the actor) that also chose this lot
    other_plans: list[str] = Field(default_factory=list)


class OffcutCandidates(BaseModel):
    items: list[OffcutCandidate]
    #: false when the actor cannot read stock (no lots are listed then)
    stock_visible: bool
    note: str = "Offcut lots on hand with a measured size; a lot is checked again when the plan is released"


class PlanOffcutsUpdate(BaseModel):
    """Replace the plan's offcut selection (order = the order the optimiser fills them)."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int
    lot_ids: Annotated[list[uuid.UUID], Field(max_length=50)]


PlanDetail.model_rebuild()
