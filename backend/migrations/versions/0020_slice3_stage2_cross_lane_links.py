"""Slice-3 stage-2 cross-lane links (integrator): voice and vision facts on the agents turn

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-04 12:00:00+00:00

Design ``agent_voice_whatsapp.md`` section 4 lists ``corrects_turn_id`` and ``transcript_meta`` on the turn; the voice
lane kept them on ``voice_utterance`` until both lanes shared one chain (voice-vision report, integrator request 2).

- ``agents_turn.corrects_turn_id``: a correction after submission names the earlier user turn it corrects (a new
  turn, never an edit). Moved here from ``voice_utterance`` (the lane migration ``0019`` no longer creates it there).
- ``agents_turn.transcript_meta``: ``{provider, language, confidence, edited, original_text}`` for a voice turn.
- ``agents_turn.vision_request_id``: a confirmed vision extraction the turn hands to the run; the run feeds it as the
  untrusted block of ai-routing.md section 6 and is tainted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents_turn", sa.Column("corrects_turn_id", sa.Uuid(), nullable=True))
    op.add_column("agents_turn", sa.Column("transcript_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agents_turn", sa.Column("vision_request_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        op.f("ck_agents_turn_transcript_meta_object"),
        "agents_turn",
        "transcript_meta IS NULL OR jsonb_typeof(transcript_meta) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agents_turn_transcript_meta_object"), "agents_turn", type_="check")
    op.drop_column("agents_turn", "vision_request_id")
    op.drop_column("agents_turn", "transcript_meta")
    op.drop_column("agents_turn", "corrects_turn_id")
