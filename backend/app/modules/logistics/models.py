"""Logistics tables (conventions: ``logistics_`` prefix; operations.md §8).

- ``logistics_packing_list`` (``PK-YYYY-NNNN``; ``PL-`` belongs to inventory pick lists): draft -> final | cancelled.
  Lines snapshot the catalogue packaging at creation (carton quantity and dimensions, stated CBM, unit / net / gross
  weights, packing type, fragile flag, the packaging row's ``updated_at``) and store the computed cartons, CBM and
  weights (Decimal, HALF_UP). A draft is flagged stale when the packaging or the order changes; a final list never
  changes.
- ``logistics_shipment`` (``SH-YYYY-NNNN``): planned -> booked -> dispatched -> in_transit -> delivered (with evidence);
  exception; cancelled. ``cutoff_at`` is the dispatch cutoff in UTC, entered as a company-local date and time. The
  shipment never posts stock: it links the challan whose issue is the one stock movement (``dispatch_posting_id``).
- ``logistics_shipment_tracking_ref``: AWB, BL, LR, container and seal numbers.
- ``logistics_container_profile``: entered internal volume, payload and fill factor for load suggestions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, BranchMixin, TenantEntity, VersionMixin
from app.modules.logistics.enums import (
    EvidenceKind,
    ExceptionCode,
    PackingListStatus,
    ShipmentMode,
    ShipmentStatus,
    TrackingRefType,
)


def _fk(target: str, nullable: bool = False) -> Any:
    return mapped_column(Uuid(as_uuid=True), ForeignKey(target, ondelete="RESTRICT"), nullable=nullable)


def _dec(precision: int, scale: int, nullable: bool = True) -> Any:
    return mapped_column(Numeric(precision, scale), nullable=nullable)


class PackingList(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "logistics_packing_list"

    packing_list_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": PackingListStatus}
    )
    sales_order_id: Mapped[uuid.UUID] = _fk("orders_sales_order.id")
    challan_id: Mapped[uuid.UUID | None] = _fk("challans_challan.id", nullable=True)
    party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: the order's owner (sales see the packing lists of their own orders)
    owner_user_id: Mapped[uuid.UUID] = _fk("app_user.id")
    total_cartons: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cbm: Mapped[Decimal] = _dec(14, 6, nullable=False)
    total_net_kg: Mapped[Decimal] = _dec(14, 3, nullable=False)
    total_gross_kg: Mapped[Decimal] = _dec(14, 3, nullable=False)
    totals_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_estimates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finalised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalised_by: Mapped[uuid.UUID | None] = _fk("app_user.id", nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "packing_list_number", name="uq_logistics_packing_list_number"),
        Index("ix_logistics_packing_list_order", "company_id", "sales_order_id"),
        CheckConstraint("packing_list_number ~ '^PK-[0-9]{4}-[0-9]{4,}$'", name="packing_list_number_format"),
        CheckConstraint(
            "total_cartons >= 0 AND total_cbm >= 0 AND total_net_kg >= 0 AND total_gross_kg >= 0",
            name="totals_non_negative",
        ),
        CheckConstraint(
            "status <> 'final' OR (finalised_at IS NOT NULL AND NOT is_stale)", name="final_is_fresh"
        ),
    )


class PackingListLine(TenantEntity, Base):
    __tablename__ = "logistics_packing_list_line"

    packing_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("logistics_packing_list.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id")
    sales_order_line_id: Mapped[uuid.UUID | None] = _fk("orders_sales_order_line.id", nullable=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[Decimal] = _dec(18, 4, nullable=False)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    # ---- packaging snapshot at creation / refresh ----
    carton_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inner_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carton_length_cm: Mapped[Decimal | None] = _dec(12, 3)
    carton_width_cm: Mapped[Decimal | None] = _dec(12, 3)
    carton_height_cm: Mapped[Decimal | None] = _dec(12, 3)
    stated_carton_cbm: Mapped[Decimal | None] = _dec(12, 6)
    unit_weight_kg: Mapped[Decimal | None] = _dec(14, 6)
    carton_net_kg: Mapped[Decimal | None] = _dec(12, 4)
    carton_gross_kg: Mapped[Decimal | None] = _dec(12, 4)
    packing_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_fragile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    packaging_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ---- computed ----
    full_cartons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loose_qty: Mapped[Decimal | None] = _dec(18, 4)
    cartons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inner_packs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_part_carton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    carton_cbm: Mapped[Decimal | None] = _dec(12, 6)
    cbm: Mapped[Decimal | None] = _dec(14, 6)
    net_kg: Mapped[Decimal | None] = _dec(14, 3)
    gross_kg: Mapped[Decimal | None] = _dec(14, 3)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    incomplete_reasons: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, default=list)
    # ---- entered values for missing / conflicting data (with a reason) ----
    override_cbm: Mapped[Decimal | None] = _dec(14, 6)
    override_net_kg: Mapped[Decimal | None] = _dec(14, 3)
    override_gross_kg: Mapped[Decimal | None] = _dec(14, 3)
    override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("packing_list_id", "line_no", name="uq_logistics_packing_list_line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "(override_cbm IS NULL AND override_net_kg IS NULL AND override_gross_kg IS NULL) OR override_reason IS NOT NULL",
            name="override_has_reason",
        ),
    )


class Shipment(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "logistics_shipment"

    shipment_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned", info={"enum": ShipmentStatus}
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": ShipmentMode})
    sales_order_id: Mapped[uuid.UUID | None] = _fk("orders_sales_order.id", nullable=True)
    challan_id: Mapped[uuid.UUID | None] = _fk("challans_challan.id", nullable=True)
    packing_list_id: Mapped[uuid.UUID | None] = _fk("logistics_packing_list.id", nullable=True)
    party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = _fk("app_user.id")
    transporter_party_id: Mapped[uuid.UUID | None] = _fk("parties_party.id", nullable=True)
    transporter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_dispatch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: the cutoff as entered (company-local date and time) and as an instant
    cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cutoff_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_posting_id: Mapped[uuid.UUID | None] = _fk("inventory_stock_posting.id", nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_kind: Mapped[str | None] = mapped_column(String(30), nullable=True, info={"enum": EvidenceKind})
    evidence_file_id: Mapped[uuid.UUID | None] = _fk("file_object.id", nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    exception_code: Mapped[str | None] = mapped_column(
        String(30), nullable=True, info={"enum": ExceptionCode}
    )
    exception_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    exception_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "shipment_number", name="uq_logistics_shipment_number"),
        Index("ix_logistics_shipment_status_cutoff", "company_id", "status", "cutoff_at"),
        Index("ix_logistics_shipment_challan", "company_id", "challan_id"),
        Index("ix_logistics_shipment_order", "company_id", "sales_order_id"),
        CheckConstraint("shipment_number ~ '^SH-[0-9]{4}-[0-9]{4,}$'", name="shipment_number_format"),
        CheckConstraint("(cutoff_date IS NULL) = (cutoff_at IS NULL)", name="cutoff_complete"),
        CheckConstraint(
            "status NOT IN ('dispatched', 'in_transit', 'delivered') OR (dispatched_at IS NOT NULL AND challan_id IS NOT NULL)",
            name="dispatched_has_challan",
        ),
        CheckConstraint(
            "status <> 'delivered' OR (delivered_at IS NOT NULL AND evidence_kind IS NOT NULL)",
            name="delivered_has_evidence",
        ),
        CheckConstraint("status <> 'exception' OR exception_code IS NOT NULL", name="exception_has_code"),
    )


class ShipmentTrackingRef(TenantEntity, Base):
    __tablename__ = "logistics_shipment_tracking_ref"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("logistics_shipment.id", ondelete="CASCADE"), nullable=False
    )
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": TrackingRefType})
    value: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (UniqueConstraint("shipment_id", "ref_type", "value", name="uq_logistics_tracking_ref"),)


class ContainerProfile(TenantEntity, VersionMixin, Base):
    __tablename__ = "logistics_container_profile"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    internal_volume_m3: Mapped[Decimal] = _dec(10, 3, nullable=False)
    max_payload_kg: Mapped[Decimal] = _dec(12, 3, nullable=False)
    fill_factor: Mapped[Decimal] = _dec(4, 3, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_logistics_container_profile_code"),
        CheckConstraint("internal_volume_m3 > 0 AND max_payload_kg > 0", name="capacity_positive"),
        CheckConstraint("fill_factor > 0 AND fill_factor <= 1", name="fill_factor_range"),
    )
