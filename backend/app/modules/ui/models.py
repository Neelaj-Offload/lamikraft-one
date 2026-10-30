"""``ui_recent_record``: the records each user opened lately (newest ``RECENT_KEEP`` kept per user).

Written by ``POST /api/v1/ui/recent-records`` when a detail route opens; read by the ``ui.recent_record``
SourceReader (onboarding step "Open a product record") and, later, by the recents list of the shell.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin

RECENT_KEEP = 20


class RecentRecord(IdMixin, TenantMixin, Base):
    __tablename__ = "ui_recent_record"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    #: a registered resource type, e.g. "catalogue.product"
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_ui_recent_record_user_resource", "company_id", "user_id", "resource_type", "resource_id", unique=True),
        Index("ix_ui_recent_record_user_time", "company_id", "user_id", "opened_at"),
        CheckConstraint("resource_type ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'", name="resource_type_format"),
    )
