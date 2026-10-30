"""ui: recent records (the records each user opened lately; onboarding "Open a product record")

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations import helpers

revision: str = '0007'
down_revision: str | Sequence[str] | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ui_recent_record',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('resource_type', sa.String(length=60), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("resource_type ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'", name=op.f('ck_ui_recent_record_resource_type_format')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_ui_recent_record_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_ui_recent_record_user_id_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ui_recent_record'))
    )
    op.create_index(op.f('ix_ui_recent_record_company_id'), 'ui_recent_record', ['company_id'], unique=False)
    op.create_index('ix_ui_recent_record_user_time', 'ui_recent_record', ['company_id', 'user_id', 'opened_at'], unique=False)
    op.create_index('uq_ui_recent_record_user_resource', 'ui_recent_record', ['company_id', 'user_id', 'resource_type', 'resource_id'], unique=True)
    helpers.enable_tenant_rls('ui_recent_record')


def downgrade() -> None:
    op.drop_index('uq_ui_recent_record_user_resource', table_name='ui_recent_record')
    op.drop_index('ix_ui_recent_record_user_time', table_name='ui_recent_record')
    op.drop_index(op.f('ix_ui_recent_record_company_id'), table_name='ui_recent_record')
    op.drop_table('ui_recent_record')
