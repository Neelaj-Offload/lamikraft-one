"""Marketplace channels, listings (channel SKU -> product) and imported orders (module 5).

Spec: docs/superpowers/specs/2026-11-25-marketplace-sync-design.md. Credentials never live here: live adapters read
them from the environment (``LK_AMAZON_*``).
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TenantEntity, VersionMixin

CHANNEL_KINDS = ("amazon", "flipkart", "pepperfry", "website")
ORDER_STATUSES = ("posted", "needs_attention", "cancelled")


class MarketplaceChannel(TenantEntity, VersionMixin, Base):
    __tablename__ = "marketplaces_channel"

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="demo")
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_warehouse.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_marketplaces_channel_code"),
        CheckConstraint("kind IN ('amazon','flipkart','pepperfry','website')", name="kind_values"),
        CheckConstraint("mode IN ('demo','live')", name="mode_values"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,29}$'", name="code_format"),
    )


class MarketplaceListing(TenantEntity, VersionMixin, Base):
    __tablename__ = "marketplaces_listing"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("marketplaces_channel.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=False
    )
    channel_sku: Mapped[str] = mapped_column(String(80), nullable=False)
    #: ASIN, Flipkart listing id or website product id
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: Amazon listings need the product type for the quantity patch
    product_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    push_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_pushed_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_push_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("company_id", "channel_id", "channel_sku", name="uq_marketplaces_listing_sku"),
        Index("ix_marketplaces_listing_product", "company_id", "product_id"),
    )


class MarketplaceOrder(TenantEntity, Base):
    __tablename__ = "marketplaces_order"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("marketplaces_channel.id", ondelete="RESTRICT"), nullable=False
    )
    external_order_id: Mapped[str] = mapped_column(String(80), nullable=False)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    #: [{"sku", "quantity", "product_id" | null, "title"}]
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    attention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_stock_posting.id", ondelete="RESTRICT"), nullable=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("company_id", "channel_id", "external_order_id", name="uq_marketplaces_order_external"),
        Index("ix_marketplaces_order_channel_time", "company_id", "channel_id", "ordered_at"),
        CheckConstraint("status IN ('posted','needs_attention','cancelled')", name="status_values"),
        CheckConstraint("(status = 'posted') = (posting_id IS NOT NULL)", name="posting_when_posted"),
    )
