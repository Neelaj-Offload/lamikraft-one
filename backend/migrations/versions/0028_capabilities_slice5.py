"""Slice-5 new capabilities (lane s5-capabilities): offcut reuse in cut plans

Revision ID: 0028 (lane placeholder 0090, renumbered at the Slice-5 merge)
Revises: 0027
Create Date: 2026-11-05 00:00:00+00:00

It needs only the cutting tables of 0013 and ``inventory_lot`` of 0022.

- ``cutting_plan_offcut``: the measured offcut lots a plan may cut from (pinned size, grain along the length), tenant
  table with forced RLS; one row per (plan, lot) and per (plan, seq).
- ``cutting_calc_board.lot_id`` gets its foreign key to ``inventory_lot`` (RESTRICT) and a CHECK that an ``offcut``
  board names its lot. The column existed since Slice 2 and was always null, so existing rows satisfy both.

Sample lineage and the what-if screens need no schema change (``sales_sample`` already links the quote, the custom
product and the challan; the simulation is read-only).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations import helpers

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cutting_plan_offcut",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("lot_code", sa.String(length=60), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("decor_key", sa.String(length=40), nullable=False),
        sa.Column("thickness_key", sa.String(length=20), nullable=False),
        sa.Column("length_mm", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("width_mm", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("grain_axis", sa.String(length=10), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("length_mm > 0 AND width_mm > 0 AND seq > 0", name=op.f("ck_cutting_plan_offcut_positive")),
        sa.CheckConstraint(
            "grain_axis IS NULL OR grain_axis IN ('length', 'width', 'none')",
            name=op.f("ck_cutting_plan_offcut_grain_axis_values"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], name=op.f("fk_cutting_plan_offcut_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f("fk_cutting_plan_offcut_created_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_user.id"], name=op.f("fk_cutting_plan_offcut_updated_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["inventory_lot.id"], name=op.f("fk_cutting_plan_offcut_lot_id_inventory_lot"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_id"], ["cutting_plan.id"], name=op.f("fk_cutting_plan_offcut_plan_id_cutting_plan"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cutting_plan_offcut")),
    )
    op.create_index(op.f("ix_cutting_plan_offcut_company_id"), "cutting_plan_offcut", ["company_id"], unique=False)
    op.create_index("uq_cutting_plan_offcut_lot", "cutting_plan_offcut", ["plan_id", "lot_id"], unique=True)
    op.create_index("uq_cutting_plan_offcut_seq", "cutting_plan_offcut", ["plan_id", "seq"], unique=True)
    helpers.enable_tenant_rls("cutting_plan_offcut")

    op.create_foreign_key(
        op.f("fk_cutting_calc_board_lot_id_inventory_lot"), "cutting_calc_board", "inventory_lot", ["lot_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_cutting_calc_board_offcut_has_lot"),
        "cutting_calc_board",
        "(source = 'offcut') = (lot_id IS NOT NULL) OR source = 'board_lot'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_cutting_calc_board_offcut_has_lot"), "cutting_calc_board", type_="check")
    op.drop_constraint(op.f("fk_cutting_calc_board_lot_id_inventory_lot"), "cutting_calc_board", type_="foreignkey")
    op.drop_index("uq_cutting_plan_offcut_seq", table_name="cutting_plan_offcut")
    op.drop_index("uq_cutting_plan_offcut_lot", table_name="cutting_plan_offcut")
    op.drop_index(op.f("ix_cutting_plan_offcut_company_id"), table_name="cutting_plan_offcut")
    op.drop_table("cutting_plan_offcut")
