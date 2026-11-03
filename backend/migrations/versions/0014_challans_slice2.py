"""challans: delivery challans as documents (Slice 2): challan, lines, return links, issued revisions, status history

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-03 09:00:00.000000+00:00

- ``challans_challan.challan_number`` (``DC-YYYY-NNNN``) is unique per company and never reused (drafts are soft-deleted);
  the number and the company are immutable (``helpers.immutable_columns``);
- ``(challan_id, line_no)`` is a DEFERRABLE unique constraint (``uq_challans_challan_line_line_no``) so line removal
  renumbers the remaining lines atomically through ``uow.defer_constraints``;
- ``uom_code`` references the company's UOM master (``uom(company_id, code)``);
- ``challans_challan_revision`` and ``challans_challan_status_history`` are append-only (trigger + revoked UPDATE/DELETE);
- ``challans_return_link.return_line_id`` is UNIQUE (one return line records against one original line, once);
- every tenant table gets forced fail-closed RLS; enumerations are varchar + CHECK (``helpers.enum_check``).
Warehouse ids (source / destination) have no foreign key until the inventory module exists (Slice 4).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "challans_challan",
    "challans_challan_line",
    "challans_return_link",
    "challans_challan_revision",
    "challans_challan_status_history",
)
APPEND_ONLY_TABLES = ("challans_challan_revision", "challans_challan_status_history")

#: (table, column, values) mirroring the StrEnums in app/modules/challans/schemas.py (contract-tested)
ENUMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("challans_challan", "challan_type", ("outward", "inward", "return", "job_work", "transfer", "sample")),
    ("challans_challan", "return_type", ("returnable", "non_returnable")),
    (
        "challans_challan",
        "destination_type",
        ("fabricator", "customer", "warehouse", "vendor", "office", "transporter"),
    ),
    ("challans_challan", "status", ("draft", "issued", "closed", "cancelled")),
    ("challans_challan", "inventory_effect", ("none", "posting")),
    ("challans_challan", "origin", ("user", "agent", "seed", "import", "migration", "duplicate")),
    ("challans_challan_line", "line_type", ("catalog", "custom", "manual")),
    ("challans_return_link", "kind", ("returned",)),
    ("challans_challan_revision", "kind", ("issued",)),
    ("challans_challan_status_history", "action", ("issue", "close", "cancel")),
)


def upgrade() -> None:
    op.create_table(
        "challans_challan",
        sa.Column("challan_number", sa.String(length=20), nullable=False),
        sa.Column("challan_date", sa.Date(), nullable=False),
        sa.Column("challan_type", sa.String(length=20), nullable=False),
        sa.Column("return_type", sa.String(length=20), nullable=False),
        sa.Column("source_location", sa.String(length=200), nullable=False),
        sa.Column("source_branch_id", sa.Uuid(), nullable=True),
        sa.Column("source_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("destination_type", sa.String(length=20), nullable=False),
        sa.Column("destination_party", sa.String(length=200), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("consignee_party_id", sa.Uuid(), nullable=True),
        sa.Column("destination_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("office_branch_id", sa.Uuid(), nullable=True),
        sa.Column("shipping_name", sa.String(length=200), nullable=True),
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("reference_no", sa.String(length=120), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("expected_return_date", sa.Date(), nullable=True),
        sa.Column("original_challan_id", sa.Uuid(), nullable=True),
        sa.Column("duplicated_from_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("inventory_effect", sa.String(length=10), nullable=False),
        sa.Column("issue_posting_id", sa.Uuid(), nullable=True),
        sa.Column("reversal_posting_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.Column("close_reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancel_reason_code", sa.String(length=40), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("due_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overdue_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("origin_ref", sa.String(length=120), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "challan_number ~ '^DC-[0-9]{4}-[0-9]{4,}$'",
            name=op.f("ck_challans_challan_challan_number_format"),
        ),
        sa.CheckConstraint(
            "btrim(destination_party) <> ''", name=op.f("ck_challans_challan_destination_party_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(source_location) <> ''", name=op.f("ck_challans_challan_source_location_not_blank")
        ),
        sa.CheckConstraint(
            "gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'",
            name=op.f("ck_challans_challan_gstin_format"),
        ),
        sa.CheckConstraint("line_count >= 0", name=op.f("ck_challans_challan_line_count_non_negative")),
        sa.CheckConstraint("revision_no >= 0", name=op.f("ck_challans_challan_revision_no_non_negative")),
        sa.CheckConstraint(
            "challan_type <> 'job_work' OR return_type = 'returnable'",
            name=op.f("ck_challans_challan_job_work_returnable"),
        ),
        sa.CheckConstraint(
            "expected_return_date IS NULL OR expected_return_date >= challan_date",
            name=op.f("ck_challans_challan_expected_return_after_date"),
        ),
        sa.CheckConstraint(
            "original_challan_id IS NULL OR challan_type = 'return'",
            name=op.f("ck_challans_challan_original_only_on_return"),
        ),
        sa.CheckConstraint(
            "original_challan_id IS NULL OR original_challan_id <> id",
            name=op.f("ck_challans_challan_original_not_self"),
        ),
        sa.CheckConstraint(
            "inventory_effect = 'none' OR issue_posting_id IS NOT NULL OR status = 'draft'",
            name=op.f("ck_challans_challan_posting_when_effect"),
        ),
        sa.CheckConstraint(
            "(status <> 'issued' AND status <> 'closed') OR issued_at IS NOT NULL",
            name=op.f("ck_challans_challan_issued_has_date"),
        ),
        sa.CheckConstraint(
            "(status <> 'closed') OR closed_at IS NOT NULL", name=op.f("ck_challans_challan_closed_has_date")
        ),
        sa.CheckConstraint(
            "(status <> 'cancelled') OR cancel_reason_code IS NOT NULL",
            name=op.f("ck_challans_challan_cancelled_has_reason"),
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL) OR (status = 'draft')", name=op.f("ck_challans_challan_deleted_draft_only")
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branch.id"],
            name=op.f("fk_challans_challan_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_cancelled_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_closed_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_challans_challan_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["consignee_party_id"],
            ["parties_party.id"],
            name=op.f("fk_challans_challan_consignee_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_deleted_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["duplicated_from_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_challan_duplicated_from_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_issued_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["office_branch_id"],
            ["branch.id"],
            name=op.f("fk_challans_challan_office_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_challan_original_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_owner_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["party_id"],
            ["parties_party.id"],
            name=op.f("fk_challans_challan_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_branch_id"],
            ["branch.id"],
            name=op.f("fk_challans_challan_source_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challans_challan")),
        sa.UniqueConstraint("company_id", "challan_number", name="uq_challans_challan_number"),
    )
    op.create_index(op.f("ix_challans_challan_branch_id"), "challans_challan", ["branch_id"], unique=False)
    op.create_index(op.f("ix_challans_challan_company_id"), "challans_challan", ["company_id"], unique=False)
    op.create_index(
        "ix_challans_challan_owner",
        "challans_challan",
        ["company_id", "owner_user_id", "status"],
        unique=False,
    )
    op.create_index("ix_challans_challan_party", "challans_challan", ["company_id", "party_id"], unique=False)
    op.create_index(
        "ix_challans_challan_search_trgm",
        "challans_challan",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_challans_challan_status_date",
        "challans_challan",
        ["company_id", "status", "challan_date"],
        unique=False,
    )
    op.create_index(
        "ix_challans_challan_type", "challans_challan", ["company_id", "challan_type"], unique=False
    )
    op.create_table(
        "challans_challan_line",
        sa.Column("challan_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("line_type", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("custom_product_id", sa.Uuid(), nullable=True),
        sa.Column("item_code", sa.String(length=120), nullable=True),
        sa.Column("item_name", sa.String(length=500), nullable=False),
        sa.Column("hsn_sac", sa.String(length=8), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=16), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("original_line_id", sa.Uuid(), nullable=True),
        sa.Column("returned_qty", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("is_non_stock", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("line_no > 0", name=op.f("ck_challans_challan_line_line_no_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_challans_challan_line_quantity_positive")),
        sa.CheckConstraint(
            "returned_qty >= 0 AND returned_qty <= quantity",
            name=op.f("ck_challans_challan_line_returned_within_quantity"),
        ),
        sa.CheckConstraint(
            "btrim(item_name) <> ''", name=op.f("ck_challans_challan_line_item_name_not_blank")
        ),
        sa.CheckConstraint(
            "hsn_sac IS NULL OR hsn_sac ~ '^[0-9]{4,8}$'",
            name=op.f("ck_challans_challan_line_hsn_sac_format"),
        ),
        sa.CheckConstraint(
            "(line_type = 'catalog' AND product_id IS NOT NULL AND custom_product_id IS NULL) OR (line_type = 'custom' AND product_id IS NULL) OR (line_type = 'manual' AND product_id IS NULL AND custom_product_id IS NULL)",
            name=op.f("ck_challans_challan_line_line_type_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_challan_line_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uom_code"],
            ["uom.company_id", "uom.code"],
            name="fk_challans_challan_line_uom",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_challans_challan_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_line_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_line_id"],
            ["challans_challan_line.id"],
            name=op.f("fk_challans_challan_line_original_line_id_challans_challan_line"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_challans_challan_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_line_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challans_challan_line")),
        sa.UniqueConstraint(
            "challan_id",
            "line_no",
            name="uq_challans_challan_line_line_no",
            deferrable=True,
            initially="IMMEDIATE",
        ),
    )
    op.create_index(
        "ix_challans_challan_line_challan", "challans_challan_line", ["challan_id", "line_no"], unique=False
    )
    op.create_index(
        op.f("ix_challans_challan_line_company_id"), "challans_challan_line", ["company_id"], unique=False
    )
    op.create_index(
        "ix_challans_challan_line_product",
        "challans_challan_line",
        ["company_id", "product_id"],
        unique=False,
    )
    op.create_table(
        "challans_return_link",
        sa.Column("return_challan_id", sa.Uuid(), nullable=False),
        sa.Column("return_line_id", sa.Uuid(), nullable=False),
        sa.Column("original_challan_id", sa.Uuid(), nullable=False),
        sa.Column("original_line_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_challans_return_link_quantity_positive")),
        sa.CheckConstraint(
            "return_challan_id <> original_challan_id", name=op.f("ck_challans_return_link_not_self")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_challans_return_link_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_challans_return_link_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_return_link_original_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_line_id"],
            ["challans_challan_line.id"],
            name=op.f("fk_challans_return_link_original_line_id_challans_challan_line"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["return_challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_return_link_return_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["return_line_id"],
            ["challans_challan_line.id"],
            name=op.f("fk_challans_return_link_return_line_id_challans_challan_line"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challans_return_link")),
        sa.UniqueConstraint("return_line_id", name="uq_challans_return_link_return_line"),
    )
    op.create_index(
        op.f("ix_challans_return_link_company_id"), "challans_return_link", ["company_id"], unique=False
    )
    op.create_index(
        "ix_challans_return_link_original",
        "challans_return_link",
        ["original_challan_id", "original_line_id"],
        unique=False,
    )
    op.create_index(
        "ix_challans_return_link_return", "challans_return_link", ["return_challan_id"], unique=False
    )
    op.create_table(
        "challans_challan_revision",
        sa.Column("challan_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("revision_no > 0", name=op.f("ck_challans_challan_revision_revision_no_positive")),
        sa.ForeignKeyConstraint(
            ["challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_challan_revision_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_challans_challan_revision_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_revision_issued_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challans_challan_revision")),
        sa.UniqueConstraint("challan_id", "revision_no", name="uq_challans_challan_revision_no"),
    )
    op.create_index(
        op.f("ix_challans_challan_revision_company_id"),
        "challans_challan_revision",
        ["company_id"],
        unique=False,
    )
    op.create_table(
        "challans_challan_status_history",
        sa.Column("challan_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("challan_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.id"],
            name=op.f("fk_challans_challan_status_history_actor_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["challan_id"],
            ["challans_challan.id"],
            name=op.f("fk_challans_challan_status_history_challan_id_challans_challan"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_challans_challan_status_history_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challans_challan_status_history")),
    )
    op.create_index(
        "ix_challans_challan_status_history_challan",
        "challans_challan_status_history",
        ["challan_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_challans_challan_status_history_company_id"),
        "challans_challan_status_history",
        ["company_id"],
        unique=False,
    )

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
    for table in APPEND_ONLY_TABLES:
        helpers.append_only(table)
    for table, column, values in ENUMS:
        helpers.enum_check(table, column, values)
    helpers.immutable_columns("challans_challan", ["challan_number", "company_id"])


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_challans_challan_immutable ON "challans_challan"')
    op.execute("DROP FUNCTION IF EXISTS lk_challans_challan_immutable()")
    # policies, CHECKs and append-only triggers are dropped with their tables
    op.drop_index(
        op.f("ix_challans_challan_status_history_company_id"), table_name="challans_challan_status_history"
    )
    op.drop_index("ix_challans_challan_status_history_challan", table_name="challans_challan_status_history")
    op.drop_table("challans_challan_status_history")
    op.drop_index(op.f("ix_challans_challan_revision_company_id"), table_name="challans_challan_revision")
    op.drop_table("challans_challan_revision")
    op.drop_index("ix_challans_return_link_return", table_name="challans_return_link")
    op.drop_index("ix_challans_return_link_original", table_name="challans_return_link")
    op.drop_index(op.f("ix_challans_return_link_company_id"), table_name="challans_return_link")
    op.drop_table("challans_return_link")
    op.drop_index("ix_challans_challan_line_product", table_name="challans_challan_line")
    op.drop_index(op.f("ix_challans_challan_line_company_id"), table_name="challans_challan_line")
    op.drop_index("ix_challans_challan_line_challan", table_name="challans_challan_line")
    op.drop_table("challans_challan_line")
    op.drop_index("ix_challans_challan_type", table_name="challans_challan")
    op.drop_index("ix_challans_challan_status_date", table_name="challans_challan")
    op.drop_index("ix_challans_challan_search_trgm", table_name="challans_challan")
    op.drop_index("ix_challans_challan_party", table_name="challans_challan")
    op.drop_index("ix_challans_challan_owner", table_name="challans_challan")
    op.drop_index(op.f("ix_challans_challan_company_id"), table_name="challans_challan")
    op.drop_index(op.f("ix_challans_challan_branch_id"), table_name="challans_challan")
    op.drop_table("challans_challan")
