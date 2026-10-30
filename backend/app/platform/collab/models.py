"""``note`` and ``attachment``. ``note``: the only store for record-level internal notes (ADR-038).

One autosaved internal note per (resource_type, resource_id). The note is a polymorphic child: it is
authorised only through the parent's ResourcePolicy (read to view, update to write).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
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


ATTACHMENT_TITLE_MAX = 200


class Attachment(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    """A file attached to any record (polymorphic child, authorised only through the parent's policy).

    Reading needs the parent's ``read``; attaching, renaming and removing need the parent's ``update``. Removal
    archives the row (the file object stays for other references and for history).
    """

    __tablename__ = "attachment"

    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_object.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(ATTACHMENT_TITLE_MAX), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("ix_attachment_resource", "company_id", "resource_type", "resource_id", "created_at"),
        Index("ix_attachment_file", "company_id", "file_id"),
        Index(
            "uq_attachment_open_file",
            "company_id",
            "resource_type",
            "resource_id",
            "file_id",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("role IN ('general','document','image')", name="role_values"),
        CheckConstraint("length(btrim(title)) > 0", name="title_present"),
    )
