"""catalogue, parties, pricing and commercial (Slice 1 wave 1, lane catalogue)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23 08:42:25.795407+00:00

All DDL of the lane in one revision (the integrator chains lane revisions at merge):
- catalogue: taxonomy, product master, specification, packaging, parsed dimensions, lookup_reference;
- parties: party, contacts, addresses, tax identifiers;
- pricing: price lists, items (no overlapping validity), append-only item history, append-only product cost;
- commercial: versioned rule sets (one active version per code).

Every tenant table gets forced fail-closed RLS; enumerations are varchar + CHECK (``helpers.enum_check``).
Unit codes are validated strings with a CHECK on the documented UOM list until ``org.uom`` exists; the
integrator replaces each ``ck_*_uom`` CHECK with an FK to ``uom.code`` at merge.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "catalogue_category",
    "catalogue_subcategory",
    "catalogue_product",
    "catalogue_product_specification",
    "catalogue_product_packaging",
    "catalogue_product_dimension",
    "catalogue_lookup_reference",
    "parties_party",
    "parties_party_contact",
    "parties_party_address",
    "parties_party_tax_identifier",
    "pricing_price_list",
    "pricing_price_list_item",
    "pricing_price_list_item_history",
    "pricing_product_cost",
    "commercial_rule_set",
)
APPEND_ONLY_TABLES = ("pricing_price_list_item_history", "pricing_product_cost")

#: documented UOM codes (docs/architecture/conventions.md section 6); replaced by an FK to uom.code at merge
UOM_CODES = (
    "pcs", "nos", "sheets", "kg", "g", "m", "mm", "cm", "sqm", "sqft", "box", "set", "roll", "bundle", "carton",
)
UOM_COLUMNS = (
    ("catalogue_product", "unit_of_sale"),
    ("catalogue_product", "stock_uom_code"),
    ("pricing_price_list", "default_unit_code"),
    ("pricing_price_list_item", "unit_code"),
    ("pricing_price_list_item", "moq_unit_code"),
    ("pricing_product_cost", "unit_code"),
)

#: (table, column, values) for varchar enumerations; the values mirror the StrEnums in each module's schemas
#: (the contract test tests/contract/catalogue/test_lane_schema.py compares them)
ENUMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("catalogue_category", "origin", ("seed", "ui", "import", "migration", "migration_inferred")),
    ("catalogue_subcategory", "origin", ("seed", "ui", "import", "migration", "migration_inferred")),
    ("catalogue_product", "status", ("active", "inactive", "under_development")),
    ("catalogue_product", "origin", ("ui", "import", "migration", "promotion", "seed")),
    ("catalogue_product", "size_basis", ("master_size", "spec_size", "spec_length_width")),
    (
        "catalogue_product_dimension",
        "kind",
        (
            "master_size", "spec_size", "board_size", "working_size", "stand_size", "plate_1_size", "plate_2_size",
            "plate_3_size",
        ),
    ),
    ("catalogue_product_dimension", "parse_status", ("parsed", "ambiguous", "unparsed")),
    ("parties_party", "customer_type", ("standard", "dealer", "distributor")),
    ("parties_party", "status", ("prospect", "active", "inactive", "blocked")),
    ("parties_party_address", "kind", ("billing", "shipping")),
    ("parties_party_tax_identifier", "scheme", ("gstin", "vat", "eori", "pan", "iec", "other")),
    ("pricing_price_list", "price_type", ("domestic", "export", "sample", "distributor")),
    ("pricing_price_list", "scope_kind", ("standard", "customer_type", "customer")),
    ("pricing_price_list", "customer_type", ("standard", "dealer", "distributor")),
    ("pricing_price_list", "status", ("draft", "active", "retired")),
    ("pricing_price_list", "source_kind", ("manual", "import", "migration", "seed")),
    ("pricing_price_list_item", "status", ("active", "retired")),
    ("pricing_price_list_item", "source_kind", ("manual", "import", "migration", "seed")),
    (
        "pricing_price_list_item_history",
        "change_kind",
        ("created", "edited_draft", "superseded", "retired", "list_activated", "list_retired"),
    ),
    ("pricing_product_cost", "source_kind", ("manual", "import", "migration", "rollup", "seed")),
    ("commercial_rule_set", "status", ("draft", "active", "retired")),
)

#: commercial.md §2.2 / ADR-018: once the parent list is active (or retired), an item's price columns are immutable;
#: only shortening valid_to, retiring the item or setting superseded_by_item_id once is allowed (draft lists are free)
PRICE_ITEM_GUARD = """
CREATE OR REPLACE FUNCTION lk_pricing_price_list_item_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    list_status text;
    free_columns text[] := ARRAY['valid_to', 'status', 'superseded_by_item_id', 'version', 'updated_at', 'updated_by'];
