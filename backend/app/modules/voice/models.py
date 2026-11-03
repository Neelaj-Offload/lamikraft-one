"""Voice tables (prefix ``voice_``), design section 4 and 14.

- ``voice_utterance``: the primary key **is** the client's UUIDv7, created when push-to-talk is pressed, so a
  retried upload, a resend after a network blip and an offline draft sent on reconnect all land on the same row
  and the same agents turn (``agents_turn`` is unique on ``(conversation_id, client_utterance_id)``). Audio is
  kept in storage by key and purged after 7 days (``audio_key`` cleared, ``audio_purged_at`` set).
- ``voice_speech``: a synthesised reply; its audio URL is valid for 5 minutes and only for its owner's session.
- ``voice_readback``: a presented read-back (customer, quantity with UOM, unit price with currency, total, dates in
  the user's zone) bound to the subject's content hash; a voice confirm or approve needs one that is unexpired
  (10 minutes) and unchanged.

All three are tenant tables with forced fail-closed RLS and every read is filtered by the owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TenantEntity, VersionMixin


class UtteranceStatus(StrEnum):
    RECEIVED = "received"
    TRANSCRIBED = "transcribed"
    FAILED = "failed"
    SUBMITTED = "submitted"


class UtteranceSource(StrEnum):
    SERVER = "server"  # audio uploaded, transcribed by the server adapter
    BROWSER = "browser"  # transcribed by the browser fallback; no audio on the server


class VoiceUtterance(TenantEntity, VersionMixin, Base):
    __tablename__ = "voice_utterance"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UtteranceStatus.RECEIVED.value)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default=UtteranceSource.SERVER.value)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str | None] = mapped_column(String(12), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    #: the Demo adapter did not know the recording and returned its scripted phrase
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audio_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_mime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    audio_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audio_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: what was sent (the edited final transcript) and the agents turn/run it became
    submitted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # a correction's ``corrects_turn_id`` lives on the agents turn (design section 4; Slice-3 stage-2 merge, 0020)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('received','transcribed','failed','submitted')", name="status_values"),
        CheckConstraint("source IN ('server','browser')", name="source_values"),
        CheckConstraint("audio_sha256 IS NULL OR audio_sha256 ~ '^[0-9a-f]{64}$'", name="audio_sha256_format"),
        CheckConstraint("duration_ms IS NULL OR duration_ms BETWEEN 0 AND 60000", name="duration_bounds"),
        Index("ix_voice_utterance_owner", "company_id", "user_id", "created_at"),
        Index("uq_voice_utterance_turn", "turn_id", unique=True, postgresql_where="turn_id IS NOT NULL"),
        Index("ix_voice_utterance_purge", "purge_at", postgresql_where="audio_key IS NOT NULL"),
    )


class VoiceSpeech(TenantEntity, Base):
    __tablename__ = "voice_speech"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False)
    #: the text is not stored (it may contain business values); its hash identifies repeats
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    audio_mime: Mapped[str] = mapped_column(String(40), nullable=False)
    audio_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    url_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audio_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_voice_speech_owner", "company_id", "user_id", "created_at"),
        Index("ix_voice_speech_purge", "purge_at", postgresql_where="audio_key IS NOT NULL"),
    )


class VoiceReadback(TenantEntity, Base):
    __tablename__ = "voice_readback"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: hash of the facts read back; a changed record needs a new read-back
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    presented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        Index("ix_voice_readback_subject", "company_id", "user_id", "subject_type", "subject_id", "presented_at"),
    )


__all__ = ["UtteranceSource", "UtteranceStatus", "VoiceReadback", "VoiceSpeech", "VoiceUtterance"]
