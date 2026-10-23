"""``search_recent``: the last searches of each user (ADR-041 keeps the newest 10 per user)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin

RECENT_KEEP = 10
QUERY_MAX_CHARS = 200


class SearchRecent(IdMixin, TenantMixin, Base):
    __tablename__ = "search_recent"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    query: Mapped[str] = mapped_column(String(QUERY_MAX_CHARS), nullable=False)
    #: normalised form (case/space/diacritic folded) so repeated searches move to the top instead of duplicating
    normalized_query: Mapped[str] = mapped_column(String(QUERY_MAX_CHARS), nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_search_recent_user_query", "company_id", "user_id", "normalized_query", unique=True),
        Index("ix_search_recent_user_time", "company_id", "user_id", "searched_at"),
    )
