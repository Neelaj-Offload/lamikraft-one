"""Cutting tables (prefix ``cutting_``): settings, machine profiles, grain locks, plans, plan items, calculations and
their immutable result rows (groups, boards, placements, item results, predicted offcuts, guillotine cuts).

Every table is a tenant table with forced RLS. A calculation and all of its result rows are append-only: reopening a
plan shows the stored latest calculation without recomputing; editing inputs only marks the plan stale. Dimensions
are canonical millimetres (NUMERIC(12,3)) with at most one decimal place (the packer works in deci-millimetres);
areas are exact mm² (NUMERIC(18,2)).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    ArchivableMixin,
    Base,
    BranchMixin,
    IdMixin,
    TenantEntity,
    TenantMixin,
    VersionMixin,
)

MODES = ("nested", "guillotine")
PLAN_STATUSES = ("draft", "calculated", "released", "archived")
CALC_STATUSES = ("idle", "queued", "running", "failed")
GRAIN_RULES = ("inherit", "locked", "free")
CALC_ORIGINS = ("sync", "job")
BOARD_SOURCES = ("standard", "board_lot", "offcut")
CUT_ORIENTATIONS = ("horizontal", "vertical")
UNFIT_REASONS = ("exceeds_usable_board", "grain_lock_prevents_rotation", "board_supply_exhausted", "max_boards_limit")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


def _mm(nullable: bool = False) -> Any:
    return mapped_column(Numeric(12, 3), nullable=nullable)


def _area() -> Any:
    return mapped_column(Numeric(18, 2), nullable=False)


def _pct() -> Any:
    return mapped_column(Numeric(7, 4), nullable=False)


class CuttingSettings(TenantEntity, VersionMixin, Base):
    """One row per company (created on first change; reads fall back to the legacy defaults)."""

    __tablename__ = "cutting_settings"

    board_length_mm: Mapped[Decimal] = _mm()
    board_width_mm: Mapped[Decimal] = _mm()
    margin_mm: Mapped[Decimal] = _mm()
    gap_mm: Mapped[Decimal] = _mm()
    oversize_mm: Mapped[Decimal] = _mm()
    default_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="nested")
    default_machine_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_machine_profile.id", ondelete="RESTRICT"), nullable=True
    )
    max_extra_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_extra_pct: Mapped[Decimal] = _pct()
    min_offcut_mm: Mapped[Decimal] = _mm()
    max_boards_per_group: Mapped[int] = mapped_column(Integer, nullable=False, default=500)

    __table_args__ = (
        CheckConstraint(_in("default_mode", MODES), name="default_mode_values"),
        CheckConstraint(
            "board_length_mm > 0 AND board_width_mm > 0 AND margin_mm >= 0 AND gap_mm >= 0 AND oversize_mm >= 0 "
            "AND min_offcut_mm > 0 AND max_extra_qty >= 0 AND max_extra_pct >= 0 AND max_extra_pct <= 100 "
            "AND max_boards_per_group BETWEEN 1 AND 5000",
            name="values_in_range",
        ),
        Index("uq_cutting_settings_company", "company_id", unique=True),
    )


class MachineProfile(TenantEntity, VersionMixin, ArchivableMixin, Base):
    """A saw or nesting machine: its layout mode and (optionally) its own kerf."""

    __tablename__ = "cutting_machine_profile"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    gap_mm: Mapped[Decimal | None] = _mm(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("mode", MODES), name="mode_values"),
        CheckConstraint("gap_mm IS NULL OR gap_mm >= 0", name="gap_non_negative"),
        Index("uq_cutting_machine_profile_code", "company_id", "code", unique=True),
    )


class GrainLock(TenantEntity, VersionMixin, Base):
    """A decor whose pieces may never be rotated (keyed on the canonical decor; legacy ``grain_locked_decors``)."""

    __tablename__ = "cutting_grain_lock"

    decor_key: Mapped[str] = mapped_column(String(40), nullable=False)
    #: the text as entered when it differed from the canonical key (``"120.0"``)
    decor_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint("decor_key = btrim(decor_key) AND length(decor_key) BETWEEN 1 AND 40", name="decor_key_trimmed"),
        Index("uq_cutting_grain_lock_decor", "company_id", "decor_key", unique=True),
    )


class Plan(TenantEntity, BranchMixin, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "cutting_plan"

    plan_number: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ---- settings snapshot (taken from company settings at creation; edited per plan) ----
    board_length_mm: Mapped[Decimal] = _mm()
    board_width_mm: Mapped[Decimal] = _mm()
    margin_mm: Mapped[Decimal] = _mm()
    gap_mm: Mapped[Decimal] = _mm()
    oversize_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oversize_mm: Mapped[Decimal] = _mm()
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="nested")
    machine_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_machine_profile.id", ondelete="RESTRICT"), nullable=True
    )
    overproduction_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_extra_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_extra_pct: Mapped[Decimal] = _pct()
    min_offcut_mm: Mapped[Decimal] = _mm()
    max_boards_per_group: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    # ---- lifecycle ----
    inputs_changed_since_calc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_physical_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: measured board dimensions recorded at verification ({"length_mm", "width_mm", "note"})
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    duplicated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_plan.id", ondelete="RESTRICT"), nullable=True
    )
    latest_calculation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    calc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ---- background calculation state (large inputs run as a job) ----
    calc_status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    calc_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    calc_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calc_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", PLAN_STATUSES), name="status_values"),
        CheckConstraint(_in("mode", MODES), name="mode_values"),
        CheckConstraint(_in("calc_status", CALC_STATUSES), name="calc_status_values"),
        CheckConstraint(
            "board_length_mm > 0 AND board_width_mm > 0 AND margin_mm >= 0 AND gap_mm >= 0 AND oversize_mm >= 0 "
            "AND min_offcut_mm > 0 AND max_extra_qty >= 0 AND max_extra_pct >= 0 AND max_extra_pct <= 100 "
            "AND max_boards_per_group BETWEEN 1 AND 5000",
            name="settings_in_range",
        ),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        Index("uq_cutting_plan_number", "company_id", "plan_number", unique=True),
        Index("ix_cutting_plan_owner", "company_id", "owner_user_id", "updated_at"),
        Index("ix_cutting_plan_list", "company_id", "status", "updated_at"),
    )


class PlanItem(TenantEntity, Base):
    __tablename__ = "cutting_plan_item"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_plan.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    #: decor as entered, and its canonical key (groups and grain locks use the key)
    decor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decor_key: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    thickness_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    length_mm: Mapped[Decimal] = _mm()
    width_mm: Mapped[Decimal] = _mm()
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    grain_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="inherit")
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint("length_mm > 0 AND width_mm > 0 AND quantity > 0 AND thickness_mm > 0", name="positive"),
        CheckConstraint(_in("grain_rule", GRAIN_RULES), name="grain_rule_values"),
        Index("uq_cutting_plan_item_line", "plan_id", "line_no", unique=True),
    )


class PlanOffcut(TenantEntity, Base):
    """A measured offcut lot the plan may cut from (Slice 5 offcut reuse; an input like the items).

    The lot's measured size is pinned at selection (grain along ``length_mm``: a lot measured with its grain across the
    width is stored turned), so a recalculation uses the size the planner saw. Whether the lot is still on hand is
    checked again when the plan is released for a work order."""

    __tablename__ = "cutting_plan_offcut"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_plan.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(60), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decor_key: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    thickness_key: Mapped[str] = mapped_column(String(20), nullable=False)
    length_mm: Mapped[Decimal] = _mm()
    width_mm: Mapped[Decimal] = _mm()
    #: the lot's recorded grain axis (``length`` | ``width`` | ``none``; null when not recorded)
    grain_axis: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        CheckConstraint("length_mm > 0 AND width_mm > 0 AND seq > 0", name="positive"),
        CheckConstraint("grain_axis IS NULL OR grain_axis IN ('length', 'width', 'none')", name="grain_axis_values"),
        Index("uq_cutting_plan_offcut_lot", "plan_id", "lot_id", unique=True),
        Index("uq_cutting_plan_offcut_seq", "plan_id", "seq", unique=True),
    )


class Calculation(TenantEntity, Base):
    """One immutable calculation of a plan (append-only)."""

    __tablename__ = "cutting_calculation"
    __append_only__ = True

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_plan.id", ondelete="RESTRICT"), nullable=False
    )
    calc_no: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_physical_verification: Mapped[bool] = mapped_column(Boolean, nullable=False)
    boards: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False)
    placed_required: Mapped[int] = mapped_column(Integer, nullable=False)
    extra: Mapped[int] = mapped_column(Integer, nullable=False)
    produced: Mapped[int] = mapped_column(Integer, nullable=False)
    unfit: Mapped[int] = mapped_column(Integer, nullable=False)
    lower_bound_boards: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_area_mm2: Mapped[Decimal] = _area()
    usable_area_mm2: Mapped[Decimal] = _area()
    placed_area_mm2: Mapped[Decimal] = _area()
    trim_area_mm2: Mapped[Decimal] = _area()
    scrap_area_mm2: Mapped[Decimal] = _area()
    efficiency_usable_pct: Mapped[Decimal] = _pct()
    efficiency_raw_pct: Mapped[Decimal] = _pct()
    scrap_pct: Mapped[Decimal] = _pct()
    evaluations: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("mode", MODES), name="mode_values"),
        CheckConstraint(_in("origin", CALC_ORIGINS), name="origin_values"),
        CheckConstraint("raw_area_mm2 = placed_area_mm2 + scrap_area_mm2 + trim_area_mm2", name="area_identity"),
        CheckConstraint("required = placed_required + unfit AND produced = placed_required + extra", name="counts"),
        Index("uq_cutting_calculation_no", "plan_id", "calc_no", unique=True),
    )


class _ResultRow(IdMixin, TenantMixin):
    """Rows written in bulk with their calculation (company_id is set explicitly; no timestamps of their own)."""

    calculation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cutting_calculation.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    group_no: Mapped[int] = mapped_column(Integer, nullable=False)


class CalcGroup(_ResultRow, Base):
    __tablename__ = "cutting_calc_group"
    __append_only__ = True

    decor_key: Mapped[str] = mapped_column(String(40), nullable=False)
    thickness_key: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    boards: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_area_mm2: Mapped[Decimal] = _area()
    usable_area_mm2: Mapped[Decimal] = _area()
    placed_area_mm2: Mapped[Decimal] = _area()
    trim_area_mm2: Mapped[Decimal] = _area()
    scrap_area_mm2: Mapped[Decimal] = _area()
    efficiency_usable_pct: Mapped[Decimal] = _pct()
    efficiency_raw_pct: Mapped[Decimal] = _pct()
    scrap_pct: Mapped[Decimal] = _pct()
    lower_bound_boards: Mapped[int] = mapped_column(Integer, nullable=False)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint("raw_area_mm2 = placed_area_mm2 + scrap_area_mm2 + trim_area_mm2", name="area_identity"),
        Index("uq_cutting_calc_group_no", "calculation_id", "group_no", unique=True),
    )


class CalcBoard(_ResultRow, Base):
    __tablename__ = "cutting_calc_board"
    __append_only__ = True

    board_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")
    #: the offcut lot cut from (``source = 'offcut'``)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    raw_length_mm: Mapped[Decimal] = _mm()
    raw_width_mm: Mapped[Decimal] = _mm()
    margin_mm: Mapped[Decimal] = _mm()
    usable_length_mm: Mapped[Decimal] = _mm()
    usable_width_mm: Mapped[Decimal] = _mm()
    placed_area_mm2: Mapped[Decimal] = _area()
    efficiency_pct: Mapped[Decimal] = _pct()

    __table_args__ = (
        CheckConstraint(_in("source", BOARD_SOURCES), name="source_values"),
        CheckConstraint("(source = 'offcut') = (lot_id IS NOT NULL) OR source = 'board_lot'", name="offcut_has_lot"),
        Index("uq_cutting_calc_board_no", "calculation_id", "group_no", "board_no", unique=True),
    )


class CalcPlacement(_ResultRow, Base):
    __tablename__ = "cutting_calc_placement"
    __append_only__ = True

    board_no: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    piece_no: Mapped[int] = mapped_column(Integer, nullable=False)
    x_mm: Mapped[Decimal] = _mm()
    y_mm: Mapped[Decimal] = _mm()
    along_length_mm: Mapped[Decimal] = _mm()
    along_width_mm: Mapped[Decimal] = _mm()
    rotated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_extra: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (Index("ix_cutting_calc_placement_board", "calculation_id", "group_no", "board_no", "seq"),)


class CalcItemResult(_ResultRow, Base):
    __tablename__ = "cutting_calc_item_result"
    __append_only__ = True

    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    length_mm: Mapped[Decimal] = _mm()
    width_mm: Mapped[Decimal] = _mm()
    rotation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False)
    placed_required: Mapped[int] = mapped_column(Integer, nullable=False)
    extra: Mapped[int] = mapped_column(Integer, nullable=False)
    produced: Mapped[int] = mapped_column(Integer, nullable=False)
    unfit: Mapped[int] = mapped_column(Integer, nullable=False)
    unfit_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("required = placed_required + unfit AND produced = placed_required + extra", name="counts"),
        CheckConstraint(f"unfit_reason IS NULL OR {_in('unfit_reason', UNFIT_REASONS)}", name="unfit_reason_values"),
        Index("uq_cutting_calc_item_result_line", "calculation_id", "line_no", unique=True),
    )


class CalcOffcut(_ResultRow, Base):
    __tablename__ = "cutting_calc_offcut"
    __append_only__ = True

    board_no: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    x_mm: Mapped[Decimal] = _mm()
    y_mm: Mapped[Decimal] = _mm()
    length_mm: Mapped[Decimal] = _mm()
    width_mm: Mapped[Decimal] = _mm()


class CalcCut(_ResultRow, Base):
    __tablename__ = "cutting_calc_cut"
    __append_only__ = True

    board_no: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    orientation: Mapped[str] = mapped_column(String(20), nullable=False)
    kerf_start_mm: Mapped[Decimal] = _mm()
    extent_start_mm: Mapped[Decimal] = _mm()
    extent_end_mm: Mapped[Decimal] = _mm()
    kerf_mm: Mapped[Decimal] = _mm()

    __table_args__ = (CheckConstraint(_in("orientation", CUT_ORIENTATIONS), name="orientation_values"),)


RESULT_MODELS = (CalcGroup, CalcBoard, CalcPlacement, CalcItemResult, CalcOffcut, CalcCut)
