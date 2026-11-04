"""Procurement tables (operations.md §5; conventions: ``procurement_`` prefix).

- ``procurement_vendor_item``: what a vendor sells us (vendor code, lead time, price with currency). Versions are kept:
  a price change creates a new row and the old one points at it (``superseded_by_id``); one active row per
  (vendor, product).
- ``procurement_requisition`` (``PR-YYYY-NNNN``): draft -> submitted -> approved | rejected -> closed (or cancelled).
  The approver is never the requester or the submitter (service check plus CHECK).
- ``procurement_purchase_order`` (``PO-YYYY-NNNN``): draft -> pending_approval -> approved -> issued ->
  partially_received -> received -> closed; cancelled. The approver is never the submitter (CHECK). Lines carry the
  expected date, the received / accepted / rejected / cancelled / billed figures (CHECKs keep them consistent) and a
  generated ``qty_outstanding``.
- ``procurement_goods_receipt`` (``GRN-YYYY-NNNN``): partial receipts per PO line; posting moves stock from the
  supplier location into QC hold (QC-required products) or stock through the inventory posting service.
- ``procurement_vendor_bill`` (+ lines): three-way match against the PO and accepted receipts; a matched bill is
  handed off to finance as an event (Slice 4).
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
    Computed,
    Date,
    DateTime,
    ForeignKey,
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
from app.modules.procurement.enums import (
    GoodsReceiptStatus,
    MatchStatus,
    PurchaseOrderStatus,
    RequisitionStatus,
    VendorBillStatus,
)

_CURRENCIES = "('INR', 'EUR', 'USD', 'GBP')"


def _qty(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(18, 4), nullable=nullable, default=default)


def _money(nullable: bool = False, default: Decimal | None = None) -> Any:
    return mapped_column(Numeric(18, 4), nullable=nullable, default=default)


def _user_fk(nullable: bool = True) -> Any:
    return mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=nullable
    )


def _fk(target: str, nullable: bool = False) -> Any:
    return mapped_column(Uuid(as_uuid=True), ForeignKey(target, ondelete="RESTRICT"), nullable=nullable)


class VendorItem(TenantEntity, VersionMixin, Base):
    __tablename__ = "procurement_vendor_item"

    vendor_party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id")
    vendor_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[Decimal] = _money()
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    price_uom: Mapped[str] = mapped_column(String(16), nullable=False)
    min_order_qty: Mapped[Decimal | None] = _qty(nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("procurement_vendor_item.id", ondelete="RESTRICT"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")

    __table_args__ = (
        Index(
            "uq_procurement_vendor_item_active",
            "company_id",
            "vendor_party_id",
            "product_id",
            unique=True,
            postgresql_where="is_active",
        ),
        Index("ix_procurement_vendor_item_product", "company_id", "product_id"),
        CheckConstraint("unit_price > 0", name="price_positive"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_non_negative"),
        CheckConstraint("min_order_qty IS NULL OR min_order_qty > 0", name="moq_positive"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_ordered"),
        CheckConstraint(
            "is_active OR superseded_by_id IS NOT NULL OR valid_to IS NOT NULL", name="inactive_has_reason"
        ),
    )


class Requisition(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "procurement_requisition"

    requisition_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": RequisitionStatus}
    )
    warehouse_id: Mapped[uuid.UUID] = _fk("inventory_warehouse.id")
    owner_user_id: Mapped[uuid.UUID] = _user_fk(nullable=False)
    required_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = _user_fk()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = _user_fk()
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "requisition_number", name="uq_procurement_requisition_number"),
        Index("ix_procurement_requisition_status", "company_id", "status"),
        CheckConstraint("requisition_number ~ '^PR-[0-9]{4}-[0-9]{4,}$'", name="requisition_number_format"),
        #: separation of duties in the database: the decider is neither the requester nor the submitter
        CheckConstraint(
            "decided_by IS NULL OR (decided_by <> owner_user_id AND decided_by IS DISTINCT FROM submitted_by)",
            name="decider_not_requester",
        ),
        CheckConstraint(
            "status IN ('draft', 'cancelled') OR submitted_at IS NOT NULL", name="submitted_has_date"
        ),
    )


class RequisitionLine(TenantEntity, Base):
    __tablename__ = "procurement_requisition_line"

    requisition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("procurement_requisition.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id")
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    required_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    suggested_vendor_item_id: Mapped[uuid.UUID | None] = _fk("procurement_vendor_item.id", nullable=True)
    #: what raised the need (e.g. ``inventory.shortage``), for traceability
    demand_ref_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    demand_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    qty_ordered: Mapped[Decimal] = _qty(default=Decimal(0))
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("requisition_id", "line_no", name="uq_procurement_requisition_line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("qty_ordered >= 0", name="ordered_non_negative"),
    )


class PurchaseOrder(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "procurement_purchase_order"

    po_number: Mapped[str] = mapped_column(String(20), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    vendor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = _fk("inventory_warehouse.id")
    owner_user_id: Mapped[uuid.UUID] = _user_fk(nullable=False)
    requisition_id: Mapped[uuid.UUID | None] = _fk("procurement_requisition.id", nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": PurchaseOrderStatus}
    )
    total_amount: Mapped[Decimal] = _money(default=Decimal(0))
    vendor_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = _user_fk()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = _user_fk()
    #: the version the approver saw; issuing re-checks it
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = _user_fk()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "po_number", name="uq_procurement_purchase_order_number"),
        Index("ix_procurement_purchase_order_status", "company_id", "status"),
        Index("ix_procurement_purchase_order_vendor", "company_id", "vendor_party_id"),
        CheckConstraint("po_number ~ '^PO-[0-9]{4}-[0-9]{4,}$'", name="po_number_format"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        #: separation of duties in the database: the approver never approves their own submission
        CheckConstraint(
            "approved_by IS NULL OR approved_by IS DISTINCT FROM submitted_by", name="approver_not_submitter"
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'cancelled') OR approved_by IS NOT NULL",
            name="approved_has_approver",
        ),
        CheckConstraint(
            "(status <> 'cancelled') OR status_reason_code IS NOT NULL", name="cancel_has_reason"
        ),
    )


class PurchaseOrderLine(TenantEntity, VersionMixin, Base):
    __tablename__ = "procurement_purchase_order_line"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("procurement_purchase_order.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id")
    vendor_item_id: Mapped[uuid.UUID | None] = _fk("procurement_vendor_item.id", nullable=True)
    requisition_line_id: Mapped[uuid.UUID | None] = _fk("procurement_requisition_line.id", nullable=True)
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price: Mapped[Decimal] = _money()
    price_override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    line_amount: Mapped[Decimal] = _money()
    lead_time_days_assumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    over_receipt_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal(0)
    )
    qty_received: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_accepted: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_rejected: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_cancelled: Mapped[Decimal] = _qty(default=Decimal(0))
    qty_billed: Mapped[Decimal] = _qty(default=Decimal(0))
    #: what the vendor still owes: ordered - cancelled - (received - rejected), never below zero
    qty_outstanding: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        Computed("GREATEST(quantity - qty_cancelled - (qty_received - qty_rejected), 0)", persisted=True),
    )
    #: stamp of the overdue sweep (cleared when the expected date moves)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("purchase_order_id", "line_no", name="uq_procurement_purchase_order_line_no"),
        Index("ix_procurement_purchase_order_line_product", "company_id", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
        CheckConstraint("line_amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "over_receipt_tolerance_pct >= 0 AND over_receipt_tolerance_pct <= 100", name="tolerance_range"
        ),
        CheckConstraint(
            "qty_received >= 0 AND qty_accepted >= 0 AND qty_rejected >= 0 AND qty_cancelled >= 0 AND qty_billed >= 0",
            name="figures_non_negative",
        ),
        CheckConstraint("qty_accepted + qty_rejected <= qty_received", name="inspected_within_received"),
        CheckConstraint("qty_cancelled <= quantity", name="cancelled_within_ordered"),
        CheckConstraint("qty_billed <= qty_accepted", name="billed_within_accepted"),
    )


class GoodsReceipt(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "procurement_goods_receipt"

    grn_number: Mapped[str] = mapped_column(String(20), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = _fk("procurement_purchase_order.id")
    vendor_party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    warehouse_id: Mapped[uuid.UUID] = _fk("inventory_warehouse.id")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": GoodsReceiptStatus}
    )
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_challan_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    vendor_invoice_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    posting_id: Mapped[uuid.UUID | None] = _fk("inventory_stock_posting.id", nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[uuid.UUID | None] = _user_fk()

    __table_args__ = (
        UniqueConstraint("company_id", "grn_number", name="uq_procurement_goods_receipt_number"),
        Index("ix_procurement_goods_receipt_po", "company_id", "purchase_order_id"),
        CheckConstraint("grn_number ~ '^GRN-[0-9]{4}-[0-9]{4,}$'", name="grn_number_format"),
        CheckConstraint("(status <> 'posted') OR posting_id IS NOT NULL", name="posted_has_posting"),
    )


class GoodsReceiptLine(TenantEntity, Base):
    __tablename__ = "procurement_goods_receipt_line"

    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("procurement_goods_receipt.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_line_id: Mapped[uuid.UUID] = _fk("procurement_purchase_order_line.id")
    product_id: Mapped[uuid.UUID] = _fk("catalogue_product.id")
    quantity: Mapped[Decimal] = _qty()
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    lot_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    supplier_lot_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lot_id: Mapped[uuid.UUID | None] = _fk("inventory_lot.id", nullable=True)
    #: where the goods went: the warehouse's QC hold (QC-required products) or a stock location
    location_id: Mapped[uuid.UUID | None] = _fk("inventory_location.id", nullable=True)
    qc_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("goods_receipt_id", "line_no", name="uq_procurement_goods_receipt_line_no"),
        Index("ix_procurement_goods_receipt_line_po_line", "company_id", "po_line_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )


class VendorBill(TenantEntity, VersionMixin, Base):
    __tablename__ = "procurement_vendor_bill"

    vendor_party_id: Mapped[uuid.UUID] = _fk("parties_party.id")
    purchase_order_id: Mapped[uuid.UUID] = _fk("procurement_purchase_order.id")
    bill_number: Mapped[str] = mapped_column(String(60), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    #: as entered from the vendor's document
    subtotal_amount: Mapped[Decimal] = _money()
    tax_amount: Mapped[Decimal] = _money(default=Decimal(0))
    total_amount: Mapped[Decimal] = _money()
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": VendorBillStatus}
    )
    match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", info={"enum": MatchStatus}
    )
    #: validated list of {code, po_line_id, line_no, expected, actual} (MatchException)
    match_exceptions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handed_off_by: Mapped[uuid.UUID | None] = _user_fk()
    accounting_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "vendor_party_id", "bill_number", name="uq_procurement_vendor_bill_number"
        ),
        Index("ix_procurement_vendor_bill_po", "company_id", "purchase_order_id"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint(
            "subtotal_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="amounts_non_negative"
        ),
        CheckConstraint(
            "(status <> 'handed_off') OR (match_status = 'matched' AND handed_off_at IS NOT NULL)",
            name="handoff_only_matched",
        ),
    )


class VendorBillLine(TenantEntity, Base):
    __tablename__ = "procurement_vendor_bill_line"

    vendor_bill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("procurement_vendor_bill.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    po_line_id: Mapped[uuid.UUID] = _fk("procurement_purchase_order_line.id")
    goods_receipt_line_id: Mapped[uuid.UUID | None] = _fk("procurement_goods_receipt_line.id", nullable=True)
    quantity: Mapped[Decimal] = _qty()
    unit_price: Mapped[Decimal] = _money()
    line_amount: Mapped[Decimal] = _money()

    __table_args__ = (
        UniqueConstraint("vendor_bill_id", "line_no", name="uq_procurement_vendor_bill_line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0 AND line_amount >= 0", name="amounts_non_negative"),
    )
