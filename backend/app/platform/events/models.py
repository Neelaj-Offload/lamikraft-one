"""Transactional outbox. Events are written in the same transaction as the change they describe.

Payloads hold references and changed-field names only — never restricted values, secrets or
personal message content. ``domain_event`` is platform-internal (the relay is cross-tenant).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin


class DomainEvent(IdMixin, Base):
    __tablename__ = "domain_event"
    __tenant_rls__ = False
    __append_only__ = False  # dispatched_at is updated by the relay

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    aggregate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_domain_event_undispatched", "seq", postgresql_where=text("dispatched_at IS NULL")),
        Index("ix_domain_event_aggregate", "company_id", "aggregate_type", "aggregate_id", "seq"),
        Index("ix_domain_event_type_time", "company_id", "event_type", "occurred_at"),
    )


class EventConsumption(Base):
    """Exactly-once marker for handlers reachable by more than one path (``consumers.once``)."""

    __tablename__ = "event_consumption"
    __tenant_rls__ = False

    consumer: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
