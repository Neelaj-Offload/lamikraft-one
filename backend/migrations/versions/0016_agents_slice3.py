"""agents (Slice 3, lane agents-runtime): trace correlation, token budgets, quota degradation, receipts, phrasing cache

Revision ID: 0016 (lane placeholder 0020, renumbered at the Slice-3 stage-1 merge)
Revises: 0015
Create Date: 2026-11-03 09:00:00.000000+00:00

Adds ``correlation_id`` to turns, run steps and the AI call log (the run already had it), the input-token budget
and degradation reason on runs, the quota owner on call-log rows, the ``agents_receipt`` table (draft undo, design
section 9) and ``agents_phrasing_cache`` (fact-hash cache, ai-routing.md section 7). New tenant tables get forced
fail-closed RLS. Reparented onto the Slice-2 chain (after ``0015_slice2_cross_lane_links``) by the integrator.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = '0016'
down_revision: str | Sequence[str] | None = '0015'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TENANT_TABLES = ("agents_receipt", "agents_phrasing_cache")


def upgrade() -> None:
    op.add_column('agents_turn', sa.Column('correlation_id', sa.String(length=64), nullable=True))
    op.add_column('agents_run', sa.Column('input_token_budget', sa.Integer(), nullable=False, server_default='120000'))
    op.add_column('agents_run', sa.Column('input_tokens_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('agents_run', sa.Column('degraded_reason', sa.String(length=40), nullable=True))
    op.create_index('ix_agents_run_correlation', 'agents_run', ['correlation_id'], unique=False)
    op.add_column('agents_run_step', sa.Column('correlation_id', sa.String(length=64), nullable=True))
    op.add_column('agents_ai_call_log', sa.Column('user_id', sa.Uuid(), nullable=True))
    op.add_column('agents_ai_call_log', sa.Column('correlation_id', sa.String(length=64), nullable=True))
    op.create_index('ix_agents_ai_call_log_user_day', 'agents_ai_call_log', ['company_id', 'user_id', 'created_at'], unique=False)

    op.create_table('agents_receipt',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('step_seq', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=80), nullable=False),
    sa.Column('summary', sa.String(length=300), nullable=False),
    sa.Column('resource_type', sa.String(length=80), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('resource_version', sa.Integer(), nullable=True),
    sa.Column('undo_kind', sa.String(length=20), nullable=False),
    sa.Column('undo_spec', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('undo_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("status IN ('active','undone','expired','target_changed')", name=op.f('ck_agents_receipt_status_values')),
    sa.CheckConstraint("undo_kind IN ('revert_draft','restore_line','none')", name=op.f('ck_agents_receipt_undo_kind_values')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_agents_receipt_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_agents_receipt_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['run_id'], ['agents_run.id'], name=op.f('fk_agents_receipt_run_id_agents_run'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_agents_receipt_updated_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_agents_receipt_user_id_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents_receipt'))
    )
    op.create_index(op.f('ix_agents_receipt_company_id'), 'agents_receipt', ['company_id'], unique=False)
    op.create_index('ix_agents_receipt_run', 'agents_receipt', ['run_id', 'step_seq'], unique=False)
    op.create_index('ix_agents_receipt_target', 'agents_receipt', ['company_id', 'resource_type', 'resource_id'], unique=False)

    op.create_table('agents_phrasing_cache',
    sa.Column('fact_hash', sa.String(length=64), nullable=False),
    sa.Column('template_code', sa.String(length=80), nullable=False),
    sa.Column('language', sa.String(length=12), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("source IN ('model','template')", name=op.f('ck_agents_phrasing_cache_source_values')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_agents_phrasing_cache_company_id_company'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents_phrasing_cache'))
    )
    op.create_index(op.f('ix_agents_phrasing_cache_company_id'), 'agents_phrasing_cache', ['company_id'], unique=False)
    op.create_index('uq_agents_phrasing_cache_hash', 'agents_phrasing_cache', ['company_id', 'fact_hash'], unique=True)

    for table in NEW_TENANT_TABLES:
        helpers.enable_tenant_rls(table)


def downgrade() -> None:
    op.drop_index('uq_agents_phrasing_cache_hash', table_name='agents_phrasing_cache')
    op.drop_index(op.f('ix_agents_phrasing_cache_company_id'), table_name='agents_phrasing_cache')
    op.drop_table('agents_phrasing_cache')
    op.drop_index('ix_agents_receipt_target', table_name='agents_receipt')
    op.drop_index('ix_agents_receipt_run', table_name='agents_receipt')
    op.drop_index(op.f('ix_agents_receipt_company_id'), table_name='agents_receipt')
    op.drop_table('agents_receipt')
    op.drop_index('ix_agents_ai_call_log_user_day', table_name='agents_ai_call_log')
    op.drop_column('agents_ai_call_log', 'correlation_id')
    op.drop_column('agents_ai_call_log', 'user_id')
    op.drop_column('agents_run_step', 'correlation_id')
    op.drop_index('ix_agents_run_correlation', table_name='agents_run')
    op.drop_column('agents_run', 'degraded_reason')
    op.drop_column('agents_run', 'input_tokens_used')
    op.drop_column('agents_run', 'input_token_budget')
    op.drop_column('agents_turn', 'correlation_id')
