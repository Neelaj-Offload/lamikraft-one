"""CRM programme module 5: marketplace channels, listings and orders

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-25 00:00:00+00:00

``marketplaces_channel`` (Amazon India, Flipkart, Pepperfry, Website; Demo or Live), ``marketplaces_listing``
(channel SKU -> product), ``marketplaces_order`` (each external order once, with the stock posting it made). The
stock posting source list gains ``marketplace_order``. Tenant tables with forced RLS.
Spec: docs/superpowers/specs/2026-11-25-marketplace-sync-design.md
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES = ("challan", "adjustment", "stock_count", "opening_batch", "transfer", "relocation", "reversal", "goods_receipt",
           "work_order", "qc_inspection")


def _tenant(table: str) -> list:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], name=op.f(f"fk_{table}_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f(f"fk_{table}_created_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_user.id"], name=op.f(f"fk_{table}_updated_by_app_user"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "marketplaces_channel",
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_tenant("marketplaces_channel"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["inventory_warehouse.id"],
                                name=op.f("fk_marketplaces_channel_warehouse_id_inventory_warehouse"), ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", "code", name="uq_marketplaces_channel_code"),
        sa.CheckConstraint("kind IN ('amazon','flipkart','pepperfry','website')", name=op.f("ck_marketplaces_channel_kind_values")),
        sa.CheckConstraint("mode IN ('demo','live')", name=op.f("ck_marketplaces_channel_mode_values")),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,29}$'", name=op.f("ck_marketplaces_channel_code_format")),
    )
    op.create_table(
        "marketplaces_listing",
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("channel_sku", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=True),
        sa.Column("product_type", sa.String(80), nullable=True),
        sa.Column("push_stock", sa.Boolean(), nullable=False),
        sa.Column("last_pushed_qty", sa.Numeric(18, 6), nullable=True),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_push_error", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_tenant("marketplaces_listing"),
        sa.ForeignKeyConstraint(["channel_id"], ["marketplaces_channel.id"],
                                name=op.f("fk_marketplaces_listing_channel_id_marketplaces_channel"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["catalogue_product.id"],
                                name=op.f("fk_marketplaces_listing_product_id_catalogue_product"), ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", "channel_id", "channel_sku", name="uq_marketplaces_listing_sku"),
    )
    op.create_index("ix_marketplaces_listing_product", "marketplaces_listing", ["company_id", "product_id"])
    op.create_table(
        "marketplaces_order",
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("external_order_id", sa.String(80), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attention_reason", sa.Text(), nullable=True),
        sa.Column("posting_id", sa.Uuid(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        *_tenant("marketplaces_order"),
        sa.ForeignKeyConstraint(["channel_id"], ["marketplaces_channel.id"],
                                name=op.f("fk_marketplaces_order_channel_id_marketplaces_channel"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posting_id"], ["inventory_stock_posting.id"],
                                name=op.f("fk_marketplaces_order_posting_id_inventory_stock_posting"), ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", "channel_id", "external_order_id", name="uq_marketplaces_order_external"),
        sa.CheckConstraint("status IN ('posted','needs_attention','cancelled')", name=op.f("ck_marketplaces_order_status_values")),
        sa.CheckConstraint("(status = 'posted') = (posting_id IS NOT NULL)", name=op.f("ck_marketplaces_order_posting_when_posted")),
    )
    op.create_index("ix_marketplaces_order_channel_time", "marketplaces_order", ["company_id", "channel_id", "ordered_at"])
    for table in ("marketplaces_channel", "marketplaces_listing", "marketplaces_order"):
        op.create_index(op.f(f"ix_{table}_company_id"), table, ["company_id"])
        helpers.enable_tenant_rls(table)
        helpers.grant_app(table)
    op.drop_constraint(op.f("ck_inventory_stock_posting_source_type_values"), "inventory_stock_posting", type_="check")
    helpers.enum_check("inventory_stock_posting", "source_type", (*SOURCES, "marketplace_order"))


def downgrade() -> None:
    op.drop_constraint(op.f("ck_inventory_stock_posting_source_type_values"), "inventory_stock_posting", type_="check")
    helpers.enum_check("inventory_stock_posting", "source_type", SOURCES)
    for table in ("marketplaces_order", "marketplaces_listing", "marketplaces_channel"):
        op.drop_table(table)
