"""Inventory tables (docs/design/source/operations.md §3, ADR-021, conventions §3 names).

- Locations: every warehouse has STOCK (internal, the default), QC (qc_hold) and REJ (rejected) plus bins (internal
  children). Company locations without a warehouse: one virtual location per type (supplier, customer, production,
  scrap, adjustment, opening, sample_consumption; may go negative) and the in-transit holding (stock-bearing).
  ``external_holding`` locations exist once per party (fabricator, job worker, customer holding returnable goods);
  the stock there stays company-owned. ``office`` locations exist once per office branch.
- Ledger: ``inventory_stock_posting`` (one per source event: UNIQUE(company, source_type, source_id, purpose)) and its
  ``inventory_stock_movement`` rows (from one location to another, quantity > 0 in the product's stock unit). Both
  are append-only (trigger). Corrections are reversal postings that point at the original.
- Projections updated by ``posting.py`` only, in the same transaction: ``inventory_stock_balance`` per (product,
  location, lot, owner) with NULLS NOT DISTINCT and CHECK (NOT enforce_non_negative OR quantity >= 0), and
  ``inventory_stock_summary`` per (product, warehouse) holding available on-hand and reserved (CHECKs >= 0). Reserving
  and posting lock the same summary row, so two requests can never take the same units.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
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

from app.core.db.base import Base, BranchMixin, IdMixin, TenantEntity, TenantMixin, VersionMixin
from app.modules.inventory.enums import (
    AdjustmentDirection,
    AdjustmentReason,
    AdjustmentStatus,
    CountStatus,
    DemandType,
    LocationType,
    LotKind,
    LotVerification,
    OpeningStatus,
    PickLineStatus,
    PickListStatus,
    PostingPurpose,
    ReservationStatus,
    ShortageStatus,
    SourceType,
    TransferStatus,
)


def _qty(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(18, 6), nullable=nullable, default=default)


def _uom_fk(table: str, column: str = "uom_code") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["company_id", column],
        ["uom.company_id", "uom.code"],
        name=f"fk_{table}_{column}",
        ondelete="RESTRICT",
    )


def _user_fk(nullable: bool = True) -> Any:
    return mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=nullable
    )


# =====================================================================================================
# master data
# =====================================================================================================
class Warehouse(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "inventory_warehouse"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: domestic or export stock (module 4); NULL for warehouses not yet classified
    market: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: provenance key for idempotent seeds (``seed:WH-MAIN``)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_inventory_warehouse_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9-]{0,19}$'", name="code_format"),
        CheckConstraint("market IS NULL OR market IN ('domestic', 'export')", name="market_values"),
        CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="country_code_format"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


class Location(TenantEntity, Base):
    __tablename__ = "inventory_location"

    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False, info={"enum": LocationType})
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=True
    )
    #: external_holding: the party holding company-owned goods
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    #: office: the branch whose office holds the goods
    office_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    is_stock_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    counts_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: the warehouse's default internal location (picking and put-away when no bin is named)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: inventory / sample / exhibition (module 4): one stock pool split by category; NULL for non-stock locations
    stock_category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "code",
            name="uq_inventory_location_code",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_inventory_location_party_holding",
            "company_id",
            "party_id",
            unique=True,
            postgresql_where="location_type = 'external_holding'",
        ),
        Index(
            "uq_inventory_location_default",
            "company_id",
            "warehouse_id",
            unique=True,
            postgresql_where="is_default",
        ),
        CheckConstraint(
            "(location_type IN ('internal', 'qc_hold', 'rejected', 'wip')) = (warehouse_id IS NOT NULL)",
            name="warehouse_bound_types",
        ),
        CheckConstraint(
            "(location_type = 'external_holding') = (party_id IS NOT NULL)", name="holding_has_party"
        ),
        CheckConstraint(
            "(location_type = 'office') = (office_branch_id IS NOT NULL)", name="office_has_branch"
        ),
        CheckConstraint("NOT is_default OR location_type = 'internal'", name="default_is_internal"),
        CheckConstraint("NOT counts_available OR is_stock_bearing", name="available_is_stock_bearing"),
        CheckConstraint(
            "stock_category IS NULL OR stock_category IN ('inventory', 'sample', 'exhibition')", name="stock_category_values"
        ),
        CheckConstraint(
            "stock_category IS NULL OR (location_type = 'internal' AND warehouse_id IS NOT NULL)",
            name="stock_category_internal",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
    )


class Lot(TenantEntity, VersionMixin, Base):
    __tablename__ = "inventory_lot"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(60), nullable=False)
    lot_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", info={"enum": LotKind}
    )
    supplier_lot_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parent_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    thickness_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    grain_axis: Mapped[str | None] = mapped_column(String(10), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified", info={"enum": LotVerification}
    )
    measured_by: Mapped[uuid.UUID | None] = _user_fk()
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "lot_code", name="uq_inventory_lot_code"),
        CheckConstraint("btrim(lot_code) <> ''", name="lot_code_not_blank"),
        CheckConstraint(
            "(length_mm IS NULL OR length_mm > 0) AND (width_mm IS NULL OR width_mm > 0) "
            "AND (thickness_mm IS NULL OR thickness_mm > 0)",
            name="dimensions_positive",
        ),
        CheckConstraint(
            "grain_axis IS NULL OR grain_axis IN ('length', 'width', 'none')", name="grain_axis_values"
        ),
    )


# =====================================================================================================
# the ledger (append-only)
# =====================================================================================================
class StockPosting(IdMixin, TenantMixin, Base):
    __tablename__ = "inventory_stock_posting"
    __append_only__ = True

    source_type: Mapped[str] = mapped_column(String(30), nullable=False, info={"enum": SourceType})
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": PostingPurpose})
    #: the source document's business number (display; e.g. DC-2026-0004)
    source_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_by: Mapped[uuid.UUID | None] = _user_fk()
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reverses_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )
    movement_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_inventory_stock_posting_idempotency_key"),
        UniqueConstraint(
            "company_id", "source_type", "source_id", "purpose", name="uq_inventory_stock_posting_source"
        ),
        UniqueConstraint("reverses_posting_id", name="uq_inventory_stock_posting_reverses"),
        Index("ix_inventory_stock_posting_posted", "company_id", "posted_at"),
        CheckConstraint("movement_count > 0", name="has_movements"),
        CheckConstraint("reverses_posting_id IS NULL OR reverses_posting_id <> id", name="not_self_reversal"),
    )


class StockMovement(IdMixin, TenantMixin, Base):
    __tablename__ = "inventory_stock_movement"
    __append_only__ = True

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    posting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    #: NULL: company-owned; a party: customer- or vendor-owned material
    owner_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    from_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    #: denormalised from the locations (record scope and the ledger browser filter on them)
    from_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=True
    )
    to_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=True
    )
    #: in the product's stock unit
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    entered_qty: Mapped[Decimal] = _qty()
    entered_uom: Mapped[str] = mapped_column(String(16), nullable=False)
    counterparty_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_reservation.id", ondelete="RESTRICT"), nullable=True
    )
    source_line_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("posting_id", "line_no", name="uq_inventory_stock_movement_line"),
        UniqueConstraint("seq", name="uq_inventory_stock_movement_seq"),
        Index("ix_inventory_stock_movement_product_seq", "company_id", "product_id", "seq"),
        Index("ix_inventory_stock_movement_posting", "company_id", "posting_id"),
        Index("ix_inventory_stock_movement_source_line", "company_id", "source_line_id"),
        _uom_fk("inventory_stock_movement"),
        CheckConstraint("from_location_id <> to_location_id", name="from_not_to"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("entered_qty > 0", name="entered_positive"),
    )


# =====================================================================================================
# projections (written only by posting.py and reservations.py, in the posting transaction)
# =====================================================================================================
class StockBalance(IdMixin, TenantMixin, Base):
    __tablename__ = "inventory_stock_balance"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    owner_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = _qty(default=Decimal(0))
    enforce_non_negative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_movement_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_movement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "product_id",
            "location_id",
            "lot_id",
            "owner_party_id",
            name="uq_inventory_stock_balance_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_inventory_stock_balance_warehouse", "company_id", "warehouse_id", "product_id"),
        CheckConstraint("NOT enforce_non_negative OR quantity >= 0", name="non_negative"),
    )


class StockSummary(IdMixin, TenantMixin, Base):
    """Per (product, warehouse): company-owned quantity in available locations (excluding offcut lots) and reserved."""

    __tablename__ = "inventory_stock_summary"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    available_on_hand: Mapped[Decimal] = _qty(default=Decimal(0))
    reserved: Mapped[Decimal] = _qty(default=Decimal(0))
    #: bumped by every posting and reservation change (shortage refresh and briefing staleness)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "warehouse_id", name="uq_inventory_stock_summary_key"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("available_on_hand >= 0", name="available_non_negative"),
    )


class Reservation(TenantEntity, VersionMixin, Base):
    __tablename__ = "inventory_reservation"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    #: in the product's stock unit
    quantity: Mapped[Decimal] = _qty()
    consumed_qty: Mapped[Decimal] = _qty(default=Decimal(0))
    released_qty: Mapped[Decimal] = _qty(default=Decimal(0))
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", info={"enum": ReservationStatus}
    )
    demand_type: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": DemandType})
    demand_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    #: the demand's header (e.g. the sales order of an SO line), for scope and grouping
    demand_parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    demand_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[uuid.UUID | None] = _user_fk()
    release_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index(
            "ix_inventory_reservation_active",
            "company_id",
            "product_id",
            "warehouse_id",
            postgresql_where="status = 'active'",
        ),
        Index("ix_inventory_reservation_demand", "company_id", "demand_type", "demand_id"),
        Index("ix_inventory_reservation_parent", "company_id", "demand_parent_id"),
        _uom_fk("inventory_reservation"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("consumed_qty >= 0 AND released_qty >= 0", name="counters_non_negative"),
        CheckConstraint("consumed_qty + released_qty <= quantity", name="within_quantity"),
        CheckConstraint(
            "status <> 'active' OR consumed_qty + released_qty < quantity", name="active_has_remaining"
        ),
    )


class ShortageState(IdMixin, TenantMixin, Base):
    """One row per (product, warehouse): unreserved demand exceeding free available stock (``inventory.shortage.*``)."""

    __tablename__ = "inventory_shortage_state"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": ShortageStatus})
    #: in the product's stock unit; read models only (never in event payloads)
    demand_qty: Mapped[Decimal] = _qty(default=Decimal(0))
    free_qty: Mapped[Decimal] = _qty(default=Decimal(0))
    shortfall_qty: Mapped[Decimal] = _qty(default=Decimal(0))
    #: [{type, id}] demands (and later supply delays) that cause the shortage; sorted, deterministic
    caused_by: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "warehouse_id", name="uq_inventory_shortage_state_key"),
        CheckConstraint(
            "demand_qty >= 0 AND free_qty >= 0 AND shortfall_qty >= 0", name="quantities_non_negative"
        ),
        CheckConstraint("(status = 'open') = (shortfall_qty > 0)", name="open_when_short"),
    )


class ReorderRule(TenantEntity, VersionMixin, Base):
    __tablename__ = "inventory_reorder_rule"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    min_qty: Mapped[Decimal] = _qty()
    max_qty: Mapped[Decimal] = _qty()
    reorder_qty: Mapped[Decimal] = _qty()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("company_id", "product_id", "warehouse_id", name="uq_inventory_reorder_rule_key"),
        CheckConstraint("min_qty >= 0 AND max_qty >= min_qty AND reorder_qty > 0", name="levels_consistent"),
    )


# =====================================================================================================
# documents
# =====================================================================================================
class _DocumentMixin:
    """Numbered warehouse documents (number from the allocator, never reused)."""

    number: Mapped[str] = mapped_column(String(30), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class PickList(_DocumentMixin, TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "inventory_pick_list"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": PickListStatus}
    )
    assignee_user_id: Mapped[uuid.UUID | None] = _user_fk()
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[uuid.UUID | None] = _user_fk()
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_by: Mapped[uuid.UUID | None] = _user_fk()
    #: the draft challan generated from the picked quantities (no second movement: the challan posts)
    challan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_inventory_pick_list_number"),
        Index("ix_inventory_pick_list_order", "company_id", "order_id"),
        CheckConstraint("posting_id IS NULL", name="picking_posts_nothing"),
    )


class PickListLine(TenantEntity, Base):
    __tablename__ = "inventory_pick_list_line"

    pick_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_pick_list.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    order_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order_line.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_reservation.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    qty_requested: Mapped[Decimal] = _qty()
    qty_picked: Mapped[Decimal | None] = _qty(nullable=True)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", info={"enum": PickLineStatus}
    )

    __table_args__ = (
        UniqueConstraint("pick_list_id", "line_no", name="uq_inventory_pick_list_line_no"),
        _uom_fk("inventory_pick_list_line"),
        CheckConstraint("qty_requested > 0", name="requested_positive"),
        CheckConstraint(
            "qty_picked IS NULL OR (qty_picked >= 0 AND qty_picked <= qty_requested)", name="picked_range"
        ),
    )


class StockCount(_DocumentMixin, TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "inventory_stock_count"

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": CountStatus}
    )
    #: count only this location (and its bins); NULL: every internal location of the warehouse
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=True
    )
    #: the movement-sequence high-water mark at freeze (movements after it stay valid)
    snapshot_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[uuid.UUID | None] = _user_fk()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = _user_fk()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = _user_fk()

    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_inventory_stock_count_number"),
        CheckConstraint(
            "status IN ('draft', 'cancelled') OR snapshot_seq IS NOT NULL", name="frozen_has_snapshot"
        ),
        #: a count with no variance posts nothing, so ``posting_id`` may stay NULL when posted
        CheckConstraint("status <> 'posted' OR approved_by IS NOT NULL", name="posted_is_approved"),
        CheckConstraint(
            "approved_by IS NULL OR submitted_by IS NULL OR approved_by <> submitted_by",
            name="approver_not_counter",
        ),
    )


class StockCountLine(TenantEntity, Base):
    __tablename__ = "inventory_stock_count_line"

    stock_count_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_count.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    system_qty_at_snapshot: Mapped[Decimal] = _qty()
    counted_qty: Mapped[Decimal | None] = _qty(nullable=True)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint("stock_count_id", "line_no", name="uq_inventory_stock_count_line_no"),
        UniqueConstraint(
            "stock_count_id",
            "product_id",
            "location_id",
            "lot_id",
            name="uq_inventory_stock_count_line_key",
            postgresql_nulls_not_distinct=True,
        ),
        _uom_fk("inventory_stock_count_line"),
        CheckConstraint("system_qty_at_snapshot >= 0", name="system_non_negative"),
        CheckConstraint("counted_qty IS NULL OR counted_qty >= 0", name="counted_non_negative"),
    )


class Adjustment(_DocumentMixin, TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "inventory_adjustment"

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": AdjustmentStatus}
    )
    reason_code: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": AdjustmentReason})
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = _user_fk()
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_inventory_adjustment_number"),
        CheckConstraint("decided_by IS NULL OR decided_by <> created_by", name="approver_not_creator"),
        CheckConstraint("(status = 'posted') = (posting_id IS NOT NULL)", name="posted_has_posting"),
    )


class AdjustmentLine(TenantEntity, Base):
    __tablename__ = "inventory_adjustment_line"

    adjustment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_adjustment.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(5), nullable=False, info={"enum": AdjustmentDirection})
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint("adjustment_id", "line_no", name="uq_inventory_adjustment_line_no"),
        _uom_fk("inventory_adjustment_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class OpeningBatch(_DocumentMixin, TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "inventory_opening_batch"

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": OpeningStatus}
    )
    source_file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = _user_fk()
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_inventory_opening_batch_number"),
        #: opening stock is approved by a second person, never its creator (DB-enforced separation of duties)
        CheckConstraint("decided_by IS NULL OR decided_by <> created_by", name="approver_not_creator"),
        CheckConstraint("(status = 'posted') = (posting_id IS NOT NULL)", name="posted_has_posting"),
    )


class OpeningBatchLine(TenantEntity, Base):
    __tablename__ = "inventory_opening_batch_line"

    opening_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_opening_batch.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=False
    )
    lot_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_row_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: allow opening stock where non-opening movements already exist (explicit, reviewed)
    late_opening: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("opening_batch_id", "line_no", name="uq_inventory_opening_batch_line_no"),
        _uom_fk("inventory_opening_batch_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class Transfer(TenantEntity, VersionMixin, BranchMixin, Base):
    """Warehouse-to-warehouse transfer in two postings: dispatch (internal A -> in transit), receive (-> internal B)."""

    __tablename__ = "inventory_transfer"

    number: Mapped[str] = mapped_column(String(30), nullable=False)
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": TransferStatus}
    )
    dispatch_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )
    receive_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_inventory_transfer_number"),
        CheckConstraint("from_warehouse_id <> to_warehouse_id", name="different_warehouses"),
        CheckConstraint(
            "status IN ('draft', 'cancelled') OR dispatch_posting_id IS NOT NULL", name="dispatched_posted"
        ),
        CheckConstraint("status <> 'received' OR receive_posting_id IS NOT NULL", name="received_posted"),
    )


class TransferLine(TenantEntity, Base):
    __tablename__ = "inventory_transfer_line"

    transfer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_transfer.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint("transfer_id", "line_no", name="uq_inventory_transfer_line_no"),
        _uom_fk("inventory_transfer_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


__all__ = [
    "Adjustment",
    "AdjustmentLine",
    "Location",
    "Lot",
    "OpeningBatch",
    "OpeningBatchLine",
    "PickList",
    "PickListLine",
    "ReorderRule",
    "Reservation",
    "ShortageState",
    "StockBalance",
    "StockCount",
    "StockCountLine",
    "StockMovement",
    "StockPosting",
    "StockSummary",
    "Transfer",
    "TransferLine",
    "Warehouse",
]
