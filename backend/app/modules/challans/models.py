"""Challan tables (Slice 2: documents only, ``inventory_effect = 'none'``).

Design notes (docs/design/source/operations.md §4, CURRENT_STATE_SPEC §4.15, §5.8, §10.1 bugs 13/14):
- ``challans_challan.challan_number`` (``DC-YYYY-NNNN``, yearly reset) is allocated at creation through the atomic
  allocator and never reused: drafts are soft-deleted (``deleted_at``), the business key is immutable (trigger).
- Every legacy header field is kept as printed text (``source_location``, ``destination_party``, ``shipping_name``,
  ``gstin``, ...) next to the structured links (party, consignee, office branch; warehouses are Slice-4 ids without a
  foreign key until the inventory module exists).
- Lines keep the legacy free-text fields plus optional product / custom-product links; ``uom_code`` references the
  company's UOM master; ``(challan_id, line_no)`` is a *deferrable* unique constraint so removal renumbers atomically.
- ``challans_return_link`` records a Return challan line against the original line (``return_line_id`` UNIQUE), and
  ``returned_qty`` on the original line is the running total (CHECK ``returned_qty <= quantity``). No stock effect.
- ``challans_challan_status_history`` is append-only.
- Internal notes are **not** a column: they live in ``platform/collab`` notes and are never printed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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

from app.core.db.base import Base, BranchMixin, IdMixin, TenantEntity, TenantMixin, VersionMixin

#: the deferrable unique constraint ``uow.defer_constraints`` names when lines are renumbered
LINE_NO_CONSTRAINT = "uq_challans_challan_line_line_no"


class Challan(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "challans_challan"

    challan_number: Mapped[str] = mapped_column(String(20), nullable=False)
    challan_date: Mapped[date] = mapped_column(Date, nullable=False)
    challan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    return_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # ---- FROM ----
    source_location: Mapped[str] = mapped_column(String(200), nullable=False)
    source_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    #: Slice 4: FK to ``inventory_warehouse`` once the inventory module exists
    source_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # ---- TO ----
    destination_type: Mapped[str] = mapped_column(String(20), nullable=False)
    destination_party: Mapped[str] = mapped_column(String(200), nullable=False)
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    consignee_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    destination_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    office_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    shipping_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: printed remarks
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    original_challan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=True
    )
    duplicated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=True
    )
    # ---- state ----
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    inventory_effect: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    #: Slice 4 postings (null while ``inventory_effect = 'none'``)
    issue_posting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    reversal_posting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    cancel_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: number of issued revisions (0 for a draft; Slice 2 issues exactly once)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: when the scheduled sweep emitted ``challans.returnable.became_due`` / ``became_overdue`` (once each)
    due_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: normalised number, destination, shipping name and reference for escaped-ILIKE / trigram search
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: who drafted it: user | agent | seed | import | migration | duplicate
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    #: provenance key for idempotent seeds and imports (e.g. ``seed:DC_JOB_WORK``)
    origin_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # ---- soft delete (drafts only; the number is never reused) ----
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("company_id", "challan_number", name="uq_challans_challan_number"),
        Index("ix_challans_challan_status_date", "company_id", "status", "challan_date"),
        Index("ix_challans_challan_party", "company_id", "party_id"),
        Index("ix_challans_challan_type", "company_id", "challan_type"),
        Index("ix_challans_challan_owner", "company_id", "owner_user_id", "status"),
        Index(
            "ix_challans_challan_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        CheckConstraint("challan_number ~ '^DC-[0-9]{4}-[0-9]{4,}$'", name="challan_number_format"),
        CheckConstraint("btrim(destination_party) <> ''", name="destination_party_not_blank"),
        CheckConstraint("btrim(source_location) <> ''", name="source_location_not_blank"),
        CheckConstraint(
            "gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'", name="gstin_format"
        ),
        CheckConstraint("line_count >= 0", name="line_count_non_negative"),
        CheckConstraint("revision_no >= 0", name="revision_no_non_negative"),
        CheckConstraint(
            "challan_type <> 'job_work' OR return_type = 'returnable'", name="job_work_returnable"
        ),
        CheckConstraint(
            "expected_return_date IS NULL OR expected_return_date >= challan_date",
            name="expected_return_after_date",
        ),
        CheckConstraint(
            "original_challan_id IS NULL OR challan_type = 'return'", name="original_only_on_return"
        ),
        CheckConstraint("original_challan_id IS NULL OR original_challan_id <> id", name="original_not_self"),
        CheckConstraint(
            "inventory_effect = 'none' OR issue_posting_id IS NOT NULL OR status = 'draft'",
            name="posting_when_effect",
        ),
        CheckConstraint(
            "(status <> 'issued' AND status <> 'closed') OR issued_at IS NOT NULL", name="issued_has_date"
        ),
        CheckConstraint("(status <> 'closed') OR closed_at IS NOT NULL", name="closed_has_date"),
        CheckConstraint(
            "(status <> 'cancelled') OR cancel_reason_code IS NOT NULL", name="cancelled_has_reason"
        ),
        CheckConstraint("(deleted_at IS NULL) OR (status = 'draft')", name="deleted_draft_only"),
    )


class ChallanLine(TenantEntity, Base):
    __tablename__ = "challans_challan_line"

    challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    #: the legacy ``sort_order`` (1-based, contiguous)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    #: FK to the custom-products table once the commercial-2 module is merged (integrator)
    custom_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_name: Mapped[str] = mapped_column(String(500), nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Return challans: the original line this line returns (document link; no stock effect in Slice 2)
    original_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan_line.id", ondelete="RESTRICT"), nullable=True
    )
    #: running total of quantity returned against this line (maintained from ``challans_return_link``)
    returned_qty: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal(0))
    #: Slice 4: explicit non-stock lines once challans post movements
    is_non_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "challan_id", "line_no", name=LINE_NO_CONSTRAINT, deferrable=True, initially="IMMEDIATE"
        ),
        Index("ix_challans_challan_line_challan", "challan_id", "line_no"),
        Index("ix_challans_challan_line_product", "company_id", "product_id"),
        ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_challans_challan_line_uom",
            ondelete="RESTRICT",
        ),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("returned_qty >= 0 AND returned_qty <= quantity", name="returned_within_quantity"),
        CheckConstraint("btrim(item_name) <> ''", name="item_name_not_blank"),
        CheckConstraint("hsn_sac IS NULL OR hsn_sac ~ '^[0-9]{4,8}$'", name="hsn_sac_format"),
        CheckConstraint(
            "(line_type = 'catalog' AND product_id IS NOT NULL AND custom_product_id IS NULL) "
            "OR (line_type = 'custom' AND product_id IS NULL) "
            "OR (line_type = 'manual' AND product_id IS NULL AND custom_product_id IS NULL)",
            name="line_type_reference",
        ),
    )


class ChallanReturnLink(IdMixin, TenantMixin, Base):
    """One Return-challan line recorded against one original line (document link; Slice 4 adds the posting)."""

    __tablename__ = "challans_return_link"

    return_challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    return_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan_line.id", ondelete="RESTRICT"), nullable=False
    )
    original_challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    original_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan_line.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="returned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: set when the return challan is cancelled (the original line's ``returned_qty`` is reduced again)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("return_line_id", name="uq_challans_return_link_return_line"),
        Index("ix_challans_return_link_original", "original_challan_id", "original_line_id"),
        Index("ix_challans_return_link_return", "return_challan_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("return_challan_id <> original_challan_id", name="not_self"),
    )


class ChallanRevision(IdMixin, TenantMixin, Base):
    """The issued document frozen as an immutable snapshot (append-only; the PDF renders from it deterministically)."""

    __tablename__ = "challans_challan_revision"
    __append_only__ = True

    challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("challan_id", "revision_no", name="uq_challans_challan_revision_no"),
        CheckConstraint("revision_no > 0", name="revision_no_positive"),
    )


class ChallanStatusHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "challans_challan_status_history"
    __append_only__ = True

    challan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("challans_challan.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: the challan version after the transition
    challan_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_challans_challan_status_history_challan", "challan_id", "occurred_at"),)


__all__ = [
    "LINE_NO_CONSTRAINT",
    "Challan",
    "ChallanLine",
    "ChallanReturnLink",
    "ChallanRevision",
    "ChallanStatusHistory",
]
