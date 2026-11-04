"""Quality tables (conventions: ``quality_`` prefix).

``quality_inspection`` (``QC-YYYY-NNNN``): one inspection of a quantity that sits in a warehouse's QC hold, requested by
a goods receipt, a production output or a customer return. Deciding it posts the accepted quantity QC hold -> stock and
the rejected quantity QC hold -> rejected through the inventory posting service (source ``qc_inspection``, purpose
``qc``: exactly one posting per inspection). ``accepted + rejected = quantity`` once decided (CHECK). The checklist
results are a validated JSONB snapshot. ``work_order_id`` references the production work order (FK added by the Slice-4
integrator in 0025).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, BranchMixin, TenantEntity, VersionMixin
from app.modules.quality.enums import InspectionStatus, SubjectType


def _qty(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(18, 4), nullable=nullable, default=default)


class Inspection(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "quality_inspection"

    inspection_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", info={"enum": InspectionStatus}
    )
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False, info={"enum": SubjectType})
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    #: human label of the subject (``GRN-2026-0001 line 1``)
    subject_label: Mapped[str] = mapped_column(String(120), nullable=False)
    #: the subject's document for navigation (GRN, work order, challan)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_work_order.id", ondelete="RESTRICT"), nullable=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lot.id", ondelete="RESTRICT"), nullable=True
    )
    owner_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    qty_accepted: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_rejected: Mapped[Decimal] = _qty(default=Decimal(0))
    #: where accepted stock goes (a stock bin of the warehouse; default its STOCK location)
    release_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_location.id", ondelete="RESTRICT"), nullable=True
    )
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    findings: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reject_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("company_id", "inspection_number", name="uq_quality_inspection_number"),
        #: one live inspection per subject
        Index(
            "uq_quality_inspection_subject_live",
            "company_id",
            "subject_type",
            "subject_id",
            unique=True,
            postgresql_where="status <> 'cancelled'",
        ),
        Index("ix_quality_inspection_status", "company_id", "status", "requested_at"),
        Index("ix_quality_inspection_work_order", "company_id", "work_order_id"),
        CheckConstraint("inspection_number ~ '^QC-[0-9]{4}-[0-9]{4,}$'", name="inspection_number_format"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("qty_accepted >= 0 AND qty_rejected >= 0", name="results_non_negative"),
        CheckConstraint(
            "status IN ('pending', 'cancelled') OR (qty_accepted + qty_rejected = quantity AND posting_id IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="decided_is_complete",
        ),
        CheckConstraint("status <> 'passed' OR qty_rejected = 0", name="passed_has_no_rejects"),
        CheckConstraint("status <> 'failed' OR qty_rejected > 0", name="failed_has_rejects"),
    )
