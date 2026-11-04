"""Sales order tables (operations.md §2; conventions: ``orders_`` prefix).

- ``orders_sales_order``: ``order_number`` (SO-YYYY-NNNN, yearly), **UNIQUE(company_id, source_quote_id)** so converting
  an accepted quote is idempotent under concurrency and retries; commercial figures are copied from the accepted
  revision snapshot (``snapshot_hash``) and never change afterwards.
- ``orders_sales_order_line``: one per snapshot line (UNIQUE(order_id, source_line_key)); ``qty_remaining`` is a
  generated column ``qty_ordered - qty_cancelled - qty_delivered`` with CHECKs that nothing goes negative and that
  delivered/cancelled never exceed what was ordered. Returns are recorded in ``qty_returned`` (credit disposition: a
  return does not reopen the remaining quantity; replacement needs a new order).
- ``orders_sales_order_status_history`` is append-only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Computed,
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
from app.modules.orders.enums import FulfilmentMode, FulfilmentState, LineKind, OrderAction, OrderStatus

_CURRENCIES = "('INR', 'EUR', 'USD', 'GBP')"


class SalesOrder(TenantEntity, VersionMixin, BranchMixin, Base):
    __tablename__ = "orders_sales_order"

    order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    party_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=False
    )
    party_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_quote_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote.id", ondelete="RESTRICT"), nullable=False
    )
    source_quote_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_quote_revision.id", ondelete="RESTRICT"), nullable=False
    )
    quote_number: Mapped[str] = mapped_column(String(30), nullable=False)
    quote_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", info={"enum": OrderStatus}
    )
    fulfilment_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", info={"enum": FulfilmentState}
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    #: incoterm, payment terms, validity, brand, customer snapshot and the calculation result with rule versions
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    surcharge_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    promised_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: the warehouse reservations and picking use by default (FK to inventory_warehouse)
    default_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=True
    )
    ship_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    hold_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    cancel_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: user | agent | seed
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("company_id", "order_number", name="uq_orders_sales_order_number"),
        #: one order per accepted quote: concurrent and retried conversions converge on this row
        UniqueConstraint("company_id", "source_quote_id", name="uq_orders_sales_order_source_quote"),
        Index("ix_orders_sales_order_status_date", "company_id", "status", "requested_delivery_date"),
        Index("ix_orders_sales_order_party", "company_id", "party_id"),
        Index("ix_orders_sales_order_owner", "company_id", "owner_user_id", "status"),
        Index(
            "ix_orders_sales_order_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        CheckConstraint("order_number ~ '^SO-[0-9]{4}-[0-9]{4,}$'", name="order_number_format"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint("line_count >= 0", name="line_count_non_negative"),
        CheckConstraint("(status <> 'on_hold') OR hold_reason_code IS NOT NULL", name="hold_has_reason"),
        CheckConstraint(
            "(status <> 'cancelled') OR cancel_reason_code IS NOT NULL", name="cancelled_has_reason"
        ),
        CheckConstraint("(status <> 'completed') OR completed_at IS NOT NULL", name="completed_has_date"),
        CheckConstraint(
            "(status = 'draft' OR status = 'cancelled') OR confirmed_at IS NOT NULL",
            name="confirmed_has_date",
        ),
    )


class SalesOrderLine(TenantEntity, VersionMixin, Base):
    __tablename__ = "orders_sales_order_line"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    #: the quote line's stable ``line_key`` (or ``surcharge`` for the materialised charge line)
    source_line_key: Mapped[str] = mapped_column(String(40), nullable=False)
    line_kind: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": LineKind})
    fulfilment_mode: Mapped[str] = mapped_column(String(20), nullable=False, info={"enum": FulfilmentMode})
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    custom_product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sales_custom_product.id", ondelete="RESTRICT"), nullable=True
    )
    product_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    #: what was printed on the accepted revision for this line (decor, size, finish, packaging summary)
    description_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    line_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    qty_delivered: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal(0))
    qty_returned: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal(0))
    qty_cancelled: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal(0))
    qty_remaining: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), Computed("qty_ordered - qty_cancelled - qty_delivered", persisted=True)
    )
    cancel_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_orders_sales_order_line_no"),
        UniqueConstraint("order_id", "source_line_key", name="uq_orders_sales_order_line_source"),
        Index("ix_orders_sales_order_line_product", "company_id", "product_id"),
        ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_orders_sales_order_line_uom",
            ondelete="RESTRICT",
        ),
        CheckConstraint("line_no > 0", name="line_no_positive"),
        CheckConstraint("qty_ordered > 0", name="ordered_positive"),
        CheckConstraint(
            "qty_delivered >= 0 AND qty_returned >= 0 AND qty_cancelled >= 0", name="quantities_non_negative"
        ),
        CheckConstraint("qty_ordered - qty_cancelled - qty_delivered >= 0", name="remaining_non_negative"),
        CheckConstraint("qty_returned <= qty_delivered", name="returned_within_delivered"),
        CheckConstraint(f"currency IN {_CURRENCIES}", name="currency_enabled"),
        CheckConstraint(
            "(line_kind = 'catalog' AND product_id IS NOT NULL) OR line_kind <> 'catalog'",
            name="catalog_has_product",
        ),
        CheckConstraint("fulfilment_mode <> 'stock' OR product_id IS NOT NULL", name="stock_has_product"),
    )


class SalesOrderStatusHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "orders_sales_order_status_history"
    __append_only__ = True

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order.id", ondelete="RESTRICT"), nullable=False
    )
    #: the order line for line-level actions (cancel_line, delivery)
    line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("orders_sales_order_line.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False, info={"enum": OrderAction})
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: the document that caused it (challan number for deliveries), display only
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    order_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_orders_sales_order_status_history_order", "order_id", "occurred_at"),)


__all__ = ["SalesOrder", "SalesOrderLine", "SalesOrderStatusHistory"]
