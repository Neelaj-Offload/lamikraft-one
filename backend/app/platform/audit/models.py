"""Append-only audit log (a trigger rejects UPDATE/DELETE; lk_app holds INSERT/SELECT only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin


class AuditLog(IdMixin, TenantMixin, Base):
    __tablename__ = "audit_log"
    __append_only__ = True

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    on_behalf_of_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    resource_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False, default="success")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    restricted_fields: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint("outcome IN ('success','denied','failed')", name="outcome_values"),
        Index("ix_audit_resource", "company_id", "resource_type", "resource_id", "occurred_at"),
        Index("ix_audit_actor", "company_id", "actor_user_id", "occurred_at"),
        Index("ix_audit_action", "company_id", "action", "occurred_at"),
        Index("ix_audit_log_keyset", "company_id", "occurred_at", "id"),
    )
