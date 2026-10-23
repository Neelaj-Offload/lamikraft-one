"""``note``: the only store for record-level internal notes (ADR-038).

One autosaved internal note per (resource_type, resource_id). The note is a polymorphic child: it is
authorised only through the parent's ResourcePolicy (read to view, update to write).
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ActorStampMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin

NOTE_MAX_CHARS = 20_000


class Note(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    __tablename__ = "note"

    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("uq_note_resource", "company_id", "resource_type", "resource_id", unique=True),
        CheckConstraint(f"char_length(body) <= {NOTE_MAX_CHARS}", name="body_length"),
    )
