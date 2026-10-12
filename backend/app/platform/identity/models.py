"""Core identity tables. ``app_user`` is global (RLS-exempt); memberships are tenant-scoped.

Users are never hard-deleted so historical attribution survives. A ``historical`` user has no
credentials and represents a legacy person migrated only for attribution.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


class AppUser(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "app_user"
    __tenant_rls__ = False

    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(254), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-IN")
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_app_user_email_normalized", "email_normalized", unique=True),
        CheckConstraint("status IN ('invited','active','disabled','historical')", name="status_values"),
        CheckConstraint("status <> 'historical' OR password_hash IS NULL", name="historical_no_credentials"),
    )


class Membership(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "membership"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    employee_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(80), nullable=True)
    manager_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=True
    )
    default_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    work_time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("uq_membership_company_user", "company_id", "user_id", unique=True),
        Index(
            "uq_membership_employee_code",
            "company_id",
            "employee_code",
            unique=True,
            postgresql_where="employee_code IS NOT NULL",
        ),
        CheckConstraint("status IN ('invited','active','suspended','deactivated')", name="status_values"),
    )
