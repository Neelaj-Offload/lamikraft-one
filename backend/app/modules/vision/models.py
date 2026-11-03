"""Vision tables (prefix ``vision_``): masked screen captures and vision requests.

- ``vision_capture``: one masked screenshot per (conversation, SHA-256) while attached; the bytes live in a
  ``file_object`` (purpose ``screen_capture``, ``restricted``) and are purged with the row's file after 24 hours.
- ``vision_request``: one row per instant answer or extraction. The AI call log row (``agents_ai_call_log``) holds
  usage only; this row references the image by SHA-256 and carries the structured result (extraction fields with
  confidences, the confirmed values once the person confirms). Vision output is untrusted (``provenance=external``).

Both are tenant tables with forced fail-closed RLS; every read is additionally filtered by the owner (a capture or
request of another user is a 404).
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


class CaptureStatus(StrEnum):
    ATTACHED = "attached"
    REMOVED = "removed"
    PURGED = "purged"


class RequestKind(StrEnum):
    SCREEN_ANSWER = "screen_answer"
    EXTRACTION = "extraction"


class RequestStatus(StrEnum):
    ANSWERED = "answered"
    HANDED_OFF = "handed_off"
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    UNAVAILABLE = "unavailable"


class ExtractionKindValue(StrEnum):
    PURCHASE_ORDER = "purchase_order"
    BILL = "bill"
    DELIVERY_NOTE = "delivery_note"
    HANDWRITTEN_LIST = "handwritten_list"


class VisionCapture(TenantEntity, Base):
    __tablename__ = "vision_capture"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    #: the assistant conversation the capture belongs to (dedupe scope); None before the first turn
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_object.id", ondelete="SET NULL"), nullable=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    #: elements replaced by opaque blocks on the client (data-restricted, password, data-private)
    masked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CaptureStatus.ATTACHED.value)
    purge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('attached','removed','purged')", name="status_values"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        # uq_vision_capture_conversation_sha (company, user, coalesce(conversation, nil uuid), sha256) WHERE status <>
        # 'purged' is an expression index: it lives in migration 0019 only (no raw SQL in module code)
        Index("ix_vision_capture_purge", "purge_at", postgresql_where="status <> 'purged'"),
    )


class VisionRequest(TenantEntity, VersionMixin, Base):
    __tablename__ = "vision_request"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    extraction_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vision_capture.id", ondelete="SET NULL"), nullable=True
    )
    #: the uploaded photo or document an extraction read (the user's own file)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_object.id", ondelete="SET NULL"), nullable=True
    )
    #: the image is referenced by hash only (never its bytes, never a path)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: screen answer {text, handoff, reason, confidence} or extraction {header, lines} with confidences
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: values the person confirmed (only these may reach tools or forms)
    confirmed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: always true: vision output is external content (ai-routing.md section 6)
    tainted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    call_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("kind IN ('screen_answer','extraction')", name="kind_values"),
        CheckConstraint(
            "status IN ('answered','handed_off','extracted','confirmed','unavailable')", name="status_values"
        ),
        CheckConstraint(
            "extraction_kind IS NULL OR extraction_kind IN ('purchase_order','bill','delivery_note','handwritten_list')",
            name="extraction_kind_values",
        ),
        CheckConstraint("tainted", name="always_tainted"),
        Index("ix_vision_request_owner", "company_id", "user_id", "created_at"),
    )


__all__ = ["CaptureStatus", "ExtractionKindValue", "RequestKind", "RequestStatus", "VisionCapture", "VisionRequest"]
