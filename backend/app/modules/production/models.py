"""Production tables (docs/design/source/operations.md §6, conventions §3 names, prefix ``production_``).

- Masters: ``production_work_center`` (capacity = calendar shifts x machines x efficiency, per-day exceptions in
  ``production_capacity_exception``; the hourly rate is a protected cost input), versioned ``production_bom`` /
  ``production_bom_line`` and ``production_routing`` / ``production_routing_operation``. A version is edited while
  draft, approved by someone other than its author (CHECK ``approved_by <> created_by``), then immutable; at most one
  approved version per product (partial unique index); approving a newer one retires the previous.
- Work orders ``WO-YYYY-NNNN`` pin a BOM and a routing version. Materials (``production_wo_material``) are the
  ``wo_material`` demand of inventory reservations; operations (``production_wo_operation``) carry planned minutes,
  the planned day for capacity and, for the board operation, the linked cut plan. Every stock event is one
  append-only ``production_wo_transaction`` whose id is the inventory posting source id (one posting per event).
- ``production_cost_rollup`` (append-only, unique per input hash: the same inputs give the same row),
  ``production_capacity_overload`` (state per work centre and day so replays emit nothing new).
Feasibility and what-if results are never stored (read-only by construction).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, BranchMixin, TenantEntity, VersionMixin
from app.modules.production.enums import (
    CostRollupStatus,
    MasterStatus,
    OperationStatus,
    OverloadStatus,
    RequirementSource,
    TransactionKind,
    WorkCenterKind,
    WorkOrderStatus,
)

_CURRENCIES = "('INR','EUR','USD','GBP')"


def _qty(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(18, 6), nullable=nullable, default=default)


def _minutes(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(12, 4), nullable=nullable, default=default)


def _uom_fk(table: str, column: str = "uom_code") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["company_id", column], ["uom.company_id", "uom.code"], name=f"fk_{table}_{column}", ondelete="RESTRICT"
    )


def _fk(target: str, nullable: bool = True) -> Any:
    return mapped_column(Uuid(as_uuid=True), ForeignKey(target, ondelete="RESTRICT"), nullable=nullable)


def _user_fk(nullable: bool = True) -> Any:
    return _fk("app_user.id", nullable)


# =====================================================================================================
# masters
# =====================================================================================================
class WorkCenter(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_work_center"

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", info={"enum": WorkCenterKind}
    )
    #: the work calendar whose shifts give the daily minutes (NULL = the company default calendar)
    calendar_id: Mapped[uuid.UUID | None] = _fk("work_calendar.id")
    machine_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    efficiency_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal(100))
    #: protected cost input (guard ``pricing.cost.read``; never sent to a model)
    rate_per_hour_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    rate_per_hour_currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    job_work_party_id: Mapped[uuid.UUID | None] = _fk("parties_party.id")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_production_work_center_code"),
        CheckConstraint("btrim(code) <> '' AND btrim(name) <> ''", name="code_name_not_blank"),
        CheckConstraint("machine_count BETWEEN 1 AND 500", name="machine_count_range"),
        CheckConstraint("efficiency_pct > 0 AND efficiency_pct <= 100", name="efficiency_range"),
        CheckConstraint(
            "(rate_per_hour_amount IS NULL) = (rate_per_hour_currency IS NULL)", name="rate_both_or_neither"
        ),
        CheckConstraint("rate_per_hour_amount IS NULL OR rate_per_hour_amount >= 0", name="rate_non_negative"),
        CheckConstraint(
            f"rate_per_hour_currency IS NULL OR rate_per_hour_currency IN {_CURRENCIES}", name="rate_currency_enabled"
        ),
    )


class CapacityException(TenantEntity, Base):
    __tablename__ = "production_capacity_exception"

    work_center_id: Mapped[uuid.UUID] = _fk("production_work_center.id", nullable=False)
    exception_date: Mapped[date] = mapped_column(Date, nullable=False)
    available_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "work_center_id", "exception_date", name="uq_production_capacity_exception_day"),
        CheckConstraint("available_minutes BETWEEN 0 AND 1440000", name="minutes_range"),
    )


class Bom(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_bom"

    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", info={"enum": MasterStatus})
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = _user_fk()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[uuid.UUID | None] = _user_fk()
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    copied_from_id: Mapped[uuid.UUID | None] = _fk("production_bom.id")

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "version_no", name="uq_production_bom_version"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("approved_by IS NULL OR approved_by <> created_by", name="approver_not_author"),
        CheckConstraint("status = 'draft' OR approved_by IS NOT NULL", name="approved_has_approver"),
        Index(
            "uq_production_bom_one_approved",
            "company_id",
            "product_id",
            unique=True,
            postgresql_where="status = 'approved'",
        ),
    )


class BomLine(TenantEntity, Base):
    __tablename__ = "production_bom_line"

    bom_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_bom.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    component_product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    #: quantity of the component per one unit of the parent product, in ``uom_code``
    qty_per: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    scrap_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal(0))
    is_sheet_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: an alternate for the primary line with this number (NULL = a primary line)
    alternate_for_line_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        UniqueConstraint("bom_id", "line_no", name="uq_production_bom_line_no"),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint("qty_per > 0", name="qty_per_positive"),
        CheckConstraint("scrap_pct >= 0 AND scrap_pct < 100", name="scrap_pct_range"),
        CheckConstraint(
            "alternate_for_line_no IS NULL OR alternate_for_line_no <> line_no", name="alternate_not_self"
        ),
        _uom_fk("production_bom_line"),
    )


class Routing(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_routing"

    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", info={"enum": MasterStatus})
    #: setup minutes are spread over this many units in the cost rollup
    standard_batch_qty: Mapped[Decimal] = _qty(default=Decimal(1))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = _user_fk()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[uuid.UUID | None] = _user_fk()
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    copied_from_id: Mapped[uuid.UUID | None] = _fk("production_routing.id")

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "version_no", name="uq_production_routing_version"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("standard_batch_qty > 0", name="batch_qty_positive"),
        CheckConstraint("approved_by IS NULL OR approved_by <> created_by", name="approver_not_author"),
        CheckConstraint("status = 'draft' OR approved_by IS NOT NULL", name="approved_has_approver"),
        Index(
            "uq_production_routing_one_approved",
            "company_id",
            "product_id",
            unique=True,
            postgresql_where="status = 'approved'",
        ),
    )


class RoutingOperation(TenantEntity, Base):
    __tablename__ = "production_routing_operation"

    routing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_routing.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    work_center_id: Mapped[uuid.UUID] = _fk("production_work_center.id", nullable=False)
    setup_minutes: Mapped[Decimal] = _minutes(default=Decimal(0))
    run_minutes_per_unit: Mapped[Decimal] = _minutes(default=Decimal(0))
    #: the board operation: a work order may link a cut plan to it
    is_board_cutting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_job_work: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("routing_id", "seq", name="uq_production_routing_operation_seq"),
        CheckConstraint("seq > 0", name="seq_positive"),
        CheckConstraint("setup_minutes >= 0 AND run_minutes_per_unit >= 0", name="minutes_non_negative"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


# =====================================================================================================
# work orders
# =====================================================================================================
class WorkOrder(TenantEntity, BranchMixin, VersionMixin, Base):
    __tablename__ = "production_work_order"

    wo_number: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    bom_id: Mapped[uuid.UUID] = _fk("production_bom.id", nullable=False)
    routing_id: Mapped[uuid.UUID] = _fk("production_routing.id", nullable=False)
    warehouse_id: Mapped[uuid.UUID] = _fk("inventory_warehouse.id", nullable=False)
    #: in the product's stock unit
    qty_planned: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    qty_good: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_scrap: Mapped[Decimal] = _qty(default=Decimal(0))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", info={"enum": WorkOrderStatus})
    #: released with short materials: the shortage refs in ``blocked_causes`` (cleared when every material is reserved)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_causes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    blocked_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sales_order_id: Mapped[uuid.UUID | None] = _fk("orders_sales_order.id")
    sales_order_line_id: Mapped[uuid.UUID | None] = _fk("orders_sales_order_line.id")
    owner_user_id: Mapped[uuid.UUID] = _user_fk(nullable=False)
    planned_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[uuid.UUID | None] = _user_fk()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = _user_fk()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = _user_fk()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = _user_fk()
    cancel_reason_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "wo_number", name="uq_production_work_order_number"),
        CheckConstraint("qty_planned > 0", name="qty_planned_positive"),
        CheckConstraint("qty_good >= 0 AND qty_scrap >= 0", name="output_non_negative"),
        CheckConstraint("sales_order_line_id IS NULL OR sales_order_id IS NOT NULL", name="line_needs_order"),
        CheckConstraint("NOT is_blocked OR status IN ('released', 'in_progress')", name="blocked_only_when_open"),
        CheckConstraint(
            "status <> 'cancelled' OR (cancelled_at IS NOT NULL AND cancel_reason_code IS NOT NULL)",
            name="cancel_has_reason",
        ),
        Index("ix_production_work_order_status", "company_id", "status", "planned_start_date"),
        Index("ix_production_work_order_product", "company_id", "product_id"),
        Index("ix_production_work_order_order_line", "company_id", "sales_order_line_id"),
        _uom_fk("production_work_order"),
    )


class WoMaterial(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_wo_material"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_work_order.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bom_line_id: Mapped[uuid.UUID | None] = _fk("production_bom_line.id")
    component_product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    #: every quantity in the component's stock unit
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    qty_required: Mapped[Decimal] = _qty()
    qty_issued: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_consumed: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_returned: Mapped[Decimal] = _qty(default=Decimal(0))
    requirement_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="bom", info={"enum": RequirementSource}
    )
    is_sheet_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cut_plan_id: Mapped[uuid.UUID | None] = _fk("cutting_plan.id")
    #: the BOM requirement before a cut plan replaced it
    qty_required_bom: Mapped[Decimal] = _qty()

    __table_args__ = (
        UniqueConstraint("work_order_id", "line_no", name="uq_production_wo_material_line"),
        CheckConstraint("qty_required > 0 AND qty_required_bom > 0", name="required_positive"),
        CheckConstraint(
            "qty_issued >= 0 AND qty_consumed >= 0 AND qty_returned >= 0", name="quantities_non_negative"
        ),
        CheckConstraint("qty_consumed + qty_returned <= qty_issued", name="wip_non_negative"),
        CheckConstraint("requirement_source = 'bom' OR cut_plan_id IS NOT NULL", name="cut_plan_source_has_plan"),
        _uom_fk("production_wo_material"),
    )


class WoOperation(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_wo_operation"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_work_order.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_operation_id: Mapped[uuid.UUID | None] = _fk("production_routing_operation.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    work_center_id: Mapped[uuid.UUID] = _fk("production_work_center.id", nullable=False)
    setup_minutes: Mapped[Decimal] = _minutes()
    run_minutes_per_unit: Mapped[Decimal] = _minutes()
    #: setup + run x planned quantity
    planned_minutes: Mapped[Decimal] = _minutes()
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_minutes: Mapped[Decimal | None] = _minutes(nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", info={"enum": OperationStatus})
    is_board_cutting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cut_plan_id: Mapped[uuid.UUID | None] = _fk("cutting_plan.id")
    #: the plan's calculation when it was linked (a recalculation afterwards needs a re-link)
    cut_calculation_id: Mapped[uuid.UUID | None] = _fk("cutting_calculation.id")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = _user_fk()

    __table_args__ = (
        UniqueConstraint("work_order_id", "seq", name="uq_production_wo_operation_seq"),
        CheckConstraint("planned_minutes >= 0 AND (actual_minutes IS NULL OR actual_minutes >= 0)", name="minutes_ok"),
        CheckConstraint("cut_plan_id IS NULL OR is_board_cutting", name="cut_plan_only_on_board_operation"),
        CheckConstraint("(cut_plan_id IS NULL) = (cut_calculation_id IS NULL)", name="cut_plan_with_calculation"),
        Index("ix_production_wo_operation_load", "company_id", "work_center_id", "planned_date"),
        Index(
            "uq_production_wo_operation_cut_plan", "company_id", "cut_plan_id", unique=True,
            postgresql_where="cut_plan_id IS NOT NULL",
        ),
    )


class WoTransaction(TenantEntity, Base):
    """One stock event of a work order (append-only). ``lines`` is the validated snapshot of what moved:
    ``[{material_id | null, product_id, quantity, uom_code, lot_id, from_location_id, to_location_id}]``."""

    __tablename__ = "production_wo_transaction"
    __append_only__ = True

    work_order_id: Mapped[uuid.UUID] = _fk("production_work_order.id", nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": TransactionKind})
    posting_id: Mapped[uuid.UUID] = _fk("inventory_stock_posting.id", nullable=False)
    operation_id: Mapped[uuid.UUID | None] = _fk("production_wo_operation.id")
    lot_id: Mapped[uuid.UUID | None] = _fk("inventory_lot.id")
    lines: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    qty_good: Mapped[Decimal | None] = _qty(nullable=True)
    qty_scrap: Mapped[Decimal | None] = _qty(nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("posting_id", name="uq_production_wo_transaction_posting"),
        Index("ix_production_wo_transaction_wo", "company_id", "work_order_id", "created_at"),
        CheckConstraint("kind <> 'offcut' OR lot_id IS NOT NULL", name="offcut_has_lot"),
    )


# =====================================================================================================
# costing and capacity state
# =====================================================================================================
class CostRollup(TenantEntity, Base):
    """A deterministic cost rollup (append-only). Figures are protected (``pricing.cost.read``, never model-exposed);
    ``missing_inputs`` lists what was excluded, so an incomplete total is never presented as complete."""

    __tablename__ = "production_cost_rollup"
    __append_only__ = True

    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id", nullable=False)
    bom_id: Mapped[uuid.UUID | None] = _fk("production_bom.id")
    routing_id: Mapped[uuid.UUID | None] = _fk("production_routing.id")
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    batch_qty: Mapped[Decimal] = _qty()
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": CostRollupStatus})
    material_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    operation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    breakdown: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    missing_inputs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "input_hash", name="uq_production_cost_rollup_inputs"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("batch_qty > 0", name="batch_qty_positive"),
        CheckConstraint("total_amount = material_amount + operation_amount", name="total_identity"),
        CheckConstraint(
            "(status = 'complete') = (jsonb_array_length(missing_inputs) = 0)", name="status_matches_missing"
        ),
        Index("ix_production_cost_rollup_product", "company_id", "product_id", "created_at"),
    )


class CapacityOverload(TenantEntity, VersionMixin, Base):
    __tablename__ = "production_capacity_overload"

    work_center_id: Mapped[uuid.UUID] = _fk("production_work_center.id", nullable=False)
    load_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": OverloadStatus})
    load_minutes: Mapped[Decimal] = _minutes()
    capacity_minutes: Mapped[Decimal] = _minutes()

    __table_args__ = (
        UniqueConstraint("company_id", "work_center_id", "load_date", name="uq_production_capacity_overload_day"),
    )


MODELS = (
    WorkCenter,
    CapacityException,
    Bom,
    BomLine,
    Routing,
    RoutingOperation,
    WorkOrder,
    WoMaterial,
    WoOperation,
    WoTransaction,
    CostRollup,
    CapacityOverload,
)
