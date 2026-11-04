"""briefings (Slice 3, lane s3-briefings): phrased version texts and the daily WhatsApp summary push

Revision ID: 0021 (lane placeholder 0035, renumbered at the Slice-3 stage-2 merge)
Revises: 0020
Create Date: 2026-11-04

``briefings_version_text`` holds the validated model wording of a version (overview sentence, item recommendation
sentences, narration bodies for "Listen to my day") per language, with its source and ``ai_status``; phrasing never
creates a version. ``briefings_summary_push`` records one daily WhatsApp summary per member and work date (queued
through the channels outbox, or skipped with the audited reason) and whether it was acknowledged on any channel.
Both are tenant tables with forced fail-closed RLS.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = '0021'
down_revision: str | Sequence[str] | None = '0020'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TENANT_TABLES = ("briefings_version_text", "briefings_summary_push")


def upgrade() -> None:
    op.create_table('briefings_summary_push',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('briefing_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.String(length=80), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=True),
    sa.Column('outbox_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('text', sa.String(length=1200), nullable=True),
    sa.Column('simulated', sa.Boolean(), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ack_channel', sa.String(length=20), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome = 'skipped' OR outbox_id IS NOT NULL", name=op.f('ck_briefings_summary_push_queued_has_outbox')),
    sa.CheckConstraint("outcome IN ('queued', 'skipped')", name=op.f('ck_briefings_summary_push_outcome_values')),
    sa.ForeignKeyConstraint(['briefing_id'], ['briefings_briefing.id'], name=op.f('fk_briefings_summary_push_briefing_id_briefings_briefing')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_briefings_summary_push_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_briefings_summary_push_user_id_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_briefings_summary_push'))
    )
    op.create_index('ix_briefings_summary_push_briefing', 'briefings_summary_push', ['company_id', 'briefing_id'], unique=False)
    op.create_index(op.f('ix_briefings_summary_push_company_id'), 'briefings_summary_push', ['company_id'], unique=False)
    op.create_index('uq_briefings_summary_push_user_date', 'briefings_summary_push', ['company_id', 'user_id', 'work_date'], unique=True)
    op.create_table('briefings_version_text',
    sa.Column('briefing_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('language', sa.String(length=12), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('ai_status', sa.String(length=20), nullable=False),
    sa.Column('overview', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('item_texts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('narration', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('batch_id', sa.String(length=120), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("ai_status IN ('demo', 'ok', 'unavailable')", name=op.f('ck_briefings_version_text_ai_status_values')),
    sa.CheckConstraint("status IN ('ready', 'pending')", name=op.f('ck_briefings_version_text_status_values')),
    sa.ForeignKeyConstraint(['briefing_id'], ['briefings_briefing.id'], name=op.f('fk_briefings_version_text_briefing_id_briefings_briefing')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_briefings_version_text_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['version_id'], ['briefings_version.id'], name=op.f('fk_briefings_version_text_version_id_briefings_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_briefings_version_text'))
    )
    op.create_index(op.f('ix_briefings_version_text_company_id'), 'briefings_version_text', ['company_id'], unique=False)
    op.create_index('uq_briefings_version_text', 'briefings_version_text', ['version_id', 'language'], unique=True)

    for table in NEW_TENANT_TABLES:
        helpers.enable_tenant_rls(table)


def downgrade() -> None:
    op.drop_index('uq_briefings_version_text', table_name='briefings_version_text')
    op.drop_index(op.f('ix_briefings_version_text_company_id'), table_name='briefings_version_text')
    op.drop_table('briefings_version_text')
    op.drop_index('uq_briefings_summary_push_user_date', table_name='briefings_summary_push')
    op.drop_index(op.f('ix_briefings_summary_push_company_id'), table_name='briefings_summary_push')
    op.drop_index('ix_briefings_summary_push_briefing', table_name='briefings_summary_push')
    op.drop_table('briefings_summary_push')
