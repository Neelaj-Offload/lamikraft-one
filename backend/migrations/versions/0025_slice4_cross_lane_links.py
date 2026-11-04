"""Slice-4 cross-lane links (integrator): quality inspections of work-order output reference the work order

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-05 00:00:00+00:00

The procurement/quality/logistics lane kept ``quality_inspection.work_order_id`` as a plain id column because the
production lane owned ``production_work_order`` (procurement-logistics report, integrator request 5). Both lanes now
share one chain, so the column gets its foreign key (RESTRICT: a work order with inspections is never deleted; work
orders are cancelled, not deleted).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        op.f("fk_quality_inspection_work_order_id_production_work_order"),
        "quality_inspection",
        "production_work_order",
        ["work_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_quality_inspection_work_order_id_production_work_order"), "quality_inspection", type_="foreignkey"
    )
