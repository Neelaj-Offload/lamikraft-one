"""migration (Slice 5, lane s5-migration): runs, quarantine issues, rerunnable ID maps, candidate party links, the
legacy document archive, opening-balance batches and backup records

Revision ID: 0050
Revises: 0018
Create Date: 2026-11-04 01:00:00+00:00

Placeholder number (0050+, completion program): the integrator renumbers it into the linear chain.

- ``migration_id_map`` is the rerunnable mapping ``UNIQUE(company_id, source_entity, source_key)``;
- ``migration_legacy_record.payload`` / ``payload_sha256`` are immutable (``helpers.immutable_columns``): an issued
  legacy document is kept exactly as exported and never rewritten;
- ``migration_party_candidate`` is unique per (company, normalised name, country) and is decided by a person;
- ``migration_backup`` holds one row per company for each ``lk backup create`` (the dump covers the whole database);
- every table is a tenant table with forced fail-closed RLS; enumerations are varchar + CHECK (``helpers.enum_check``)
  mirroring the StrEnums in ``app/modules/migration/models.py`` (contract-tested).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0050"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "migration_run",
    "migration_issue",
    "migration_id_map",
    "migration_party_candidate",
    "migration_legacy_record",
    "migration_opening_batch",
    "migration_opening_line",
    "migration_backup",
)

#: (table, column, values) mirroring the StrEnums in app/modules/migration/models.py (contract-tested)
ENUMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("migration_run", "kind", ("dry_run", "apply")),
    ("migration_run", "status", ("running", "completed", "failed")),
    ("migration_issue", "severity", ("error", "quarantine", "warning", "info")),
    ("migration_id_map", "status", ("planned", "quarantined", "rejected", "applied")),
    ("migration_party_candidate", "status", ("proposed", "linked", "new_party", "rejected")),
    ("migration_opening_batch", "status", ("staged", "approved", "posted", "rejected")),
    ("migration_opening_line", "status", ("valid", "quarantined")),
    ("migration_backup", "status", ("completed", "failed")),
    ("migration_backup", "rehearsal_outcome", ("passed", "failed")),
)


def upgrade() -> None:
    op.create_table(
        "migration_backup",
        sa.Column("backup_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("database", sa.String(length=80), nullable=False),
        sa.Column("alembic_revision", sa.String(length=40), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dump_bytes", sa.BigInteger(), nullable=True),
        sa.Column("dump_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_files", sa.Integer(), nullable=True),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_sha256", sa.String(length=64), nullable=True),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("table_count", sa.Integer(), nullable=True),
        sa.Column("row_total", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("rehearsal_outcome", sa.String(length=20), nullable=True),
        sa.Column("rehearsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rehearsal_checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rehearsal_seconds", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_backup_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_backup")),
        sa.UniqueConstraint("company_id", "backup_id", name="uq_migration_backup_backup_id"),
    )
    op.create_index(op.f("ix_migration_backup_company_id"), "migration_backup", ["company_id"], unique=False)
    op.create_index(
        "ix_migration_backup_company_started", "migration_backup", ["company_id", "started_at"], unique=False
    )
    op.create_table(
        "migration_run",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_label", sa.String(length=200), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("export_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("backup_id", sa.String(length=40), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by_name", sa.String(length=200), nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_run_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_migration_run_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_migration_run_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_run")),
    )
    op.create_index(op.f("ix_migration_run_company_id"), "migration_run", ["company_id"], unique=False)
    op.create_index(
        "ix_migration_run_company_started", "migration_run", ["company_id", "started_at"], unique=False
    )
    op.create_table(
        "migration_id_map",
        sa.Column("source_entity", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=400), nullable=False),
        sa.Column("business_key", sa.String(length=400), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("target_table", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("first_run_id", sa.Uuid(), nullable=False),
        sa.Column("last_run_id", sa.Uuid(), nullable=False),
        sa.Column("applied_run_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["applied_run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_id_map_applied_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_id_map_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["first_run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_id_map_first_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_id_map_last_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_id_map")),
        sa.UniqueConstraint("company_id", "source_entity", "source_key", name="uq_migration_id_map_source"),
    )
    op.create_index(
        "ix_migration_id_map_business",
        "migration_id_map",
        ["company_id", "source_entity", "business_key"],
        unique=False,
    )
    op.create_index(op.f("ix_migration_id_map_company_id"), "migration_id_map", ["company_id"], unique=False)
    op.create_table(
        "migration_issue",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("source_file", sa.String(length=200), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.String(length=400), nullable=True),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=True),
        sa.Column("raw_value", sa.String(length=500), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_issue_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_issue_run_id_migration_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_issue")),
    )
    op.create_index(op.f("ix_migration_issue_company_id"), "migration_issue", ["company_id"], unique=False)
    op.create_index(
        "ix_migration_issue_run", "migration_issue", ["run_id", "severity", "entity"], unique=False
    )
    op.create_index("ix_migration_issue_run_code", "migration_issue", ["run_id", "code"], unique=False)
    op.create_table(
        "migration_opening_batch",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_count", sa.Integer(), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posting_ref", sa.String(length=120), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["app_user.id"],
            name=op.f("fk_migration_opening_batch_approved_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_opening_batch_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_migration_opening_batch_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_opening_batch_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_migration_opening_batch_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_opening_batch")),
    )
    op.create_index(
        "ix_migration_opening_batch_company",
        "migration_opening_batch",
        ["company_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_opening_batch_company_id"), "migration_opening_batch", ["company_id"], unique=False
    )
    op.create_table(
        "migration_party_candidate",
        sa.Column("name_key", sa.String(length=200), nullable=False),
        sa.Column("country_key", sa.String(length=80), nullable=False),
        sa.Column("legacy_name", sa.String(length=200), nullable=False),
        sa.Column("legacy_country", sa.String(length=80), nullable=True),
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("suggested_party_id", sa.Uuid(), nullable=True),
        sa.Column("match_kind", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("linked_party_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column("last_run_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_party_candidate_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_migration_party_candidate_created_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["app_user.id"],
            name=op.f("fk_migration_party_candidate_decided_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_party_candidate_last_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_party_id"],
            ["parties_party.id"],
            name=op.f("fk_migration_party_candidate_linked_party_id_parties_party"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["suggested_party_id"],
            ["parties_party.id"],
            name=op.f("fk_migration_party_candidate_suggested_party_id_parties_party"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_migration_party_candidate_updated_by_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_party_candidate")),
        sa.UniqueConstraint("company_id", "name_key", "country_key", name="uq_migration_party_candidate_key"),
    )
    op.create_index(
        op.f("ix_migration_party_candidate_company_id"),
        "migration_party_candidate",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_migration_party_candidate_status",
        "migration_party_candidate",
        ["company_id", "status"],
        unique=False,
    )
    op.create_table(
        "migration_legacy_record",
        sa.Column("source_entity", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=400), nullable=False),
        sa.Column("document_number", sa.String(length=80), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("legacy_total", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("recomputed_total", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("has_discrepancy", sa.Boolean(), nullable=False),
        sa.Column("party_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("applied_run_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["applied_run_id"],
            ["migration_run.id"],
            name=op.f("fk_migration_legacy_record_applied_run_id_migration_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_legacy_record_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["party_candidate_id"],
            ["migration_party_candidate.id"],
            name=op.f("fk_migration_legacy_record_party_candidate_id_migration_party_candidate"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_legacy_record")),
        sa.UniqueConstraint(
            "company_id", "source_entity", "source_key", name="uq_migration_legacy_record_source"
        ),
    )
    op.create_index(
        op.f("ix_migration_legacy_record_company_id"), "migration_legacy_record", ["company_id"], unique=False
    )
    op.create_index(
        "ix_migration_legacy_record_number",
        "migration_legacy_record",
        ["company_id", "source_entity", "document_number"],
        unique=False,
    )
    op.create_table(
        "migration_opening_line",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("product_key", sa.String(length=200), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("location_code", sa.String(length=80), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("uom_code", sa.String(length=20), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issue_code", sa.String(length=60), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["migration_opening_batch.id"],
            name=op.f("fk_migration_opening_line_batch_id_migration_opening_batch"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["company.id"],
            name=op.f("fk_migration_opening_line_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["catalogue_product.id"],
            name=op.f("fk_migration_opening_line_product_id_catalogue_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_migration_opening_line")),
    )
    op.create_index(
        "ix_migration_opening_line_batch", "migration_opening_line", ["batch_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_migration_opening_line_company_id"), "migration_opening_line", ["company_id"], unique=False
    )

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
    for table, column, values in ENUMS:
        helpers.enum_check(table, column, values)
    helpers.immutable_columns(
        "migration_legacy_record", ["payload", "payload_sha256", "company_id", "source_entity", "source_key"]
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_migration_legacy_record_immutable ON "migration_legacy_record"')
    op.execute("DROP FUNCTION IF EXISTS lk_migration_legacy_record_immutable()")
    # policies and CHECKs are dropped with their tables
    op.drop_index(op.f("ix_migration_opening_line_company_id"), table_name="migration_opening_line")
    op.drop_index("ix_migration_opening_line_batch", table_name="migration_opening_line")
    op.drop_table("migration_opening_line")
    op.drop_index("ix_migration_legacy_record_number", table_name="migration_legacy_record")
    op.drop_index(op.f("ix_migration_legacy_record_company_id"), table_name="migration_legacy_record")
    op.drop_table("migration_legacy_record")
    op.drop_index("ix_migration_party_candidate_status", table_name="migration_party_candidate")
    op.drop_index(op.f("ix_migration_party_candidate_company_id"), table_name="migration_party_candidate")
    op.drop_table("migration_party_candidate")
    op.drop_index(op.f("ix_migration_opening_batch_company_id"), table_name="migration_opening_batch")
    op.drop_index("ix_migration_opening_batch_company", table_name="migration_opening_batch")
    op.drop_table("migration_opening_batch")
    op.drop_index("ix_migration_issue_run_code", table_name="migration_issue")
    op.drop_index("ix_migration_issue_run", table_name="migration_issue")
    op.drop_index(op.f("ix_migration_issue_company_id"), table_name="migration_issue")
    op.drop_table("migration_issue")
    op.drop_index(op.f("ix_migration_id_map_company_id"), table_name="migration_id_map")
    op.drop_index("ix_migration_id_map_business", table_name="migration_id_map")
    op.drop_table("migration_id_map")
    op.drop_index("ix_migration_run_company_started", table_name="migration_run")
    op.drop_index(op.f("ix_migration_run_company_id"), table_name="migration_run")
    op.drop_table("migration_run")
    op.drop_index("ix_migration_backup_company_started", table_name="migration_backup")
    op.drop_index(op.f("ix_migration_backup_company_id"), table_name="migration_backup")
    op.drop_table("migration_backup")
