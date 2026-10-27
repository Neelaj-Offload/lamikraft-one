"""Versioned commercial rule sets (``quote_commercial`` v1, ...). One active version per code."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, TenantEntity, VersionMixin


class RuleSet(TenantEntity, VersionMixin, Base):
    __tablename__ = "commercial_rule_set"

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    #: validated by ``schemas.QuoteCommercialRulesV1`` on write (decimal strings, never floats)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "code", "version_no", name="uq_commercial_rule_set_version"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
    )


#: one active version per code
Index(
    "uq_commercial_rule_set_one_active",
    RuleSet.company_id,
    RuleSet.code,
    unique=True,
    postgresql_where=RuleSet.status == "active",
)

__all__ = ["RuleSet"]
