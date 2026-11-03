"""voice + vision (Slice 3): utterances, spoken replies, read-backs, masked screen captures, vision requests

Revision ID: 0030
Revises: 0015
Create Date: 2026-11-04 03:00:00+00:00

Placeholder number (completion program: parallel lanes use 0030+; the Slice-3 integrator renumbers and reparents it
after the agents-s3 ``0020`` and WhatsApp ``0022`` migrations).

- ``voice_utterance``: the primary key is the client's UUIDv7; ``turn_id`` unique when set; audio purged after 7 days.
- ``voice_speech``: synthesised replies (text hash only, never the text); ``voice_readback``: presented read-backs.
- ``vision_capture``: one live capture per (company, user, conversation, sha256) — partial unique index over
  ``coalesce(conversation_id, nil uuid)`` while not purged; ``vision_request`` is always tainted (CHECK).
- ``file_object.purpose`` gains ``screen_capture`` (restricted masked screenshots, purged after 24 hours).
- Every new table is a tenant table with forced fail-closed RLS; enumerations are varchar + CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations import helpers

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("voice_utterance", "voice_speech", "voice_readback", "vision_capture", "vision_request")
ENUMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("voice_utterance", "status", ("received", "transcribed", "failed", "submitted")),
    ("voice_utterance", "source", ("server", "browser")),
    ("vision_capture", "status", ("attached", "removed", "purged")),
    ("vision_request", "kind", ("screen_answer", "extraction")),
    ("vision_request", "status", ("answered", "handed_off", "extracted", "confirmed", "unavailable")),
)


def _tenant_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _tenant_constraints(table: str) -> list[sa.SchemaItem]:
    return [
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], name=op.f(f"fk_{table}_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f(f"fk_{table}_created_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["app_user.id"], name=op.f(f"fk_{table}_updated_by_app_user"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name=op.f(f"fk_{table}_user_id_app_user"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "voice_utterance",
        *_tenant_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("audio_key", sa.String(length=200), nullable=True),
        sa.Column("audio_sha256", sa.String(length=64), nullable=True),
        sa.Column("audio_mime", sa.String(length=40), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=True),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("submitted_text", sa.Text(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("corrects_turn_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("audio_sha256 IS NULL OR audio_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_voice_utterance_audio_sha256_format")),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms BETWEEN 0 AND 60000", name=op.f("ck_voice_utterance_duration_bounds")),
        *_tenant_constraints("voice_utterance"),
    )
    op.create_index(op.f("ix_voice_utterance_company_id"), "voice_utterance", ["company_id"])
    op.create_index("ix_voice_utterance_owner", "voice_utterance", ["company_id", "user_id", "created_at"])
    op.create_index("uq_voice_utterance_turn", "voice_utterance", ["turn_id"], unique=True,
                    postgresql_where=sa.text("turn_id IS NOT NULL"))
    op.create_index("ix_voice_utterance_purge", "voice_utterance", ["purge_at"],
                    postgresql_where=sa.text("audio_key IS NOT NULL"))

    op.create_table(
        "voice_speech",
        *_tenant_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("audio_key", sa.String(length=200), nullable=True),
        sa.Column("audio_mime", sa.String(length=40), nullable=False),
        sa.Column("audio_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("url_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True),
        *_tenant_constraints("voice_speech"),
    )
    op.create_index(op.f("ix_voice_speech_company_id"), "voice_speech", ["company_id"])
    op.create_index("ix_voice_speech_owner", "voice_speech", ["company_id", "user_id", "created_at"])
    op.create_index("ix_voice_speech_purge", "voice_speech", ["purge_at"], postgresql_where=sa.text("audio_key IS NOT NULL"))

    op.create_table(
        "voice_readback",
        *_tenant_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=80), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("subject_version", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by", sa.String(length=80), nullable=True),
        *_tenant_constraints("voice_readback"),
    )
    op.create_index(op.f("ix_voice_readback_company_id"), "voice_readback", ["company_id"])
    op.create_index("ix_voice_readback_subject", "voice_readback",
                    ["company_id", "user_id", "subject_type", "subject_id", "presented_at"])

    op.create_table(
        "vision_capture",
        *_tenant_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("masked_count", sa.Integer(), nullable=False),
        sa.Column("route_path", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("purge_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_vision_capture_sha256_format")),
        sa.ForeignKeyConstraint(["file_id"], ["file_object.id"], name=op.f("fk_vision_capture_file_id_file_object"), ondelete="SET NULL"),
        *_tenant_constraints("vision_capture"),
    )
    op.create_index(op.f("ix_vision_capture_company_id"), "vision_capture", ["company_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_vision_capture_conversation_sha ON vision_capture "
        "(company_id, user_id, coalesce(conversation_id, '00000000-0000-0000-0000-000000000000'::uuid), sha256) "
        "WHERE status <> 'purged'"
    )
    op.create_index("ix_vision_capture_purge", "vision_capture", ["purge_at"], postgresql_where=sa.text("status <> 'purged'"))

    op.create_table(
        "vision_request",
        *_tenant_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("extraction_kind", sa.String(length=30), nullable=True),
        sa.Column("capture_id", sa.Uuid(), nullable=True),
        sa.Column("source_file_id", sa.Uuid(), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tainted", sa.Boolean(), nullable=False),
        sa.Column("call_log_id", sa.Uuid(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "extraction_kind IS NULL OR extraction_kind IN ('purchase_order','bill','delivery_note','handwritten_list')",
            name=op.f("ck_vision_request_extraction_kind_values"),
        ),
        sa.CheckConstraint("tainted", name=op.f("ck_vision_request_always_tainted")),
        sa.ForeignKeyConstraint(["capture_id"], ["vision_capture.id"], name=op.f("fk_vision_request_capture_id_vision_capture"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_file_id"], ["file_object.id"], name=op.f("fk_vision_request_source_file_id_file_object"), ondelete="SET NULL"),
        *_tenant_constraints("vision_request"),
    )
    op.create_index(op.f("ix_vision_request_company_id"), "vision_request", ["company_id"])
    op.create_index("ix_vision_request_owner", "vision_request", ["company_id", "user_id", "created_at"])

    for table in TENANT_TABLES:
        helpers.enable_tenant_rls(table)
        helpers.grant_app(table)
    for table, column, values in ENUMS:
        helpers.enum_check(table, column, values)

    op.drop_constraint(op.f("ck_file_object_purpose_values"), "file_object", type_="check")
    op.create_check_constraint(
        op.f("ck_file_object_purpose_values"), "file_object",
        "purpose IN ('image','document','import','export','screen_capture')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM file_object WHERE purpose = 'screen_capture'")
    op.drop_constraint(op.f("ck_file_object_purpose_values"), "file_object", type_="check")
    op.create_check_constraint(
        op.f("ck_file_object_purpose_values"), "file_object", "purpose IN ('image','document','import','export')",
    )
    for table in ("vision_request", "vision_capture", "voice_readback", "voice_speech", "voice_utterance"):
        op.drop_table(table)
