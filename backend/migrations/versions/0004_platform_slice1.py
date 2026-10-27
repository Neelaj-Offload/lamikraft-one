"""platform slice 1: settings, currency, UOM master, files, notes, recent searches, integration status

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 08:02:00+00:00

All DDL of the Slice-1 wave-1 platform lane (org settings and reference data, files, collab notes,
search, integration status, audit keyset index). The integrator chains the lane migrations at merge.
RLS, append-only triggers and CHECKs come from ``migrations/helpers.py`` and the model constraints.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "setting",
    "setting_revision",
    "uom",
    "uom_alias",
    "uom_conversion",
    "file_object",
    "note",
    "search_recent",
    "integration_status",
)

#: global reference rows (conventions §6: enabled currencies INR, EUR, USD, GBP, exponent 2)
CURRENCIES = (
    {"code": "INR", "name": "Indian rupee", "symbol": "₹", "exponent": 2, "enabled": True, "sort_order": 1},
    {"code": "EUR", "name": "Euro", "symbol": "€", "exponent": 2, "enabled": True, "sort_order": 2},
    {"code": "USD", "name": "US dollar", "symbol": "$", "exponent": 2, "enabled": True, "sort_order": 3},
    {"code": "GBP", "name": "Pound sterling", "symbol": "£", "exponent": 2, "enabled": True, "sort_order": 4},
)


def upgrade() -> None:
    op.create_table('currency',
    sa.Column('code', sa.CHAR(length=3), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('symbol', sa.String(length=8), nullable=False),
    sa.Column('exponent', sa.SmallInteger(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), nullable=False),
    sa.CheckConstraint("code ~ '^[A-Z]{3}$'", name=op.f('ck_currency_code_format')),
    sa.CheckConstraint('exponent BETWEEN 0 AND 4', name=op.f('ck_currency_exponent_range')),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_currency'))
    )
    op.create_table('file_object',
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('content_type', sa.String(length=120), nullable=False),
    sa.Column('declared_content_type', sa.String(length=120), nullable=True),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('storage_backend', sa.String(length=20), nullable=False),
    sa.Column('storage_key', sa.String(length=200), nullable=False),
    sa.Column('restricted', sa.Boolean(), nullable=False),
    sa.Column('claims', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("jsonb_typeof(claims) = 'array'", name=op.f('ck_file_object_claims_array')),
    sa.CheckConstraint("kind IN ('png','jpeg','gif','webp','pdf','xlsx','csv','txt')", name=op.f('ck_file_object_kind_values')),
    sa.CheckConstraint("purpose IN ('image','document','import','export')", name=op.f('ck_file_object_purpose_values')),
    sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f('ck_file_object_sha256_format')),
    sa.CheckConstraint("storage_backend IN ('local_fs','s3')", name=op.f('ck_file_object_storage_backend_values')),
    sa.CheckConstraint('size_bytes >= 0', name=op.f('ck_file_object_size_non_negative')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_file_object_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_file_object_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_file_object_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_file_object'))
    )
    op.create_index(op.f('ix_file_object_company_id'), 'file_object', ['company_id'], unique=False)
    op.create_index('ix_file_object_creator', 'file_object', ['company_id', 'created_by', 'created_at'], unique=False)
    op.create_index('uq_file_object_company_sha256', 'file_object', ['company_id', 'sha256'], unique=True)
    op.create_index('uq_file_object_storage_key', 'file_object', ['storage_key'], unique=True)
    op.create_table('integration_status',
    sa.Column('integration_key', sa.String(length=40), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_code', sa.String(length=60), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("mode IN ('demo','live')", name=op.f('ck_integration_status_mode_values')),
    sa.CheckConstraint("state <> 'connected' OR verified_at IS NOT NULL", name=op.f('ck_integration_status_connected_requires_verification')),
    sa.CheckConstraint("state IN ('not_connected','connected','error')", name=op.f('ck_integration_status_state_values')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_integration_status_company_id_company'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_status'))
    )
    op.create_index(op.f('ix_integration_status_company_id'), 'integration_status', ['company_id'], unique=False)
    op.create_index('uq_integration_status_key', 'integration_status', ['company_id', 'integration_key'], unique=True)
    op.create_table('note',
    sa.Column('resource_type', sa.String(length=80), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('char_length(body) <= 20000', name=op.f('ck_note_body_length')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_note_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_note_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_note_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_note'))
    )
    op.create_index(op.f('ix_note_company_id'), 'note', ['company_id'], unique=False)
    op.create_index('uq_note_resource', 'note', ['company_id', 'resource_type', 'resource_id'], unique=True)
    op.create_table('search_recent',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('query', sa.String(length=200), nullable=False),
    sa.Column('normalized_query', sa.String(length=200), nullable=False),
    sa.Column('searched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_search_recent_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_search_recent_user_id_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_search_recent'))
    )
    op.create_index(op.f('ix_search_recent_company_id'), 'search_recent', ['company_id'], unique=False)
    op.create_index('ix_search_recent_user_time', 'search_recent', ['company_id', 'user_id', 'searched_at'], unique=False)
    op.create_index('uq_search_recent_user_query', 'search_recent', ['company_id', 'user_id', 'normalized_query'], unique=True)
    op.create_table('uom',
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('dimension', sa.String(length=10), nullable=False),
    sa.Column('is_integer', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,15}$'", name=op.f('ck_uom_code_format')),
    sa.CheckConstraint("dimension IN ('count','pack','mass','length','area')", name=op.f('ck_uom_dimension_values')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_uom_company_id_company'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_uom')),
    sa.UniqueConstraint('company_id', 'code', name='uq_uom_company_id_code')
    )
    op.create_index(op.f('ix_uom_company_id'), 'uom', ['company_id'], unique=False)
    op.create_table('setting',
    sa.Column('branch_id', sa.Uuid(), nullable=True),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('schema_version', sa.SmallInteger(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,63}$'", name=op.f('ck_setting_key_format')),
    sa.ForeignKeyConstraint(['branch_id'], ['branch.id'], name=op.f('fk_setting_branch_id_branch'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_setting_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_setting_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_setting_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_setting'))
    )
    op.create_index(op.f('ix_setting_company_id'), 'setting', ['company_id'], unique=False)
    op.create_index('uq_setting_scope_key', 'setting', ['company_id', 'branch_id', 'key'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('uom_alias',
    sa.Column('alias', sa.String(length=40), nullable=False),
    sa.Column('uom_code', sa.String(length=16), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id', 'uom_code'], ['uom.company_id', 'uom.code'], name='fk_uom_alias_uom', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_uom_alias_company_id_company'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_uom_alias'))
    )
    op.create_index(op.f('ix_uom_alias_company_id'), 'uom_alias', ['company_id'], unique=False)
    op.create_index('uq_uom_alias_company_alias', 'uom_alias', ['company_id', 'alias'], unique=True)
    op.create_table('uom_conversion',
    sa.Column('from_code', sa.String(length=16), nullable=False),
    sa.Column('to_code', sa.String(length=16), nullable=False),
    sa.Column('factor', sa.Numeric(precision=20, scale=10), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=True),
    sa.Column('provenance', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("provenance IN ('standard','product_packaging','manual','import')", name=op.f('ck_uom_conversion_provenance_values')),
    sa.CheckConstraint('factor > 0', name=op.f('ck_uom_conversion_factor_positive')),
    sa.CheckConstraint('from_code <> to_code', name=op.f('ck_uom_conversion_distinct_units')),
    sa.ForeignKeyConstraint(['company_id', 'from_code'], ['uom.company_id', 'uom.code'], name='fk_uom_conversion_from_uom', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id', 'to_code'], ['uom.company_id', 'uom.code'], name='fk_uom_conversion_to_uom', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_uom_conversion_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_uom_conversion_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_uom_conversion_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_uom_conversion'))
    )
    op.create_index(op.f('ix_uom_conversion_company_id'), 'uom_conversion', ['company_id'], unique=False)
    # one conversion per unordered unit pair and product: (a, b) and (b, a) can never both exist
    op.create_index('uq_uom_conversion_pair', 'uom_conversion', ['company_id', sa.text('LEAST(from_code, to_code)'), sa.text('GREATEST(from_code, to_code)'), 'product_id'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('setting_revision',
    sa.Column('setting_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('branch_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('schema_version', sa.SmallInteger(), nullable=False),
    sa.Column('changed_by', sa.Uuid(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('change_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['changed_by'], ['app_user.id'], name=op.f('fk_setting_revision_changed_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_setting_revision_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['setting_id'], ['setting.id'], name=op.f('fk_setting_revision_setting_id_setting'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_setting_revision'))
    )
    op.create_index(op.f('ix_setting_revision_company_id'), 'setting_revision', ['company_id'], unique=False)
    op.create_index('ix_setting_revision_key', 'setting_revision', ['company_id', 'key', 'changed_at'], unique=False)
    op.create_index('uq_setting_revision_version', 'setting_revision', ['setting_id', 'version'], unique=True)

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
    helpers.append_only("setting_revision")

    currency = sa.table(
        "currency",
        sa.column("code", sa.CHAR(3)),
        sa.column("name", sa.String),
        sa.column("symbol", sa.String),
        sa.column("exponent", sa.SmallInteger),
        sa.column("enabled", sa.Boolean),
        sa.column("sort_order", sa.SmallInteger),
    )
    op.bulk_insert(currency, list(CURRENCIES))
    # the currency reference is global and read-only for the runtime role
    op.execute('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON "currency" FROM lk_app')

    # keyset pagination of the audit read API: (company_id, occurred_at DESC, id DESC)
    op.create_index("ix_audit_log_keyset", "audit_log", ["company_id", "occurred_at", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_keyset", table_name="audit_log")
    op.drop_index('uq_setting_revision_version', table_name='setting_revision')
    op.drop_index('ix_setting_revision_key', table_name='setting_revision')
    op.drop_index(op.f('ix_setting_revision_company_id'), table_name='setting_revision')
    op.drop_table('setting_revision')
    op.drop_index('uq_uom_conversion_pair', table_name='uom_conversion', postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_uom_conversion_company_id'), table_name='uom_conversion')
    op.drop_table('uom_conversion')
    op.drop_index('uq_uom_alias_company_alias', table_name='uom_alias')
    op.drop_index(op.f('ix_uom_alias_company_id'), table_name='uom_alias')
    op.drop_table('uom_alias')
    op.drop_index('uq_setting_scope_key', table_name='setting', postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_setting_company_id'), table_name='setting')
    op.drop_table('setting')
    op.drop_index(op.f('ix_uom_company_id'), table_name='uom')
    op.drop_table('uom')
    op.drop_index('uq_search_recent_user_query', table_name='search_recent')
    op.drop_index('ix_search_recent_user_time', table_name='search_recent')
    op.drop_index(op.f('ix_search_recent_company_id'), table_name='search_recent')
    op.drop_table('search_recent')
    op.drop_index('uq_note_resource', table_name='note')
    op.drop_index(op.f('ix_note_company_id'), table_name='note')
    op.drop_table('note')
    op.drop_index('uq_integration_status_key', table_name='integration_status')
    op.drop_index(op.f('ix_integration_status_company_id'), table_name='integration_status')
    op.drop_table('integration_status')
    op.drop_index('uq_file_object_storage_key', table_name='file_object')
    op.drop_index('uq_file_object_company_sha256', table_name='file_object')
    op.drop_index('ix_file_object_creator', table_name='file_object')
    op.drop_index(op.f('ix_file_object_company_id'), table_name='file_object')
    op.drop_table('file_object')
    op.drop_table('currency')