BEGIN
    SELECT status INTO list_status FROM pricing_price_list WHERE id = OLD.price_list_id;
    IF list_status IS DISTINCT FROM 'draft' THEN
        IF (to_jsonb(NEW) - free_columns) IS DISTINCT FROM (to_jsonb(OLD) - free_columns) THEN
            RAISE EXCEPTION 'pricing_price_list_item: prices of an active or retired list are immutable; supersede instead'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.valid_to IS DISTINCT FROM OLD.valid_to
           AND (NEW.valid_to IS NULL OR (OLD.valid_to IS NOT NULL AND NEW.valid_to > OLD.valid_to)) THEN
            RAISE EXCEPTION 'pricing_price_list_item: valid_to of an active price may only be shortened'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'active' AND NEW.status = 'retired') THEN
            RAISE EXCEPTION 'pricing_price_list_item: an active price may only be retired'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.superseded_by_item_id IS DISTINCT FROM OLD.superseded_by_item_id
           AND OLD.superseded_by_item_id IS NOT NULL THEN
            RAISE EXCEPTION 'pricing_price_list_item: superseded_by_item_id is set once'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
"""

PRODUCT_KEY_GUARD = """
CREATE OR REPLACE FUNCTION lk_catalogue_product_key_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.product_key IS DISTINCT FROM OLD.product_key THEN
        RAISE EXCEPTION 'catalogue_product.product_key is immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
