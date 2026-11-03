"""Slice-2 cross-lane links (integrator): challan custom lines and dispatched samples

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04 00:52:27+00:00

- ``challans_challan_line.custom_product_id`` -> ``sales_custom_product.id`` (RESTRICT, like the quote line's FK);
  requested by the challans and commercial-2 lanes once both tables were on one chain.
- ``sales_sample.challan_id`` -> ``challans_challan.id`` (RESTRICT): the challan whose issue dispatched the sample
  (``sales.sample_dispatch`` on ``challans.challan.issued``); requested by the commercial-2 lane.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        op.f("fk_challans_challan_line_custom_product_id_sales_custom_product"),
        "challans_challan_line",
        "sales_custom_product",
        ["custom_product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_sales_sample_challan_id_challans_challan"),
        "sales_sample",
        "challans_challan",
        ["challan_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_sales_sample_challan_id_challans_challan"), "sales_sample", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_challans_challan_line_custom_product_id_sales_custom_product"), "challans_challan_line", type_="foreignkey"
    )
