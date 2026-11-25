"""CRM programme module 4: design numbers, item classes, stock categories, warehouse markets

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-25 00:00:00+00:00

- ``catalogue_product.design_no`` (e.g. CB07) and ``item_class`` (finished / raw_material / packaging; existing rows
  become finished, the demo walnut board LK-WB-1800 raw_material).
- ``inventory_warehouse.market`` (domestic / export) and ``country_code``; existing warehouses become domestic, IN.
- ``inventory_location.stock_category`` (inventory / sample / exhibition). Existing warehouse internal locations are
  inventory; every warehouse gains SAMPLE and EXHIB locations (internal, stock-bearing, not available to sell).

Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("catalogue_product", sa.Column("design_no", sa.String(length=20), nullable=True))
    op.add_column("catalogue_product", sa.Column("item_class", sa.String(length=20), nullable=False,
                                                 server_default="finished"))
    op.create_check_constraint("item_class_values", "catalogue_product",
                               "item_class IN ('finished', 'raw_material', 'packaging')")
    op.create_check_constraint("design_no_format", "catalogue_product", "design_no IS NULL OR design_no ~ '^[A-Z0-9][A-Z0-9-]{0,19}$'")
    op.create_index("ix_catalogue_product_design", "catalogue_product", ["company_id", "design_no"])

    op.add_column("inventory_warehouse", sa.Column("market", sa.String(length=10), nullable=True))
    op.add_column("inventory_warehouse", sa.Column("country_code", sa.CHAR(length=2), nullable=True))
    op.create_check_constraint("market_values", "inventory_warehouse", "market IS NULL OR market IN ('domestic', 'export')")
    op.create_check_constraint("country_code_format", "inventory_warehouse", "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'")

    op.add_column("inventory_location", sa.Column("stock_category", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "stock_category_values", "inventory_location",
        "stock_category IS NULL OR stock_category IN ('inventory', 'sample', 'exhibition')",
    )
    op.create_check_constraint(
        "stock_category_internal", "inventory_location",
        "stock_category IS NULL OR (location_type = 'internal' AND warehouse_id IS NOT NULL)",
    )

    # RLS is forced: each company's rows are written under its own app.company_id
    op.execute(
        """
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN SELECT id FROM company LOOP
                PERFORM set_config('app.company_id', c.id::text, true);
                UPDATE catalogue_product SET item_class = 'raw_material'
                 WHERE company_id = c.id AND product_key = 'LK-WB-1800';
                UPDATE inventory_warehouse SET market = 'domestic', country_code = 'IN' WHERE company_id = c.id;
                UPDATE inventory_location SET stock_category = 'inventory'
                 WHERE company_id = c.id AND location_type = 'internal' AND warehouse_id IS NOT NULL;
                INSERT INTO inventory_location
                    (id, company_id, warehouse_id, code, name, location_type, is_stock_bearing, counts_available,
                     is_default, is_active, stock_category, created_at, updated_at)
                SELECT gen_random_uuid(), c.id, w.id, v.code, v.name, 'internal', true, false, false, true, v.cat, now(), now()
                  FROM inventory_warehouse w
                 CROSS JOIN (VALUES ('SAMPLE', 'Sample stock', 'sample'), ('EXHIB', 'Exhibition stock', 'exhibition'))
                       AS v(code, name, cat)
                 WHERE w.company_id = c.id
                ON CONFLICT DO NOTHING;
            END LOOP;
            PERFORM set_config('app.company_id', '', true);
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM inventory_location WHERE stock_category IN ('sample', 'exhibition') "
               "AND NOT EXISTS (SELECT 1 FROM inventory_stock_balance b WHERE b.location_id = inventory_location.id)")
    op.drop_constraint(op.f("ck_inventory_location_stock_category_internal"), "inventory_location", type_="check")
    op.drop_constraint(op.f("ck_inventory_location_stock_category_values"), "inventory_location", type_="check")
    op.drop_column("inventory_location", "stock_category")
    op.drop_constraint(op.f("ck_inventory_warehouse_country_code_format"), "inventory_warehouse", type_="check")
    op.drop_constraint(op.f("ck_inventory_warehouse_market_values"), "inventory_warehouse", type_="check")
    op.drop_column("inventory_warehouse", "country_code")
    op.drop_column("inventory_warehouse", "market")
    op.drop_index("ix_catalogue_product_design", table_name="catalogue_product")
    op.drop_constraint(op.f("ck_catalogue_product_design_no_format"), "catalogue_product", type_="check")
    op.drop_constraint(op.f("ck_catalogue_product_item_class_values"), "catalogue_product", type_="check")
    op.drop_column("catalogue_product", "item_class")
    op.drop_column("catalogue_product", "design_no")
