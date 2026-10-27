"""``integration_status``: the single truthful state of every external integration (ADR-040).

``connected`` is written only by a verification routine (``system.service.run_verification``); no API
sets it directly. Rows exist only once a verification ran; until then the configured mode is reported with
the state ``not_connected``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin, enum_column


class IntegrationMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class IntegrationState(StrEnum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    ERROR = "error"


class IntegrationStatus(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "integration_status"

    integration_key: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = enum_column(IntegrationMode, length=10)
    state: Mapped[str] = enum_column(IntegrationState, length=20)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: sanitised, non-secret facts from the verification (e.g. account display name, API version)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("uq_integration_status_key", "company_id", "integration_key", unique=True),
        CheckConstraint("mode IN ('demo','live')", name="mode_values"),
        CheckConstraint("state IN ('not_connected','connected','error')", name="state_values"),
        CheckConstraint("state <> 'connected' OR verified_at IS NOT NULL", name="connected_requires_verification"),
    )
