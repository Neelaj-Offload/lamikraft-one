"""Company and branch: the tenancy boundary. ``company`` itself is RLS-exempt (platform-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, IdMixin, TimestampMixin


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "company"
    __tenant_rls__ = False

    company_key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    default_time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-IN")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    authz_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("company_key ~ '^[a-z][a-z0-9-]{1,39}$'", name="company_key_format"),
        CheckConstraint("status IN ('active','suspended')", name="status_values"),
    )


class Branch(IdMixin, TimestampMixin, ArchivableMixin, Base):
    __tablename__ = "branch"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_head_office: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("uq_branch_company_code", "company_id", "branch_code", unique=True),
        Index(
            "uq_branch_one_head_office",
            "company_id",
            unique=True,
            postgresql_where=text("is_head_office AND archived_at IS NULL"),
        ),
        CheckConstraint("gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'", name="gstin_format"),
    )


__all__ = ["Branch", "Company", "datetime"]
