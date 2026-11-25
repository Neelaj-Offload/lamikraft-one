"""CRM programme module 1: the lead pipeline

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-25 00:00:00+00:00

- ``parties_party`` gains the lead columns: website, lead source, interests, requirement, first contact date, pipeline
  stage (+ lost reason), priority, temperature and the denormalised next follow-up date. All nullable: vendors keep
  NULL. Backfill: every party with the customer role gets a stage (prospect → ``new``, otherwise ``won``), priority
  ``B``, temperature ``cold`` and its creation date (IST) as first contact.
- ``parties_lead_source``: the per-company managed list of lead sources (copy of ``parties_customer_type``); five
  built-in sources for every existing company. ``parties_party.lead_source_code`` is a composite FK to it.
- ``parties_activity``: the append-only activity log (call, email, WhatsApp, meeting, visit, note) with an optional
  next follow-up date.

Spec: docs/superpowers/specs/2026-11-25-leads-module-design.md
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEAD_STAGES = ("new", "contacted", "qualified", "negotiating", "won", "lost")
INTERESTS = ("lamikraft", "table_top", "standard_decorative", "standard_compact")
ACTIVITY_KINDS = ("call", "email", "whatsapp", "meeting", "visit", "note")
SYSTEM_LEAD_SOURCES = (
    ("website", "Website", 10),
    ("visiting_card", "Visiting card", 20),
    ("trade_show", "Trade show", 30),
    ("referral", "Referral", 40),
    ("other", "Other", 90),
)


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _tenant_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _tenant_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], name=op.f(f"fk_{table}_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f(f"fk_{table}_created_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_user.id"], name=op.f(f"fk_{table}_updated_by_app_user"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    # ---- lead sources ------------------------------------------------------------------------------------------
    op.create_table(
        "parties_lead_source",
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        *_tenant_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("btrim(label) <> ''", name=op.f("ck_parties_lead_source_label_not_blank")),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,19}$'", name=op.f("ck_parties_lead_source_code_format")),
        *_tenant_constraints("parties_lead_source"),
        sa.UniqueConstraint("company_id", "code", name="uq_parties_lead_source_code"),
    )
    op.create_index(op.f("ix_parties_lead_source_company_id"), "parties_lead_source", ["company_id"])

    # ---- activity log ------------------------------------------------------------------------------------------
    op.create_table(
        "parties_activity",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_follow_up_on", sa.Date(), nullable=True),
        *_tenant_columns(),
        sa.CheckConstraint("char_length(notes) <= 4000", name=op.f("ck_parties_activity_notes_length")),
        sa.CheckConstraint(
            "outcome IS NOT NULL OR notes IS NOT NULL", name=op.f("ck_parties_activity_has_content")
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], ["parties_party.id"], name=op.f("fk_parties_activity_party_id_parties_party"), ondelete="RESTRICT"
        ),
        *_tenant_constraints("parties_activity"),
    )
    op.create_index(op.f("ix_parties_activity_company_id"), "parties_activity", ["company_id"])
    op.create_index(
        "ix_parties_activity_party_time", "parties_activity", ["company_id", "party_id", sa.text("occurred_at DESC")]
    )

    for table in ("parties_lead_source", "parties_activity"):
        helpers.enable_tenant_rls(table)
        helpers.grant_app(table)
    helpers.enum_check("parties_activity", "kind", ACTIVITY_KINDS)
    helpers.append_only("parties_activity")

    # ---- lead columns on the party -----------------------------------------------------------------------------
    op.add_column("parties_party", sa.Column("website", sa.String(length=200), nullable=True))
    op.add_column("parties_party", sa.Column("lead_source_code", sa.String(length=20), nullable=True))
    op.add_column("parties_party", sa.Column("interests", postgresql.ARRAY(sa.String(length=30)), nullable=True))
    op.add_column("parties_party", sa.Column("requirement", sa.Text(), nullable=True))
    op.add_column("parties_party", sa.Column("first_contact_on", sa.Date(), nullable=True))
    op.add_column("parties_party", sa.Column("lead_stage", sa.String(length=20), nullable=True))
    op.add_column("parties_party", sa.Column("lost_reason", sa.String(length=500), nullable=True))
    op.add_column("parties_party", sa.Column("priority", sa.CHAR(length=1), nullable=True))
    op.add_column("parties_party", sa.Column("temperature", sa.String(length=10), nullable=True))
    op.add_column("parties_party", sa.Column("next_follow_up_on", sa.Date(), nullable=True))
    op.add_column("parties_party", sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "lead_stage_values", "parties_party", f"lead_stage IS NULL OR lead_stage IN ({_quoted(LEAD_STAGES)})"
    )
    op.create_check_constraint(
        "lost_reason_when_lost",
        "parties_party",
        "(lead_stage IS NOT DISTINCT FROM 'lost') = (lost_reason IS NOT NULL)",
    )
    op.create_check_constraint("priority_values", "parties_party", "priority IS NULL OR priority IN ('A', 'B', 'C')")
    op.create_check_constraint(
        "temperature_values", "parties_party", "temperature IS NULL OR temperature IN ('hot', 'warm', 'cold')"
    )
    op.create_check_constraint(
        "interests_values",
        "parties_party",
        f"interests IS NULL OR interests <@ ARRAY[{_quoted(INTERESTS)}]::varchar[]",
    )
    op.create_check_constraint(
        "requirement_length", "parties_party", "requirement IS NULL OR char_length(requirement) <= 2000"
    )
    op.create_foreign_key(
        "fk_parties_party_lead_source",
        "parties_party",
        "parties_lead_source",
        ["company_id", "lead_source_code"],
        ["company_id", "code"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_parties_party_lead_stage", "parties_party", ["company_id", "lead_stage"])
    op.create_index("ix_parties_party_lead_source", "parties_party", ["company_id", "lead_source_code"])
    op.create_index(
        "ix_parties_party_follow_up", "parties_party", ["company_id", "owner_user_id", "next_follow_up_on"]
    )

    # ---- backfill (RLS is forced: write each company's rows under its own app.company_id) ----------------------
    values = ", ".join(f"('{code}', '{label}', {order})" for code, label, order in SYSTEM_LEAD_SOURCES)
    op.execute(
        f"""
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN SELECT id FROM company LOOP
                PERFORM set_config('app.company_id', c.id::text, true);
                INSERT INTO parties_lead_source
                    (id, company_id, code, label, display_order, is_active, is_system, version, created_at, updated_at)
                SELECT gen_random_uuid(), c.id, v.code, v.label, v.ord, true, true, 1, now(), now()
                FROM (VALUES {values}) AS v(code, label, ord)
                ON CONFLICT (company_id, code) DO NOTHING;
                UPDATE parties_party
                   SET lead_stage = CASE WHEN status = 'prospect' THEN 'new' ELSE 'won' END,
                       priority = 'B',
                       temperature = 'cold',
                       first_contact_on = (created_at AT TIME ZONE 'Asia/Kolkata')::date
                 WHERE company_id = c.id AND 'customer' = ANY(roles);
            END LOOP;
            PERFORM set_config('app.company_id', '', true);
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_parties_party_follow_up", table_name="parties_party")
    op.drop_index("ix_parties_party_lead_source", table_name="parties_party")
    op.drop_index("ix_parties_party_lead_stage", table_name="parties_party")
    op.drop_constraint("fk_parties_party_lead_source", "parties_party", type_="foreignkey")
    for name in (
        "requirement_length", "interests_values", "temperature_values", "priority_values", "lost_reason_when_lost",
        "lead_stage_values",
    ):
        op.drop_constraint(op.f(f"ck_parties_party_{name}"), "parties_party", type_="check")
    for column in (
        "stage_changed_at", "next_follow_up_on", "temperature", "priority", "lost_reason", "lead_stage", "first_contact_on", "requirement",
        "interests", "lead_source_code", "website",
    ):
        op.drop_column("parties_party", column)
    op.drop_table("parties_activity")
    op.drop_table("parties_lead_source")
