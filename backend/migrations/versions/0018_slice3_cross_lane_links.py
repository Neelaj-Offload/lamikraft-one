"""Slice-3 stage-1 cross-lane links (integrator): how a turn arrived

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-04 03:00:00+00:00

- ``agents_turn.input_mode`` (``text`` | ``voice`` | ``wa_text`` | ``wa_voice`` | ``card_action``, default ``text``):
  the WhatsApp lane records the mode on ``channels_message.input_mode`` and asked for it to reach the agents turn once
  both lanes were on one chain (design ``agent_voice_whatsapp.md``, ``agents_turn`` columns). Existing turns are
  ``text``. The voice lane sets ``voice``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents_turn", sa.Column("input_mode", sa.String(length=20), server_default="text", nullable=False))
    op.create_check_constraint(
        op.f("ck_agents_turn_input_mode_values"),
        "agents_turn",
        "input_mode IN ('text','voice','wa_text','wa_voice','card_action')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agents_turn_input_mode_values"), "agents_turn", type_="check")
    op.drop_column("agents_turn", "input_mode")