"""


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('catalogue_category',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('name_key', sa.String(length=120), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_catalog_page_start', sa.String(length=40), nullable=True),
    sa.Column('source_catalog_page_end', sa.String(length=40), nullable=True),
    sa.Column('legacy_product_count', sa.Integer(), nullable=True),
    sa.Column('origin', sa.String(length=30), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_catalogue_category_name_not_blank')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_category_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_catalogue_category_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_catalogue_category_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_catalogue_category')),
    sa.UniqueConstraint('company_id', 'name_key', name='uq_catalogue_category_name_key')
    )
    op.create_index(op.f('ix_catalogue_category_company_id'), 'catalogue_category', ['company_id'], unique=False)
    op.create_table('catalogue_lookup_reference',
    sa.Column('lookup_type', sa.String(length=80), nullable=False),
    sa.Column('key_1', sa.String(length=200), nullable=False),
    sa.Column('key_2', sa.String(length=200), server_default='', nullable=False),
    sa.Column('value_1', sa.Text(), nullable=True),
    sa.Column('value_2', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source_extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_lookup_reference_company_id_company'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_catalogue_lookup_reference')),
    sa.UniqueConstraint('company_id', 'lookup_type', 'key_1', 'key_2', name='uq_catalogue_lookup_reference_key')
    )
    op.create_index(op.f('ix_catalogue_lookup_reference_company_id'), 'catalogue_lookup_reference', ['company_id'], unique=False)
    op.create_table('commercial_rule_set',
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('engine_version', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_by', sa.Uuid(), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('version_no > 0', name=op.f('ck_commercial_rule_set_version_no_positive')),
    sa.ForeignKeyConstraint(['activated_by'], ['app_user.id'], name=op.f('fk_commercial_rule_set_activated_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_commercial_rule_set_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_commercial_rule_set_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_commercial_rule_set_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_commercial_rule_set')),
    sa.UniqueConstraint('company_id', 'code', 'version_no', name='uq_commercial_rule_set_version')
    )
    op.create_index(op.f('ix_commercial_rule_set_company_id'), 'commercial_rule_set', ['company_id'], unique=False)
    op.create_index('uq_commercial_rule_set_one_active', 'commercial_rule_set', ['company_id', 'code'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table('catalogue_subcategory',
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('name_key', sa.String(length=120), nullable=False),
    sa.Column('display_order', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('source_catalog_page_start', sa.String(length=40), nullable=True),
    sa.Column('source_catalog_page_end', sa.String(length=40), nullable=True),
    sa.Column('legacy_product_count', sa.Integer(), nullable=True),
    sa.Column('origin', sa.String(length=30), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_catalogue_subcategory_name_not_blank')),
    sa.ForeignKeyConstraint(['category_id'], ['catalogue_category.id'], name=op.f('fk_catalogue_subcategory_category_id_catalogue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_subcategory_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_catalogue_subcategory_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_catalogue_subcategory_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_catalogue_subcategory')),
    sa.UniqueConstraint('company_id', 'category_id', 'name_key', name='uq_catalogue_subcategory_name_key'),
    sa.UniqueConstraint('id', 'category_id', name='uq_catalogue_subcategory_id_category')
    )
    op.create_index(op.f('ix_catalogue_subcategory_category_id'), 'catalogue_subcategory', ['category_id'], unique=False)
    op.create_index(op.f('ix_catalogue_subcategory_company_id'), 'catalogue_subcategory', ['company_id'], unique=False)
    op.create_table('parties_party',
    sa.Column('party_number', sa.String(length=20), nullable=False),
    sa.Column('legal_name', sa.String(length=200), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('name_key', sa.String(length=200), nullable=False),
    sa.Column('country_code', sa.CHAR(length=2), nullable=False),
    sa.Column('default_currency', sa.CHAR(length=3), nullable=False),
    sa.Column('customer_type', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('roles', sa.ARRAY(sa.String(length=20)), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.Uuid(), nullable=True),
    sa.Column('branch_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("btrim(legal_name) <> '' AND btrim(display_name) <> ''", name=op.f('ck_parties_party_names_not_blank')),
    sa.CheckConstraint("cardinality(roles) > 0 AND roles <@ ARRAY['customer','vendor','fabricator','job_worker']::varchar[]", name=op.f('ck_parties_party_roles_values')),
    sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name=op.f('ck_parties_party_country_code_format')),
    sa.CheckConstraint("default_currency IN ('INR','EUR','USD','GBP')", name=op.f('ck_parties_party_default_currency_enabled')),
    sa.CheckConstraint("party_number ~ '^P-[0-9]{5,}$'", name=op.f('ck_parties_party_party_number_format')),
    sa.ForeignKeyConstraint(['archived_by'], ['app_user.id'], name=op.f('fk_parties_party_archived_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['branch_id'], ['branch.id'], name=op.f('fk_parties_party_branch_id_branch'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_parties_party_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_parties_party_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['app_user.id'], name=op.f('fk_parties_party_owner_user_id_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_parties_party_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parties_party'))
    )
    op.create_index(op.f('ix_parties_party_branch_id'), 'parties_party', ['branch_id'], unique=False)
    op.create_index(op.f('ix_parties_party_company_id'), 'parties_party', ['company_id'], unique=False)
    op.create_index('ix_parties_party_name_key', 'parties_party', ['company_id', 'name_key'], unique=False)
    op.create_index('ix_parties_party_owner', 'parties_party', ['company_id', 'owner_user_id'], unique=False)
    op.create_index('ix_parties_party_roles', 'parties_party', ['roles'], unique=False, postgresql_using='gin')
    op.create_index('ix_parties_party_search_trgm', 'parties_party', ['search_text'], unique=False, postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.create_index('uq_parties_party_number', 'parties_party', ['company_id', 'party_number'], unique=True)
    op.create_table('catalogue_product',
    sa.Column('product_key', sa.String(length=120), nullable=False),
    sa.Column('display_sku', sa.String(length=120), nullable=False),
    sa.Column('product_name', sa.String(length=300), nullable=False),
    sa.Column('brand', sa.String(length=40), nullable=True),
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.Column('subcategory_id', sa.Uuid(), nullable=True),
    sa.Column('category_source', sa.String(length=200), nullable=True),
    sa.Column('subcategory_source', sa.String(length=200), nullable=True),
    sa.Column('product_type', sa.String(length=200), nullable=True),
    sa.Column('variant_group', sa.String(length=200), nullable=True),
    sa.Column('unit_of_sale', sa.String(length=20), nullable=True),
    sa.Column('decor_no', sa.String(length=40), nullable=True),
    sa.Column('decor_no_source', sa.String(length=80), nullable=True),
    sa.Column('decor_name', sa.String(length=200), nullable=True),
    sa.Column('decor_primary', sa.String(length=40), nullable=True),
    sa.Column('decor_options', sa.ARRAY(sa.String(length=40)), nullable=True),
    sa.Column('decor_options_text', sa.Text(), nullable=True),
    sa.Column('finish', sa.String(length=200), nullable=True),
    sa.Column('shape', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('internal_remarks', sa.Text(), nullable=True),
    sa.Column('source_design_no', sa.String(length=200), nullable=True),
    sa.Column('source_shape_no', sa.String(length=200), nullable=True),
    sa.Column('source_sheet', sa.String(length=200), nullable=True),
    sa.Column('source_row', sa.String(length=200), nullable=True),
    sa.Column('source_catalog_page', sa.String(length=200), nullable=True),
    sa.Column('source_notes', sa.Text(), nullable=True),
    sa.Column('source_extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('origin', sa.String(length=30), nullable=False),
    sa.Column('origin_ref', sa.String(length=200), nullable=True),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('size_length_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('size_width_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('size_height_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('size_diameter_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('size_basis', sa.String(length=30), nullable=True),
    sa.Column('hsn_sac', sa.String(length=8), nullable=True),
    sa.Column('stock_uom_code', sa.String(length=20), nullable=True),
    sa.Column('is_stock_tracked', sa.Boolean(), nullable=True),
    sa.Column('track_lots', sa.Boolean(), nullable=True),
    sa.Column('qc_required', sa.Boolean(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("btrim(display_sku) <> '' AND btrim(product_name) <> ''", name=op.f('ck_catalogue_product_names_not_blank')),
    sa.CheckConstraint("hsn_sac IS NULL OR hsn_sac ~ '^[0-9]{4,8}$'", name=op.f('ck_catalogue_product_hsn_sac_format')),
    sa.CheckConstraint("product_key = btrim(product_key) AND length(product_key) BETWEEN 1 AND 120 AND product_key !~ '[[:cntrl:]]'", name=op.f('ck_catalogue_product_product_key_format')),
    sa.CheckConstraint('(size_length_mm IS NULL OR size_length_mm > 0) AND (size_width_mm IS NULL OR size_width_mm > 0) AND (size_height_mm IS NULL OR size_height_mm > 0) AND (size_diameter_mm IS NULL OR size_diameter_mm > 0)', name=op.f('ck_catalogue_product_size_positive')),
    sa.ForeignKeyConstraint(['archived_by'], ['app_user.id'], name=op.f('fk_catalogue_product_archived_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['category_id'], ['catalogue_category.id'], name=op.f('fk_catalogue_product_category_id_catalogue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_product_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_catalogue_product_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subcategory_id', 'category_id'], ['catalogue_subcategory.id', 'catalogue_subcategory.category_id'], name='fk_catalogue_product_subcategory_in_category', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_catalogue_product_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_catalogue_product')),
    sa.UniqueConstraint('company_id', 'product_key', name='uq_catalogue_product_key')
    )
    op.create_index('ix_catalogue_product_brand', 'catalogue_product', ['company_id', 'brand'], unique=False)
    op.create_index(op.f('ix_catalogue_product_company_id'), 'catalogue_product', ['company_id'], unique=False)
    op.create_index('ix_catalogue_product_decor', 'catalogue_product', ['company_id', 'decor_no'], unique=False)
    op.create_index('ix_catalogue_product_display_sku', 'catalogue_product', ['company_id', 'display_sku'], unique=False)
    op.create_index('ix_catalogue_product_finish', 'catalogue_product', ['company_id', 'finish'], unique=False)
    op.create_index('ix_catalogue_product_search_trgm', 'catalogue_product', ['search_text'], unique=False, postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.create_index('ix_catalogue_product_size', 'catalogue_product', ['company_id', 'size_length_mm', 'size_width_mm'], unique=False)
    op.create_index('ix_catalogue_product_status_live', 'catalogue_product', ['company_id', 'status'], unique=False, postgresql_where=sa.text('archived_at IS NULL'))
    op.create_index('ix_catalogue_product_taxonomy', 'catalogue_product', ['company_id', 'category_id', 'subcategory_id'], unique=False)
    op.create_index('ix_catalogue_product_updated', 'catalogue_product', ['company_id', sa.literal_column('updated_at DESC')], unique=False)
    op.create_index('ix_catalogue_product_variant_group', 'catalogue_product', ['company_id', 'variant_group'], unique=False)
    op.create_table('parties_party_address',
    sa.Column('party_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('line1', sa.String(length=200), nullable=False),
    sa.Column('line2', sa.String(length=200), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('region', sa.String(length=120), nullable=True),
    sa.Column('postal_code', sa.String(length=20), nullable=True),
    sa.Column('country_code', sa.CHAR(length=2), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name=op.f('ck_parties_party_address_country_code_format')),
    sa.ForeignKeyConstraint(['archived_by'], ['app_user.id'], name=op.f('fk_parties_party_address_archived_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_parties_party_address_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_parties_party_address_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['party_id'], ['parties_party.id'], name=op.f('fk_parties_party_address_party_id_parties_party'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_parties_party_address_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parties_party_address'))
    )
    op.create_index(op.f('ix_parties_party_address_company_id'), 'parties_party_address', ['company_id'], unique=False)
    op.create_index(op.f('ix_parties_party_address_party_id'), 'parties_party_address', ['party_id'], unique=False)
    op.create_index('uq_parties_party_address_default', 'parties_party_address', ['party_id', 'kind'], unique=True, postgresql_where=sa.text('is_default AND archived_at IS NULL'))
    op.create_table('parties_party_contact',
    sa.Column('party_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('job_title', sa.String(length=120), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['archived_by'], ['app_user.id'], name=op.f('fk_parties_party_contact_archived_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_parties_party_contact_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_parties_party_contact_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['party_id'], ['parties_party.id'], name=op.f('fk_parties_party_contact_party_id_parties_party'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_parties_party_contact_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parties_party_contact'))
    )
    op.create_index(op.f('ix_parties_party_contact_company_id'), 'parties_party_contact', ['company_id'], unique=False)
    op.create_index(op.f('ix_parties_party_contact_party_id'), 'parties_party_contact', ['party_id'], unique=False)
    op.create_index('uq_parties_party_contact_primary', 'parties_party_contact', ['party_id'], unique=True, postgresql_where=sa.text('is_primary AND archived_at IS NULL'))
    op.create_table('parties_party_tax_identifier',
    sa.Column('party_id', sa.Uuid(), nullable=False),
    sa.Column('scheme', sa.String(length=10), nullable=False),
    sa.Column('value', sa.String(length=40), nullable=False),
    sa.Column('country_code', sa.CHAR(length=2), nullable=True),
    sa.Column('verification_status', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("scheme <> 'gstin' OR value ~ '^[0-9]{2}[A-Z0-9]{13}$'", name=op.f('ck_parties_party_tax_identifier_gstin_format')),
    sa.CheckConstraint("scheme <> 'pan' OR value ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'", name=op.f('ck_parties_party_tax_identifier_pan_format')),
    sa.CheckConstraint("verification_status = 'unverified'", name=op.f('ck_parties_party_tax_identifier_never_claimed_verified')),
    sa.ForeignKeyConstraint(['archived_by'], ['app_user.id'], name=op.f('fk_parties_party_tax_identifier_archived_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_parties_party_tax_identifier_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_parties_party_tax_identifier_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['party_id'], ['parties_party.id'], name=op.f('fk_parties_party_tax_identifier_party_id_parties_party'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_parties_party_tax_identifier_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parties_party_tax_identifier'))
    )
    op.create_index(op.f('ix_parties_party_tax_identifier_company_id'), 'parties_party_tax_identifier', ['company_id'], unique=False)
    op.create_index(op.f('ix_parties_party_tax_identifier_party_id'), 'parties_party_tax_identifier', ['party_id'], unique=False)
    op.create_index('uq_parties_party_tax_identifier_value', 'parties_party_tax_identifier', ['company_id', 'scheme', 'value'], unique=True, postgresql_where=sa.text('archived_at IS NULL'))
    op.create_table('pricing_price_list',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('price_type', sa.String(length=20), nullable=False),
    sa.Column('scope_kind', sa.String(length=20), nullable=False),
    sa.Column('party_id', sa.Uuid(), nullable=True),
    sa.Column('customer_type', sa.String(length=20), nullable=True),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('default_unit_code', sa.String(length=20), nullable=True),
    sa.Column('price_basis', sa.String(length=120), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=200), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_by', sa.Uuid(), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_by', sa.Uuid(), nullable=True),
    sa.Column('retire_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("(scope_kind = 'customer' AND party_id IS NOT NULL AND customer_type IS NULL) OR (scope_kind = 'customer_type' AND party_id IS NULL AND customer_type IS NOT NULL) OR (scope_kind = 'standard' AND party_id IS NULL AND customer_type IS NULL)", name=op.f('ck_pricing_price_list_scope_target')),
    sa.CheckConstraint("currency IN ('INR','EUR','USD','GBP')", name=op.f('ck_pricing_price_list_currency_enabled')),
    sa.CheckConstraint('priority IS NULL OR priority >= 0', name=op.f('ck_pricing_price_list_priority_non_negative')),
    sa.CheckConstraint('valid_to IS NULL OR valid_to >= valid_from', name=op.f('ck_pricing_price_list_validity_order')),
    sa.ForeignKeyConstraint(['activated_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_activated_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_pricing_price_list_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['party_id'], ['parties_party.id'], name=op.f('fk_pricing_price_list_party_id_parties_party'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['retired_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_retired_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pricing_price_list')),
    sa.UniqueConstraint('company_id', 'code', name='uq_pricing_price_list_code'),
    sa.UniqueConstraint('id', 'currency', name='uq_pricing_price_list_id_currency')
    )
    op.create_index(op.f('ix_pricing_price_list_company_id'), 'pricing_price_list', ['company_id'], unique=False)
    op.create_index('ix_pricing_price_list_lookup', 'pricing_price_list', ['company_id', 'status', 'scope_kind', 'price_type', 'currency'], unique=False)
    op.create_index('ix_pricing_price_list_party', 'pricing_price_list', ['company_id', 'party_id'], unique=False)
    op.create_table('catalogue_product_dimension',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('source_field', sa.String(length=60), nullable=False),
    sa.Column('source_text', sa.String(length=200), nullable=False),
    sa.Column('length_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('width_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('height_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('diameter_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('source_unit', sa.String(length=10), nullable=True),
    sa.Column('unit_inferred', sa.Boolean(), nullable=False),
    sa.Column('parse_status', sa.String(length=20), nullable=False),
    sa.Column('parse_warnings', sa.ARRAY(sa.String(length=60)), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_product_dimension_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['catalogue_product.id'], name=op.f('fk_catalogue_product_dimension_product_id_catalogue_product'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_catalogue_product_dimension')),
    sa.UniqueConstraint('product_id', 'kind', name='uq_catalogue_product_dimension_kind')
    )
    op.create_index(op.f('ix_catalogue_product_dimension_company_id'), 'catalogue_product_dimension', ['company_id'], unique=False)
    op.create_index('ix_catalogue_product_dimension_status', 'catalogue_product_dimension', ['company_id', 'parse_status'], unique=False)
    op.create_table('catalogue_product_packaging',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('carton_qty', sa.Integer(), nullable=True),
    sa.Column('inner_qty', sa.Integer(), nullable=True),
    sa.Column('unit_weight_g', sa.Numeric(precision=14, scale=3), nullable=True),
    sa.Column('packing_type', sa.String(length=200), nullable=True),
    sa.Column('carton_length_cm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('carton_width_cm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('carton_height_cm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('net_weight_kg', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('gross_weight_kg', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('cbm', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('packaging_notes', sa.Text(), nullable=True),
    sa.Column('fragile_notes', sa.Text(), nullable=True),
    sa.Column('packaging_status', sa.String(length=200), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('alias_provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source_extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('(carton_length_cm IS NULL OR carton_length_cm > 0) AND (carton_width_cm IS NULL OR carton_width_cm > 0) AND (carton_height_cm IS NULL OR carton_height_cm > 0)', name=op.f('ck_catalogue_product_packaging_carton_dimensions_positive')),
    sa.CheckConstraint('(carton_qty IS NULL OR carton_qty > 0) AND (inner_qty IS NULL OR inner_qty > 0)', name=op.f('ck_catalogue_product_packaging_quantities_positive')),
    sa.CheckConstraint('(unit_weight_g IS NULL OR unit_weight_g > 0) AND (net_weight_kg IS NULL OR net_weight_kg > 0) AND (gross_weight_kg IS NULL OR gross_weight_kg > 0) AND (cbm IS NULL OR cbm > 0)', name=op.f('ck_catalogue_product_packaging_weights_positive')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_product_packaging_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['catalogue_product.id'], name=op.f('fk_catalogue_product_packaging_product_id_catalogue_product'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('product_id', name=op.f('pk_catalogue_product_packaging'))
    )
    op.create_index(op.f('ix_catalogue_product_packaging_company_id'), 'catalogue_product_packaging', ['company_id'], unique=False)
    op.create_table('catalogue_product_specification',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('length_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('length_mm_source', sa.String(length=80), nullable=True),
    sa.Column('width_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('width_mm_source', sa.String(length=80), nullable=True),
    sa.Column('height_mm', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('height_mm_source', sa.String(length=80), nullable=True),
    sa.Column('thickness_mm', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('thickness_mm_source', sa.String(length=80), nullable=True),
    sa.Column('thickness_text', sa.String(length=200), nullable=True),
    sa.Column('size_label', sa.String(length=200), nullable=True),
    sa.Column('spec_finish', sa.String(length=200), nullable=True),
    sa.Column('material_type', sa.String(length=200), nullable=True),
    sa.Column('groove_count', sa.Integer(), nullable=True),
    sa.Column('bowl_count', sa.Integer(), nullable=True),
    sa.Column('bowl_type', sa.String(length=200), nullable=True),
    sa.Column('top_sheet', sa.String(length=200), nullable=True),
    sa.Column('stand_material', sa.String(length=200), nullable=True),
    sa.Column('spec_type', sa.String(length=200), nullable=True),
    sa.Column('no_of_boards', sa.Integer(), nullable=True),
    sa.Column('handle_type', sa.String(length=200), nullable=True),
    sa.Column('special_features', sa.Text(), nullable=True),
    sa.Column('care_instructions', sa.Text(), nullable=True),
    sa.Column('usage_notes', sa.Text(), nullable=True),
    sa.Column('source_extra', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('(groove_count IS NULL OR groove_count >= 0) AND (bowl_count IS NULL OR bowl_count >= 0) AND (no_of_boards IS NULL OR no_of_boards >= 0)', name=op.f('ck_catalogue_product_specification_counts_non_negative')),
    sa.CheckConstraint('(length_mm IS NULL OR length_mm > 0) AND (width_mm IS NULL OR width_mm > 0) AND (height_mm IS NULL OR height_mm > 0) AND (thickness_mm IS NULL OR thickness_mm > 0)', name=op.f('ck_catalogue_product_specification_dimensions_positive')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_catalogue_product_specification_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['catalogue_product.id'], name=op.f('fk_catalogue_product_specification_product_id_catalogue_product'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('product_id', name=op.f('pk_catalogue_product_specification'))
    )
    op.create_index(op.f('ix_catalogue_product_specification_company_id'), 'catalogue_product_specification', ['company_id'], unique=False)
    op.create_index('ix_catalogue_product_specification_thickness', 'catalogue_product_specification', ['company_id', 'thickness_mm'], unique=False)
    op.create_table('pricing_price_list_item',
    sa.Column('price_list_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('product_key', sa.String(length=120), nullable=False),
    sa.Column('display_sku', sa.String(length=120), nullable=True),
    sa.Column('unit_code', sa.String(length=20), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('final_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('base_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('base_price_label', sa.String(length=120), nullable=True),
    sa.Column('addon_price', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('addon_price_label', sa.String(length=120), nullable=True),
    sa.Column('price_basis', sa.String(length=120), nullable=True),
    sa.Column('yield_qty_per_board', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('thickness_mm', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('moq', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('moq_unit_code', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('superseded_by_item_id', sa.Uuid(), nullable=True),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=200), nullable=True),
    sa.Column('source_sheet', sa.String(length=200), nullable=True),
    sa.Column('source_row', sa.String(length=40), nullable=True),
    sa.Column('import_job_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint('(base_price IS NULL OR base_price >= 0) AND (addon_price IS NULL OR addon_price >= 0)', name=op.f('ck_pricing_price_list_item_breakdown_non_negative')),
    sa.CheckConstraint('(yield_qty_per_board IS NULL OR yield_qty_per_board > 0) AND (moq IS NULL OR moq > 0) AND (thickness_mm IS NULL OR thickness_mm > 0)', name=op.f('ck_pricing_price_list_item_quantities_positive')),
    sa.CheckConstraint('final_price IS NULL OR final_price = unit_price', name=op.f('ck_pricing_price_list_item_final_price_matches_unit_price')),
    sa.CheckConstraint('unit_price >= 0', name=op.f('ck_pricing_price_list_item_unit_price_non_negative')),
    sa.CheckConstraint('valid_to IS NULL OR valid_to >= valid_from', name=op.f('ck_pricing_price_list_item_validity_order')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_pricing_price_list_item_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_item_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['price_list_id'], ['pricing_price_list.id'], name=op.f('fk_pricing_price_list_item_price_list_id_pricing_price_list'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['catalogue_product.id'], name=op.f('fk_pricing_price_list_item_product_id_catalogue_product'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['superseded_by_item_id'], ['pricing_price_list_item.id'], name='fk_pricing_price_list_item_superseded_by', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_pricing_price_list_item_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pricing_price_list_item'))
    )
    op.create_index(op.f('ix_pricing_price_list_item_company_id'), 'pricing_price_list_item', ['company_id'], unique=False)
    op.create_index('ix_pricing_price_list_item_list_product', 'pricing_price_list_item', ['price_list_id', 'product_id'], unique=False)
    op.create_index('ix_pricing_price_list_item_product', 'pricing_price_list_item', ['company_id', 'product_id'], unique=False)
    op.create_table('pricing_product_cost',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('cost_version', sa.Integer(), nullable=False),
    sa.Column('unit_cost_amount', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('unit_cost_currency', sa.CHAR(length=3), nullable=False),
    sa.Column('unit_code', sa.String(length=20), nullable=False),
    sa.Column('cost_components', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source_kind', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=200), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("unit_cost_currency IN ('INR','EUR','USD','GBP')", name=op.f('ck_pricing_product_cost_unit_cost_currency_enabled')),
    sa.CheckConstraint('cost_version > 0', name=op.f('ck_pricing_product_cost_cost_version_positive')),
    sa.CheckConstraint('unit_cost_amount >= 0', name=op.f('ck_pricing_product_cost_unit_cost_non_negative')),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_pricing_product_cost_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_pricing_product_cost_created_by_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['catalogue_product.id'], name=op.f('fk_pricing_product_cost_product_id_catalogue_product'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_pricing_product_cost_updated_by_app_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pricing_product_cost')),
    sa.UniqueConstraint('company_id', 'product_id', 'cost_version', name='uq_pricing_product_cost_version')
    )
    op.create_index(op.f('ix_pricing_product_cost_company_id'), 'pricing_product_cost', ['company_id'], unique=False)
    op.create_table('pricing_price_list_item_history',
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('price_list_id', sa.Uuid(), nullable=False),
    sa.Column('change_kind', sa.String(length=20), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['app_user.id'], name=op.f('fk_pricing_price_list_item_history_actor_user_id_app_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], name=op.f('fk_pricing_price_list_item_history_company_id_company'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['item_id'], ['pricing_price_list_item.id'], name='fk_pricing_price_list_item_history_item', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['price_list_id'], ['pricing_price_list.id'], name='fk_pricing_price_list_item_history_list', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pricing_price_list_item_history'))
    )
    op.create_index(op.f('ix_pricing_price_list_item_history_company_id'), 'pricing_price_list_item_history', ['company_id'], unique=False)
    op.create_index('ix_pricing_price_list_item_history_item', 'pricing_price_list_item_history', ['item_id', 'occurred_at'], unique=False)
    # ### end Alembic commands ###

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
    for table in APPEND_ONLY_TABLES:
        helpers.append_only(table)
    for table, column, values in ENUMS:
        helpers.enum_check(table, column, values)
    for table, column in UOM_COLUMNS:
        helpers.enum_check(table, column, UOM_CODES, name=f"{column}_uom")

    # an active price never overlaps another active price of the same (list, product, unit)
    op.execute(
        "ALTER TABLE pricing_price_list_item ADD CONSTRAINT ex_pricing_price_list_item_no_overlap EXCLUDE USING gist "
        "(price_list_id WITH =, product_id WITH =, unit_code WITH =, "
        "daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[]') WITH &&) WHERE (status = 'active')"
    )
    # product_key is the immutable business key (the API never accepts it on update; the database refuses too)
    op.execute(PRODUCT_KEY_GUARD)
    op.execute(
        "CREATE TRIGGER trg_catalogue_product_key_immutable BEFORE UPDATE OF product_key ON catalogue_product "
        "FOR EACH ROW EXECUTE FUNCTION lk_catalogue_product_key_immutable()"
    )
    # active price-list items change only through an effective-dated supersede (the database refuses edits too)
    op.execute(PRICE_ITEM_GUARD)
    op.execute(
        "CREATE TRIGGER trg_pricing_price_list_item_immutable BEFORE UPDATE ON pricing_price_list_item "
        "FOR EACH ROW EXECUTE FUNCTION lk_pricing_price_list_item_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pricing_price_list_item_immutable ON pricing_price_list_item")
    op.execute("DROP FUNCTION IF EXISTS lk_pricing_price_list_item_immutable()")
    op.execute("DROP TRIGGER IF EXISTS trg_catalogue_product_key_immutable ON catalogue_product")
    op.execute("DROP FUNCTION IF EXISTS lk_catalogue_product_key_immutable()")
    # policies, CHECKs, the exclusion constraint and append-only triggers are dropped with their tables
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_pricing_price_list_item_history_item', table_name='pricing_price_list_item_history')
    op.drop_index(op.f('ix_pricing_price_list_item_history_company_id'), table_name='pricing_price_list_item_history')
    op.drop_table('pricing_price_list_item_history')
    op.drop_index(op.f('ix_pricing_product_cost_company_id'), table_name='pricing_product_cost')
    op.drop_table('pricing_product_cost')
    op.drop_index('ix_pricing_price_list_item_product', table_name='pricing_price_list_item')
    op.drop_index('ix_pricing_price_list_item_list_product', table_name='pricing_price_list_item')
    op.drop_index(op.f('ix_pricing_price_list_item_company_id'), table_name='pricing_price_list_item')
    op.drop_table('pricing_price_list_item')
    op.drop_index('ix_catalogue_product_specification_thickness', table_name='catalogue_product_specification')
    op.drop_index(op.f('ix_catalogue_product_specification_company_id'), table_name='catalogue_product_specification')
    op.drop_table('catalogue_product_specification')
    op.drop_index(op.f('ix_catalogue_product_packaging_company_id'), table_name='catalogue_product_packaging')
    op.drop_table('catalogue_product_packaging')
    op.drop_index('ix_catalogue_product_dimension_status', table_name='catalogue_product_dimension')
    op.drop_index(op.f('ix_catalogue_product_dimension_company_id'), table_name='catalogue_product_dimension')
    op.drop_table('catalogue_product_dimension')
    op.drop_index('ix_pricing_price_list_party', table_name='pricing_price_list')
    op.drop_index('ix_pricing_price_list_lookup', table_name='pricing_price_list')
    op.drop_index(op.f('ix_pricing_price_list_company_id'), table_name='pricing_price_list')
    op.drop_table('pricing_price_list')
    op.drop_index('uq_parties_party_tax_identifier_value', table_name='parties_party_tax_identifier', postgresql_where=sa.text('archived_at IS NULL'))
    op.drop_index(op.f('ix_parties_party_tax_identifier_party_id'), table_name='parties_party_tax_identifier')
    op.drop_index(op.f('ix_parties_party_tax_identifier_company_id'), table_name='parties_party_tax_identifier')
    op.drop_table('parties_party_tax_identifier')
    op.drop_index('uq_parties_party_contact_primary', table_name='parties_party_contact', postgresql_where=sa.text('is_primary AND archived_at IS NULL'))
    op.drop_index(op.f('ix_parties_party_contact_party_id'), table_name='parties_party_contact')
    op.drop_index(op.f('ix_parties_party_contact_company_id'), table_name='parties_party_contact')
    op.drop_table('parties_party_contact')
    op.drop_index('uq_parties_party_address_default', table_name='parties_party_address', postgresql_where=sa.text('is_default AND archived_at IS NULL'))
    op.drop_index(op.f('ix_parties_party_address_party_id'), table_name='parties_party_address')
    op.drop_index(op.f('ix_parties_party_address_company_id'), table_name='parties_party_address')
    op.drop_table('parties_party_address')
    op.drop_index('ix_catalogue_product_variant_group', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_updated', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_taxonomy', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_status_live', table_name='catalogue_product', postgresql_where=sa.text('archived_at IS NULL'))
    op.drop_index('ix_catalogue_product_size', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_search_trgm', table_name='catalogue_product', postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.drop_index('ix_catalogue_product_finish', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_display_sku', table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_decor', table_name='catalogue_product')
    op.drop_index(op.f('ix_catalogue_product_company_id'), table_name='catalogue_product')
    op.drop_index('ix_catalogue_product_brand', table_name='catalogue_product')
    op.drop_table('catalogue_product')
    op.drop_index('uq_parties_party_number', table_name='parties_party')
    op.drop_index('ix_parties_party_search_trgm', table_name='parties_party', postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.drop_index('ix_parties_party_roles', table_name='parties_party', postgresql_using='gin')
    op.drop_index('ix_parties_party_owner', table_name='parties_party')
    op.drop_index('ix_parties_party_name_key', table_name='parties_party')
    op.drop_index(op.f('ix_parties_party_company_id'), table_name='parties_party')
    op.drop_index(op.f('ix_parties_party_branch_id'), table_name='parties_party')
    op.drop_table('parties_party')
    op.drop_index(op.f('ix_catalogue_subcategory_company_id'), table_name='catalogue_subcategory')
    op.drop_index(op.f('ix_catalogue_subcategory_category_id'), table_name='catalogue_subcategory')
    op.drop_table('catalogue_subcategory')
    op.drop_index('uq_commercial_rule_set_one_active', table_name='commercial_rule_set', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_commercial_rule_set_company_id'), table_name='commercial_rule_set')
    op.drop_table('commercial_rule_set')
    op.drop_index(op.f('ix_catalogue_lookup_reference_company_id'), table_name='catalogue_lookup_reference')
    op.drop_table('catalogue_lookup_reference')
    op.drop_index(op.f('ix_catalogue_category_company_id'), table_name='catalogue_category')
    op.drop_table('catalogue_category')
    # ### end Alembic commands ###
