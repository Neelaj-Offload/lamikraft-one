"""CRM programme module 3: proforma invoices

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-25 00:00:00+00:00

``sales_proforma_invoice``: a PI made from a quotation's issued revision (lines, party block and totals in
``snapshot``), edited while draft, numbered ``PI-YYYY-NNNN`` at issue or entered from history with its original
number. Tenant table with forced RLS. Spec: docs/superpowers/specs/2026-11-25-proforma-invoices-design.md
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "sales_proforma_invoice"


def upgrade() -> None:
    op.create_table(
        T,
        sa.Column("pi_number", sa.String(length=40), nullable=True),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("pi_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("port_of_loading", sa.String(length=120), nullable=True),
        sa.Column("port_of_discharge", sa.String(length=120), nullable=True),
        sa.Column("payment_terms", sa.String(length=500), nullable=True),
        sa.Column("delivery_terms", sa.String(length=200), nullable=True),
        sa.Column("bank_account_label", sa.String(length=80), nullable=True),
        sa.Column("declaration", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("branch_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('draft','issued','cancelled')", name=op.f(f"ck_{T}_status_values")),
        sa.CheckConstraint(
            "(status <> 'draft' OR pi_number IS NULL) AND (status <> 'issued' OR pi_number IS NOT NULL)",
            name=op.f(f"ck_{T}_number_when_issued"),
        ),
        sa.CheckConstraint("status <> 'cancelled' OR cancel_reason IS NOT NULL", name=op.f(f"ck_{T}_cancel_reason_required")),
        sa.CheckConstraint("declaration IS NULL OR char_length(declaration) <= 2000", name=op.f(f"ck_{T}_declaration_length")),
        sa.CheckConstraint("notes IS NULL OR char_length(notes) <= 4000", name=op.f(f"ck_{T}_notes_length")),
        sa.ForeignKeyConstraint(["quote_id"], ["sales_quote.id"], name=op.f(f"fk_{T}_quote_id_sales_quote"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["party_id"], ["parties_party.id"], name=op.f(f"fk_{T}_party_id_parties_party"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["app_user.id"], name=op.f(f"fk_{T}_owner_user_id_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issued_by"], ["app_user.id"], name=op.f(f"fk_{T}_issued_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branch.id"], name=op.f(f"fk_{T}_branch_id_branch"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], name=op.f(f"fk_{T}_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f(f"fk_{T}_created_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_user.id"], name=op.f(f"fk_{T}_updated_by_app_user"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{T}")),
    )
    op.create_index(op.f(f"ix_{T}_company_id"), T, ["company_id"])
    op.create_index(op.f(f"ix_{T}_branch_id"), T, ["branch_id"])
    op.create_index("uq_sales_proforma_invoice_number", T, ["company_id", "pi_number"], unique=True,
                    postgresql_where=sa.text("pi_number IS NOT NULL"))
    op.create_index("ix_sales_proforma_invoice_party", T, ["company_id", "party_id"])
    op.create_index("ix_sales_proforma_invoice_quote", T, ["company_id", "quote_id"])
    helpers.enable_tenant_rls(T)
    helpers.grant_app(T)


def downgrade() -> None:
    op.drop_table(T)
