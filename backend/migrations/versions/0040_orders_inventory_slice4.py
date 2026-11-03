"""orders and inventory (Slice 4, lane s4-orders-inventory): sales orders, warehouses, locations, lots, the stock
ledger, projections, reservations, shortage state, pick lists, counts, adjustments, opening batches, transfers,
reorder rules; challan links to warehouses, orders, order lines and lots

Revision ID: 0040 (placeholder; the Slice-4 integrator renumbers it onto the chain)
Revises: 0018
Create Date: 2026-11-04

- ``inventory_stock_posting`` / ``inventory_stock_movement`` are append-only (trigger + revoked UPDATE/DELETE):
  corrections are reversal postings. UNIQUE(company, source_type, source_id, purpose) gives exactly one posting per
  source event; UNIQUE(company, idempotency_key) and UNIQUE(reverses_posting_id) close the replay paths.
- ``inventory_stock_balance`` key is UNIQUE NULLS NOT DISTINCT (PG >= 15) with CHECK (NOT enforce_non_negative OR
  quantity >= 0); ``inventory_stock_summary`` CHECKs reserved >= 0 and available >= 0: oversell and silent negative
  stock are impossible at the database level.
- ``orders_sales_order`` UNIQUE(company_id, source_quote_id): one order per accepted quote.
- Opening batches and adjustments CHECK approver <> creator (separation of duties in the database).
- Order numbers, warehouse codes and posting sources are immutable (``helpers.immutable_columns``).
- Every tenant table gets forced fail-closed RLS; enumerations are varchar + CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "inventory_stock_posting",
    "inventory_warehouse",
    "inventory_adjustment",
    "inventory_location",
    "inventory_opening_batch",
    "inventory_transfer",
    "inventory_lot",
    "inventory_reorder_rule",
    "inventory_shortage_state",
    "inventory_stock_count",
    "inventory_stock_summary",
    "inventory_adjustment_line",
    "inventory_opening_batch_line",
    "inventory_reservation",
    "inventory_stock_balance",
    "inventory_stock_count_line",
    "inventory_transfer_line",
    "inventory_stock_movement",
    "orders_sales_order",
    "orders_sales_order_line",
    "inventory_pick_list",
    "orders_sales_order_status_history",
    "inventory_pick_list_line",
)
APPEND_ONLY_TABLES = (
    "inventory_stock_movement",
    "inventory_stock_posting",
    "orders_sales_order_status_history",
)
#: (table, column, values) mirroring the StrEnums in app/modules/{inventory,orders}/enums.py (contract-tested)
ENUMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "inventory_stock_posting",
        "source_type",
        (
            "challan",
            "adjustment",
            "stock_count",
            "opening_batch",
            "transfer",
            "relocation",
            "reversal",
            "goods_receipt",
            "work_order",
            "qc_inspection",
        ),
    ),
    (
        "inventory_stock_posting",
        "purpose",
        (
            "issue",
            "return",
            "cancel",
            "adjust",
            "count",
            "opening",
            "dispatch",
            "receive",
            "relocate",
            "reverse",
            "consume",
            "output",
            "write_off",
            "qc",
        ),
    ),
    ("inventory_adjustment", "status", ("draft", "submitted", "posted", "rejected")),
    ("inventory_adjustment", "reason_code", ("damage", "loss", "found", "correction", "scrap", "other")),
    (
        "inventory_location",
        "location_type",
        (
            "internal",
            "qc_hold",
            "rejected",
            "wip",
            "office",
            "in_transit",
            "external_holding",
            "supplier",
            "customer",
            "production",
            "scrap",
            "adjustment",
            "opening",
            "sample_consumption",
        ),
    ),
    ("inventory_opening_batch", "status", ("draft", "submitted", "posted", "rejected")),
    ("inventory_transfer", "status", ("draft", "dispatched", "received", "cancelled")),
    ("inventory_lot", "lot_kind", ("standard", "board_lot", "offcut")),
    ("inventory_lot", "verification_status", ("unverified", "verified")),
    ("inventory_shortage_state", "status", ("open", "resolved")),
    ("inventory_stock_count", "status", ("draft", "frozen", "submitted", "posted", "cancelled")),
    ("inventory_adjustment_line", "direction", ("in", "out")),
    ("inventory_reservation", "status", ("active", "fulfilled", "released", "cancelled")),
    ("inventory_reservation", "demand_type", ("so_line", "wo_material", "transfer_line")),
    ("orders_sales_order", "status", ("draft", "confirmed", "on_hold", "completed", "cancelled")),
    ("orders_sales_order", "fulfilment_state", ("none", "partial", "complete")),
    ("orders_sales_order_line", "line_kind", ("catalog", "custom", "manual", "charge")),
    ("orders_sales_order_line", "fulfilment_mode", ("stock", "make_to_order", "non_stock")),
    ("inventory_pick_list", "status", ("draft", "released", "picked", "cancelled")),
    (
        "orders_sales_order_status_history",
        "action",
        (
            "create",
            "confirm",
            "hold",
            "release_hold",
            "cancel",
            "complete",
            "cancel_line",
            "deliver",
            "return",
            "reverse_delivery",
        ),
    ),
    ("inventory_pick_list_line", "status", ("open", "picked", "short")),
)


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "inventory_stock_posting",
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("source_label", sa.String(length=80), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reverses_posting_id", sa.Uuid(), nullable=True),
        sa.Column("movement_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("movement_count > 0", name=op.f("ck_inventory_stock_posting_has_movements")),
        sa.CheckConstraint(
            "reverses_posting_id IS NULL OR reverses_posting_id <> id",
            name=op.f("ck_inventory_stock_posting_not_self_reversal"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_posting_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_posting_posted_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_stock_posting_reverses_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_posting")),
        sa.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_inventory_stock_posting_idempotency_key"
        ),
        sa.UniqueConstraint(
            "company_id", "source_type", "source_id", "purpose", name="uq_inventory_stock_posting_source"
        ),
        sa.UniqueConstraint("reverses_posting_id", name="uq_inventory_stock_posting_reverses"),
    )
    op.create_index(
        op.f("ix_inventory_stock_posting_company_id"), "inventory_stock_posting", ["company_id"], unique=False
    )
    op.create_index(
        "ix_inventory_stock_posting_posted",
        "inventory_stock_posting",
        ["company_id", "posted_at"],
        unique=False,
    )
    op.create_table(
        "inventory_warehouse",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("origin_ref", sa.String(length=120), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_inventory_warehouse_name_not_blank")),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9-]{0,19}$'", name=op.f("ck_inventory_warehouse_code_format")
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_warehouse_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_warehouse_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_warehouse_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_warehouse_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_warehouse")),
        sa.UniqueConstraint("company_id", "code", name="uq_inventory_warehouse_code"),
    )
    op.create_index(
        op.f("ix_inventory_warehouse_branch_id"), "inventory_warehouse", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_warehouse_company_id"), "inventory_warehouse", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_adjustment",
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status = 'posted') = (posting_id IS NOT NULL)",
            name=op.f("ck_inventory_adjustment_posted_has_posting"),
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> created_by",
            name=op.f("ck_inventory_adjustment_approver_not_creator"),
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_adjustment_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_adjustment_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_adjustment_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_adjustment_decided_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_adjustment_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_adjustment_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_adjustment_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_adjustment")),
        sa.UniqueConstraint("company_id", "number", name="uq_inventory_adjustment_number"),
    )
    op.create_index(
        op.f("ix_inventory_adjustment_branch_id"), "inventory_adjustment", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_adjustment_company_id"), "inventory_adjustment", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_location",
        sa.Column("warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location_type", sa.String(length=30), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("office_branch_id", sa.Uuid(), nullable=True),
        sa.Column("is_stock_bearing", sa.Boolean(), nullable=False),
        sa.Column("counts_available", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(location_type = 'external_holding') = (party_id IS NOT NULL)",
            name=op.f("ck_inventory_location_holding_has_party"),
        ),
        sa.CheckConstraint(
            "(location_type = 'office') = (office_branch_id IS NOT NULL)",
            name=op.f("ck_inventory_location_office_has_branch"),
        ),
        sa.CheckConstraint(
            "(location_type IN ('internal', 'qc_hold', 'rejected', 'wip')) = (warehouse_id IS NOT NULL)",
            name=op.f("ck_inventory_location_warehouse_bound_types"),
        ),
        sa.CheckConstraint(
            "NOT is_default OR location_type = 'internal'",
            name=op.f("ck_inventory_location_default_is_internal"),
        ),
        sa.CheckConstraint(
            "NOT counts_available OR is_stock_bearing",
            name=op.f("ck_inventory_location_available_is_stock_bearing"),
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_inventory_location_parent_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_location_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_location_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_location_office_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_location_parent_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["party_id"],
            ["parties_party.id"],
            name=op.f("fk_inventory_location_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_location_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_location_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_location")),
        sa.UniqueConstraint(
            "company_id",
            "warehouse_id",
            "code",
            name="uq_inventory_location_code",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_inventory_location_company_id"), "inventory_location", ["company_id"], unique=False
    )
    op.create_index(
        "uq_inventory_location_default",
        "inventory_location",
        ["company_id", "warehouse_id"],
        unique=True,
        postgresql_where="is_default",
    )
    op.create_index(
        "uq_inventory_location_party_holding",
        "inventory_location",
        ["company_id", "party_id"],
        unique=True,
        postgresql_where="location_type = 'external_holding'",
    )
    op.create_table(
        "inventory_opening_batch",
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("origin_ref", sa.String(length=120), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status = 'posted') = (posting_id IS NOT NULL)",
            name=op.f("ck_inventory_opening_batch_posted_has_posting"),
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by <> created_by",
            name=op.f("ck_inventory_opening_batch_approver_not_creator"),
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_opening_batch_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_opening_batch_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_opening_batch_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_opening_batch_decided_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_opening_batch_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_opening_batch_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_opening_batch_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_opening_batch")),
        sa.UniqueConstraint("company_id", "number", name="uq_inventory_opening_batch_number"),
    )
    op.create_index(
        op.f("ix_inventory_opening_batch_branch_id"), "inventory_opening_batch", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_opening_batch_company_id"), "inventory_opening_batch", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_transfer",
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("from_warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("to_warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dispatch_posting_id", sa.Uuid(), nullable=True),
        sa.Column("receive_posting_id", sa.Uuid(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status <> 'received' OR receive_posting_id IS NOT NULL",
            name=op.f("ck_inventory_transfer_received_posted"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'cancelled') OR dispatch_posting_id IS NOT NULL",
            name=op.f("ck_inventory_transfer_dispatched_posted"),
        ),
        sa.CheckConstraint(
            "from_warehouse_id <> to_warehouse_id", name=op.f("ck_inventory_transfer_different_warehouses")
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_transfer_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_transfer_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_transfer_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_transfer_dispatch_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_transfer_from_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["receive_posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_transfer_receive_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_transfer_to_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_transfer_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_transfer")),
        sa.UniqueConstraint("company_id", "number", name="uq_inventory_transfer_number"),
    )
    op.create_index(
        op.f("ix_inventory_transfer_branch_id"), "inventory_transfer", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_transfer_company_id"), "inventory_transfer", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_lot",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("lot_code", sa.String(length=60), nullable=False),
        sa.Column("lot_kind", sa.String(length=20), nullable=False),
        sa.Column("supplier_lot_ref", sa.String(length=120), nullable=True),
        sa.Column("parent_lot_id", sa.Uuid(), nullable=True),
        sa.Column("length_mm", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("width_mm", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("thickness_mm", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("grain_axis", sa.String(length=10), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("measured_by", sa.Uuid(), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("btrim(lot_code) <> ''", name=op.f("ck_inventory_lot_lot_code_not_blank")),
        sa.CheckConstraint(
            "grain_axis IS NULL OR grain_axis IN ('length', 'width', 'none')",
            name=op.f("ck_inventory_lot_grain_axis_values"),
        ),
        sa.CheckConstraint(
            "(length_mm IS NULL OR length_mm > 0) AND (width_mm IS NULL OR width_mm > 0) AND (thickness_mm IS NULL OR thickness_mm > 0)",
            name=op.f("ck_inventory_lot_dimensions_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_lot_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_lot_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["measured_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_lot_measured_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_lot_parent_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_lot_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_lot_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_lot")),
        sa.UniqueConstraint("company_id", "product_id", "lot_code", name="uq_inventory_lot_code"),
    )
    op.create_index(op.f("ix_inventory_lot_company_id"), "inventory_lot", ["company_id"], unique=False)
    op.create_table(
        "inventory_reorder_rule",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("min_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("max_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("reorder_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "min_qty >= 0 AND max_qty >= min_qty AND reorder_qty > 0",
            name=op.f("ck_inventory_reorder_rule_levels_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_reorder_rule_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_reorder_rule_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_reorder_rule_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_reorder_rule_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_reorder_rule_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_reorder_rule")),
        sa.UniqueConstraint("company_id", "product_id", "warehouse_id", name="uq_inventory_reorder_rule_key"),
    )
    op.create_index(
        op.f("ix_inventory_reorder_rule_company_id"), "inventory_reorder_rule", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_shortage_state",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("demand_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("free_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("shortfall_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("caused_by", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'open') = (shortfall_qty > 0)",
            name=op.f("ck_inventory_shortage_state_open_when_short"),
        ),
        sa.CheckConstraint(
            "demand_qty >= 0 AND free_qty >= 0 AND shortfall_qty >= 0",
            name=op.f("ck_inventory_shortage_state_quantities_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_shortage_state_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_shortage_state_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_shortage_state_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_shortage_state")),
        sa.UniqueConstraint(
            "company_id", "product_id", "warehouse_id", name="uq_inventory_shortage_state_key"
        ),
    )
    op.create_index(
        op.f("ix_inventory_shortage_state_company_id"),
        "inventory_shortage_state",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "inventory_stock_count",
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_seq", sa.BigInteger(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status <> 'posted' OR approved_by IS NOT NULL",
            name=op.f("ck_inventory_stock_count_posted_is_approved"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'cancelled') OR snapshot_seq IS NOT NULL",
            name=op.f("ck_inventory_stock_count_frozen_has_snapshot"),
        ),
        sa.CheckConstraint(
            "approved_by IS NULL OR submitted_by IS NULL OR approved_by <> submitted_by",
            name=op.f("ck_inventory_stock_count_approver_not_counter"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_approved_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_stock_count_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_count_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_frozen_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_stock_count_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_stock_count_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_submitted_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_stock_count_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_count")),
        sa.UniqueConstraint("company_id", "number", name="uq_inventory_stock_count_number"),
    )
    op.create_index(
        op.f("ix_inventory_stock_count_branch_id"), "inventory_stock_count", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_stock_count_company_id"), "inventory_stock_count", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_stock_summary",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("available_on_hand", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("reserved", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "available_on_hand >= 0", name=op.f("ck_inventory_stock_summary_available_non_negative")
        ),
        sa.CheckConstraint("reserved >= 0", name=op.f("ck_inventory_stock_summary_reserved_non_negative")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_summary_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_stock_summary_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_stock_summary_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_summary")),
        sa.UniqueConstraint(
            "company_id", "product_id", "warehouse_id", name="uq_inventory_stock_summary_key"
        ),
    )
    op.create_index(
        op.f("ix_inventory_stock_summary_company_id"), "inventory_stock_summary", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_adjustment_line",
        sa.Column("adjustment_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(length=5), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_adjustment_line_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["adjustment_id"],
            ["inventory_adjustment.id"],
            name=op.f("fk_inventory_adjustment_line_adjustment_id_inventory_adjustment"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_adjustment_line_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_adjustment_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_adjustment_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_adjustment_line_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_adjustment_line_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_adjustment_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_adjustment_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_adjustment_line")),
        sa.UniqueConstraint("adjustment_id", "line_no", name="uq_inventory_adjustment_line_no"),
    )
    op.create_index(
        op.f("ix_inventory_adjustment_line_company_id"),
        "inventory_adjustment_line",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "inventory_opening_batch_line",
        sa.Column("opening_batch_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("lot_code", sa.String(length=60), nullable=True),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("source_row_ref", sa.String(length=60), nullable=True),
        sa.Column("late_opening", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_opening_batch_line_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_opening_batch_line_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_opening_batch_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_opening_batch_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_opening_batch_line_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_opening_batch_line_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opening_batch_id"],
            ["inventory_opening_batch.id"],
            name=op.f("fk_inventory_opening_batch_line_opening_batch_id_inventory_opening_batch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_opening_batch_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_opening_batch_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_opening_batch_line")),
        sa.UniqueConstraint("opening_batch_id", "line_no", name="uq_inventory_opening_batch_line_no"),
    )
    op.create_index(
        op.f("ix_inventory_opening_batch_line_company_id"),
        "inventory_opening_batch_line",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "inventory_reservation",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("consumed_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("released_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("demand_type", sa.String(length=20), nullable=False),
        sa.Column("demand_id", sa.Uuid(), nullable=False),
        sa.Column("demand_parent_id", sa.Uuid(), nullable=True),
        sa.Column("demand_label", sa.String(length=80), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.Uuid(), nullable=True),
        sa.Column("release_reason_code", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status <> 'active' OR consumed_qty + released_qty < quantity",
            name=op.f("ck_inventory_reservation_active_has_remaining"),
        ),
        sa.CheckConstraint(
            "consumed_qty + released_qty <= quantity", name=op.f("ck_inventory_reservation_within_quantity")
        ),
        sa.CheckConstraint(
            "consumed_qty >= 0 AND released_qty >= 0",
            name=op.f("ck_inventory_reservation_counters_non_negative"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_reservation_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_reservation_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_reservation_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_reservation_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_reservation_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_reservation_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_reservation_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["released_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_reservation_released_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_reservation_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_reservation_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_reservation")),
    )
    op.create_index(
        "ix_inventory_reservation_active",
        "inventory_reservation",
        ["company_id", "product_id", "warehouse_id"],
        unique=False,
        postgresql_where="status = 'active'",
    )
    op.create_index(
        op.f("ix_inventory_reservation_company_id"), "inventory_reservation", ["company_id"], unique=False
    )
    op.create_index(
        "ix_inventory_reservation_demand",
        "inventory_reservation",
        ["company_id", "demand_type", "demand_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_reservation_parent",
        "inventory_reservation",
        ["company_id", "demand_parent_id"],
        unique=False,
    )
    op.create_table(
        "inventory_stock_balance",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("owner_party_id", sa.Uuid(), nullable=True),
        sa.Column("warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("enforce_non_negative", sa.Boolean(), nullable=False),
        sa.Column("last_movement_seq", sa.BigInteger(), nullable=True),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "NOT enforce_non_negative OR quantity >= 0", name=op.f("ck_inventory_stock_balance_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_balance_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_stock_balance_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_stock_balance_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_party_id"],
            ["parties_party.id"],
            name=op.f("fk_inventory_stock_balance_owner_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_stock_balance_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_stock_balance_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_balance")),
        sa.UniqueConstraint(
            "company_id",
            "product_id",
            "location_id",
            "lot_id",
            "owner_party_id",
            name="uq_inventory_stock_balance_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_inventory_stock_balance_company_id"), "inventory_stock_balance", ["company_id"], unique=False
    )
    op.create_index(
        "ix_inventory_stock_balance_warehouse",
        "inventory_stock_balance",
        ["company_id", "warehouse_id", "product_id"],
        unique=False,
    )
    op.create_table(
        "inventory_stock_count_line",
        sa.Column("stock_count_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("system_qty_at_snapshot", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("counted_qty", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "counted_qty IS NULL OR counted_qty >= 0",
            name=op.f("ck_inventory_stock_count_line_counted_non_negative"),
        ),
        sa.CheckConstraint(
            "system_qty_at_snapshot >= 0", name=op.f("ck_inventory_stock_count_line_system_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_stock_count_line_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_count_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_stock_count_line_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_stock_count_line_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_stock_count_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_count_id"],
            ["inventory_stock_count.id"],
            name=op.f("fk_inventory_stock_count_line_stock_count_id_inventory_stock_count"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_stock_count_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_count_line")),
        sa.UniqueConstraint("stock_count_id", "line_no", name="uq_inventory_stock_count_line_no"),
        sa.UniqueConstraint(
            "stock_count_id",
            "product_id",
            "location_id",
            "lot_id",
            name="uq_inventory_stock_count_line_key",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_inventory_stock_count_line_company_id"),
        "inventory_stock_count_line",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "inventory_transfer_line",
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_transfer_line_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_transfer_line_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_transfer_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_transfer_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_transfer_line_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_transfer_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["inventory_transfer.id"],
            name=op.f("fk_inventory_transfer_line_transfer_id_inventory_transfer"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_transfer_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_transfer_line")),
        sa.UniqueConstraint("transfer_id", "line_no", name="uq_inventory_transfer_line_no"),
    )
    op.create_index(
        op.f("ix_inventory_transfer_line_company_id"), "inventory_transfer_line", ["company_id"], unique=False
    )
    op.create_table(
        "inventory_stock_movement",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("owner_party_id", sa.Uuid(), nullable=True),
        sa.Column("from_location_id", sa.Uuid(), nullable=False),
        sa.Column("to_location_id", sa.Uuid(), nullable=False),
        sa.Column("from_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("to_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("entered_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("entered_uom", sa.String(length=16), nullable=False),
        sa.Column("counterparty_party_id", sa.Uuid(), nullable=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("source_line_type", sa.String(length=40), nullable=True),
        sa.Column("source_line_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("entered_qty > 0", name=op.f("ck_inventory_stock_movement_entered_positive")),
        sa.CheckConstraint(
            "from_location_id <> to_location_id", name=op.f("ck_inventory_stock_movement_from_not_to")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_stock_movement_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_stock_movement_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_stock_movement_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_party_id"],
            ["parties_party.id"],
            name=op.f("fk_inventory_stock_movement_counterparty_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_stock_movement_from_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_stock_movement_from_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_stock_movement_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_party_id"],
            ["parties_party.id"],
            name=op.f("fk_inventory_stock_movement_owner_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_stock_movement_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_stock_movement_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["inventory_reservation.id"],
            name=op.f("fk_inventory_stock_movement_reservation_id_inventory_reservation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_stock_movement_to_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_stock_movement_to_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_stock_movement")),
        sa.UniqueConstraint("posting_id", "line_no", name="uq_inventory_stock_movement_line"),
        sa.UniqueConstraint("seq", name="uq_inventory_stock_movement_seq"),
    )
    op.create_index(
        op.f("ix_inventory_stock_movement_company_id"),
        "inventory_stock_movement",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_stock_movement_posting",
        "inventory_stock_movement",
        ["company_id", "posting_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_stock_movement_product_seq",
        "inventory_stock_movement",
        ["company_id", "product_id", "seq"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_stock_movement_source_line",
        "inventory_stock_movement",
        ["company_id", "source_line_id"],
        unique=False,
    )
    op.create_table(
        "orders_sales_order",
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("party_name", sa.String(length=200), nullable=False),
        sa.Column("source_quote_id", sa.Uuid(), nullable=False),
        sa.Column("source_quote_revision_id", sa.Uuid(), nullable=False),
        sa.Column("quote_number", sa.String(length=30), nullable=False),
        sa.Column("quote_revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("fulfilment_state", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("terms_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("surcharge_amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("default_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("ship_to", sa.Text(), nullable=True),
        sa.Column("customer_reference", sa.String(length=120), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("hold_reason_code", sa.String(length=40), nullable=True),
        sa.Column("hold_reason", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancel_reason_code", sa.String(length=40), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status <> 'cancelled') OR cancel_reason_code IS NOT NULL",
            name=op.f("ck_orders_sales_order_cancelled_has_reason"),
        ),
        sa.CheckConstraint(
            "(status <> 'completed') OR completed_at IS NOT NULL",
            name=op.f("ck_orders_sales_order_completed_has_date"),
        ),
        sa.CheckConstraint(
            "(status <> 'on_hold') OR hold_reason_code IS NOT NULL",
            name=op.f("ck_orders_sales_order_hold_has_reason"),
        ),
        sa.CheckConstraint(
            "(status = 'draft' OR status = 'cancelled') OR confirmed_at IS NOT NULL",
            name=op.f("ck_orders_sales_order_confirmed_has_date"),
        ),
        sa.CheckConstraint(
            "currency IN ('INR', 'EUR', 'USD', 'GBP')", name=op.f("ck_orders_sales_order_currency_enabled")
        ),
        sa.CheckConstraint(
            "order_number ~ '^SO-[0-9]{4}-[0-9]{4,}$'", name=op.f("ck_orders_sales_order_order_number_format")
        ),
        sa.CheckConstraint("line_count >= 0", name=op.f("ck_orders_sales_order_line_count_non_negative")),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_orders_sales_order_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_cancelled_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_orders_sales_order_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_confirmed_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["default_warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_orders_sales_order_default_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_owner_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["party_id"],
            ["parties_party.id"],
            name=op.f("fk_orders_sales_order_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_quote_id"],
            ["sales_quote.id"],
            name=op.f("fk_orders_sales_order_source_quote_id_sales_quote"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_quote_revision_id"],
            ["sales_quote_revision.id"],
            name=op.f("fk_orders_sales_order_source_quote_revision_id_sales_quote_revision"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders_sales_order")),
        sa.UniqueConstraint("company_id", "order_number", name="uq_orders_sales_order_number"),
        sa.UniqueConstraint("company_id", "source_quote_id", name="uq_orders_sales_order_source_quote"),
    )
    op.create_index(
        op.f("ix_orders_sales_order_branch_id"), "orders_sales_order", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_orders_sales_order_company_id"), "orders_sales_order", ["company_id"], unique=False
    )
    op.create_index(
        "ix_orders_sales_order_owner",
        "orders_sales_order",
        ["company_id", "owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_orders_sales_order_party", "orders_sales_order", ["company_id", "party_id"], unique=False
    )
    op.create_index(
        "ix_orders_sales_order_search_trgm",
        "orders_sales_order",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_orders_sales_order_status_date",
        "orders_sales_order",
        ["company_id", "status", "requested_delivery_date"],
        unique=False,
    )
    op.create_table(
        "orders_sales_order_line",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("source_line_key", sa.String(length=40), nullable=False),
        sa.Column("line_kind", sa.String(length=20), nullable=False),
        sa.Column("fulfilment_mode", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("custom_product_id", sa.Uuid(), nullable=True),
        sa.Column("product_key", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("description_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("line_total_amount", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("qty_ordered", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("qty_delivered", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("qty_returned", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("qty_cancelled", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column(
            "qty_remaining",
            sa.Numeric(precision=18, scale=6),
            sa.Computed("qty_ordered - qty_cancelled - qty_delivered", persisted=True),
            nullable=False,
        ),
        sa.Column("cancel_reason_code", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(line_kind = 'catalog' AND product_id IS NOT NULL) OR line_kind <> 'catalog'",
            name=op.f("ck_orders_sales_order_line_catalog_has_product"),
        ),
        sa.CheckConstraint(
            "currency IN ('INR', 'EUR', 'USD', 'GBP')",
            name=op.f("ck_orders_sales_order_line_currency_enabled"),
        ),
        sa.CheckConstraint(
            "fulfilment_mode <> 'stock' OR product_id IS NOT NULL",
            name=op.f("ck_orders_sales_order_line_stock_has_product"),
        ),
        sa.CheckConstraint("line_no > 0", name=op.f("ck_orders_sales_order_line_line_no_positive")),
        sa.CheckConstraint(
            "qty_delivered >= 0 AND qty_returned >= 0 AND qty_cancelled >= 0",
            name=op.f("ck_orders_sales_order_line_quantities_non_negative"),
        ),
        sa.CheckConstraint(
            "qty_ordered - qty_cancelled - qty_delivered >= 0",
            name=op.f("ck_orders_sales_order_line_remaining_non_negative"),
        ),
        sa.CheckConstraint("qty_ordered > 0", name=op.f("ck_orders_sales_order_line_ordered_positive")),
        sa.CheckConstraint(
            "qty_returned <= qty_delivered", name=op.f("ck_orders_sales_order_line_returned_within_delivered")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_orders_sales_order_line_uom",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_orders_sales_order_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["custom_product_id"],
            ["sales_custom_product.id"],
            name=op.f("fk_orders_sales_order_line_custom_product_id_sales_custom_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders_sales_order.id"],
            name=op.f("fk_orders_sales_order_line_order_id_orders_sales_order"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_orders_sales_order_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders_sales_order_line")),
        sa.UniqueConstraint("order_id", "line_no", name="uq_orders_sales_order_line_no"),
        sa.UniqueConstraint("order_id", "source_line_key", name="uq_orders_sales_order_line_source"),
    )
    op.create_index(
        op.f("ix_orders_sales_order_line_company_id"), "orders_sales_order_line", ["company_id"], unique=False
    )
    op.create_index(
        "ix_orders_sales_order_line_product",
        "orders_sales_order_line",
        ["company_id", "product_id"],
        unique=False,
    )
    op.create_table(
        "inventory_pick_list",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.Uuid(), nullable=True),
        sa.Column("picked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picked_by", sa.Uuid(), nullable=True),
        sa.Column("challan_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("posting_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("posting_id IS NULL", name=op.f("ck_inventory_pick_list_picking_posts_nothing")),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_assignee_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_inventory_pick_list_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_inventory_pick_list_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_pick_list_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders_sales_order.id"],
            name=op.f("fk_inventory_pick_list_order_id_orders_sales_order"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["picked_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_picked_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posting_id"],
            ["inventory_stock_posting.id"],
            name=op.f("fk_inventory_pick_list_posting_id_inventory_stock_posting"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["released_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_released_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["inventory_warehouse.id"],
            name=op.f("fk_inventory_pick_list_warehouse_id_inventory_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_pick_list")),
        sa.UniqueConstraint("company_id", "number", name="uq_inventory_pick_list_number"),
    )
    op.create_index(
        op.f("ix_inventory_pick_list_branch_id"), "inventory_pick_list", ["branch_id"], unique=False
    )
    op.create_index(
        op.f("ix_inventory_pick_list_company_id"), "inventory_pick_list", ["company_id"], unique=False
    )
    op.create_index(
        "ix_inventory_pick_list_order", "inventory_pick_list", ["company_id", "order_id"], unique=False
    )
    op.create_table(
        "orders_sales_order_status_history",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("line_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.id"],
            name=op.f("fk_orders_sales_order_status_history_actor_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_orders_sales_order_status_history_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["orders_sales_order_line.id"],
            name=op.f("fk_orders_sales_order_status_history_line_id_orders_sales_order_line"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders_sales_order.id"],
            name=op.f("fk_orders_sales_order_status_history_order_id_orders_sales_order"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders_sales_order_status_history")),
    )
    op.create_index(
        op.f("ix_orders_sales_order_status_history_company_id"),
        "orders_sales_order_status_history",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_orders_sales_order_status_history_order",
        "orders_sales_order_status_history",
        ["order_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "inventory_pick_list_line",
        sa.Column("pick_list_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("order_line_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("qty_requested", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("qty_picked", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "qty_picked IS NULL OR (qty_picked >= 0 AND qty_picked <= qty_requested)",
            name=op.f("ck_inventory_pick_list_line_picked_range"),
        ),
        sa.CheckConstraint("qty_requested > 0", name=op.f("ck_inventory_pick_list_line_requested_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_inventory_pick_list_line_uom_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_inventory_pick_list_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["inventory_location.id"],
            name=op.f("fk_inventory_pick_list_line_location_id_inventory_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lot.id"],
            name=op.f("fk_inventory_pick_list_line_lot_id_inventory_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"],
            ["orders_sales_order_line.id"],
            name=op.f("fk_inventory_pick_list_line_order_line_id_orders_sales_order_line"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pick_list_id"],
            ["inventory_pick_list.id"],
            name=op.f("fk_inventory_pick_list_line_pick_list_id_inventory_pick_list"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_inventory_pick_list_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["inventory_reservation.id"],
            name=op.f("fk_inventory_pick_list_line_reservation_id_inventory_reservation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_inventory_pick_list_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_pick_list_line")),
        sa.UniqueConstraint("pick_list_id", "line_no", name="uq_inventory_pick_list_line_no"),
    )
    op.create_index(
        op.f("ix_inventory_pick_list_line_company_id"),
        "inventory_pick_list_line",
        ["company_id"],
        unique=False,
    )
    op.add_column("challans_challan", sa.Column("sales_order_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_challans_challan_destination_warehouse_id_inventory_warehouse"),
        "challans_challan",
        "inventory_warehouse",
        ["destination_warehouse_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_challans_challan_sales_order_id_orders_sales_order"),
        "challans_challan",
        "orders_sales_order",
        ["sales_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_challans_challan_source_warehouse_id_inventory_warehouse"),
        "challans_challan",
        "inventory_warehouse",
        ["source_warehouse_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("challans_challan_line", sa.Column("sales_order_line_id", sa.Uuid(), nullable=True))
    op.add_column("challans_challan_line", sa.Column("lot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_challans_challan_line_sales_order_line_id_orders_sales_order_line"),
        "challans_challan_line",
        "orders_sales_order_line",
        ["sales_order_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_challans_challan_line_lot_id_inventory_lot"),
        "challans_challan_line",
        "inventory_lot",
        ["lot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # ### end Alembic commands ###

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
    for table in APPEND_ONLY_TABLES:
        helpers.append_only(table)
    for table, column, values in ENUMS:
        helpers.enum_check(table, column, values)
    helpers.immutable_columns("orders_sales_order", ["order_number", "company_id", "source_quote_id"])
    helpers.immutable_columns("inventory_warehouse", ["code", "company_id"])
    helpers.immutable_columns("inventory_location", ["warehouse_id", "location_type", "company_id"])


def downgrade() -> None:
    for table in ("orders_sales_order", "inventory_warehouse", "inventory_location"):
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_immutable ON "{table}"')
        op.execute(f"DROP FUNCTION IF EXISTS lk_{table}_immutable()")
    # policies, CHECKs and append-only triggers are dropped with their tables
    op.drop_constraint(
        op.f("fk_challans_challan_line_lot_id_inventory_lot"), "challans_challan_line", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_challans_challan_line_sales_order_line_id_orders_sales_order_line"),
        "challans_challan_line",
        type_="foreignkey",
    )
    op.drop_column("challans_challan_line", "lot_id")
    op.drop_column("challans_challan_line", "sales_order_line_id")
    op.drop_constraint(
        op.f("fk_challans_challan_source_warehouse_id_inventory_warehouse"),
        "challans_challan",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_challans_challan_sales_order_id_orders_sales_order"), "challans_challan", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_challans_challan_destination_warehouse_id_inventory_warehouse"),
        "challans_challan",
        type_="foreignkey",
    )
    op.drop_column("challans_challan", "sales_order_id")
    op.drop_index(op.f("ix_inventory_pick_list_line_company_id"), table_name="inventory_pick_list_line")
    op.drop_table("inventory_pick_list_line")
    op.drop_index(
        "ix_orders_sales_order_status_history_order", table_name="orders_sales_order_status_history"
    )
    op.drop_index(
        op.f("ix_orders_sales_order_status_history_company_id"),
        table_name="orders_sales_order_status_history",
    )
    op.drop_table("orders_sales_order_status_history")
    op.drop_index("ix_inventory_pick_list_order", table_name="inventory_pick_list")
    op.drop_index(op.f("ix_inventory_pick_list_company_id"), table_name="inventory_pick_list")
    op.drop_index(op.f("ix_inventory_pick_list_branch_id"), table_name="inventory_pick_list")
    op.drop_table("inventory_pick_list")
    op.drop_index("ix_orders_sales_order_line_product", table_name="orders_sales_order_line")
    op.drop_index(op.f("ix_orders_sales_order_line_company_id"), table_name="orders_sales_order_line")
    op.drop_table("orders_sales_order_line")
    op.drop_index("ix_orders_sales_order_status_date", table_name="orders_sales_order")
    op.drop_index(
        "ix_orders_sales_order_search_trgm",
        table_name="orders_sales_order",
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.drop_index("ix_orders_sales_order_party", table_name="orders_sales_order")
    op.drop_index("ix_orders_sales_order_owner", table_name="orders_sales_order")
    op.drop_index(op.f("ix_orders_sales_order_company_id"), table_name="orders_sales_order")
    op.drop_index(op.f("ix_orders_sales_order_branch_id"), table_name="orders_sales_order")
    op.drop_table("orders_sales_order")
    op.drop_index("ix_inventory_stock_movement_source_line", table_name="inventory_stock_movement")
    op.drop_index("ix_inventory_stock_movement_product_seq", table_name="inventory_stock_movement")
    op.drop_index("ix_inventory_stock_movement_posting", table_name="inventory_stock_movement")
    op.drop_index(op.f("ix_inventory_stock_movement_company_id"), table_name="inventory_stock_movement")
    op.drop_table("inventory_stock_movement")
    op.drop_index(op.f("ix_inventory_transfer_line_company_id"), table_name="inventory_transfer_line")
    op.drop_table("inventory_transfer_line")
    op.drop_index(op.f("ix_inventory_stock_count_line_company_id"), table_name="inventory_stock_count_line")
    op.drop_table("inventory_stock_count_line")
    op.drop_index("ix_inventory_stock_balance_warehouse", table_name="inventory_stock_balance")
    op.drop_index(op.f("ix_inventory_stock_balance_company_id"), table_name="inventory_stock_balance")
    op.drop_table("inventory_stock_balance")
    op.drop_index("ix_inventory_reservation_parent", table_name="inventory_reservation")
    op.drop_index("ix_inventory_reservation_demand", table_name="inventory_reservation")
    op.drop_index(op.f("ix_inventory_reservation_company_id"), table_name="inventory_reservation")
    op.drop_index(
        "ix_inventory_reservation_active",
        table_name="inventory_reservation",
        postgresql_where="status = 'active'",
    )
    op.drop_table("inventory_reservation")
    op.drop_index(
        op.f("ix_inventory_opening_batch_line_company_id"), table_name="inventory_opening_batch_line"
    )
    op.drop_table("inventory_opening_batch_line")
    op.drop_index(op.f("ix_inventory_adjustment_line_company_id"), table_name="inventory_adjustment_line")
    op.drop_table("inventory_adjustment_line")
    op.drop_index(op.f("ix_inventory_stock_summary_company_id"), table_name="inventory_stock_summary")
    op.drop_table("inventory_stock_summary")
    op.drop_index(op.f("ix_inventory_stock_count_company_id"), table_name="inventory_stock_count")
    op.drop_index(op.f("ix_inventory_stock_count_branch_id"), table_name="inventory_stock_count")
    op.drop_table("inventory_stock_count")
    op.drop_index(op.f("ix_inventory_shortage_state_company_id"), table_name="inventory_shortage_state")
    op.drop_table("inventory_shortage_state")
    op.drop_index(op.f("ix_inventory_reorder_rule_company_id"), table_name="inventory_reorder_rule")
    op.drop_table("inventory_reorder_rule")
    op.drop_index(op.f("ix_inventory_lot_company_id"), table_name="inventory_lot")
    op.drop_table("inventory_lot")
    op.drop_index(op.f("ix_inventory_transfer_company_id"), table_name="inventory_transfer")
    op.drop_index(op.f("ix_inventory_transfer_branch_id"), table_name="inventory_transfer")
    op.drop_table("inventory_transfer")
    op.drop_index(op.f("ix_inventory_opening_batch_company_id"), table_name="inventory_opening_batch")
    op.drop_index(op.f("ix_inventory_opening_batch_branch_id"), table_name="inventory_opening_batch")
    op.drop_table("inventory_opening_batch")
    op.drop_index(
        "uq_inventory_location_party_holding",
        table_name="inventory_location",
        postgresql_where="location_type = 'external_holding'",
    )
    op.drop_index(
        "uq_inventory_location_default", table_name="inventory_location", postgresql_where="is_default"
    )
    op.drop_index(op.f("ix_inventory_location_company_id"), table_name="inventory_location")
    op.drop_table("inventory_location")
    op.drop_index(op.f("ix_inventory_adjustment_company_id"), table_name="inventory_adjustment")
    op.drop_index(op.f("ix_inventory_adjustment_branch_id"), table_name="inventory_adjustment")
    op.drop_table("inventory_adjustment")
    op.drop_index(op.f("ix_inventory_warehouse_company_id"), table_name="inventory_warehouse")
    op.drop_index(op.f("ix_inventory_warehouse_branch_id"), table_name="inventory_warehouse")
    op.drop_table("inventory_warehouse")
    op.drop_index("ix_inventory_stock_posting_posted", table_name="inventory_stock_posting")
    op.drop_index(op.f("ix_inventory_stock_posting_company_id"), table_name="inventory_stock_posting")
    op.drop_table("inventory_stock_posting")
    # ### end Alembic commands ###
