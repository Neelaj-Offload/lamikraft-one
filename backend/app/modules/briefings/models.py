"""Briefing tables: one briefing per user and work date, immutable versions and items (copy-on-write),
recommendations, per-user item states, acknowledgements and voice/chat pins.

A version is written only when the visible item set or an item fingerprint changes (no manufactured
updates). Versions and items are append-only; acknowledgements are monotonic per user.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


class BriefingStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class BriefingTrigger(StrEnum):
    FIRST_OPEN = "first_open"
    PRECOMPUTE = "precompute"
    WHATSAPP = "whatsapp"
    AGENT = "agent"
    SEED = "seed"


class DayType(StrEnum):
    WORKING = "working"
    NON_WORKING = "non_working"
    HOLIDAY = "holiday"
    LEAVE = "leave"


class VersionCause(StrEnum):
    INITIAL = "initial"
    EVENT_UPDATE = "event_update"
    PERMISSION_CHANGE = "permission_change"
    MANUAL_REFRESH = "manual_refresh"


class Section(StrEnum):
    NEEDS_YOU_NOW = "needs_you_now"
    PLAN_FOR_TODAY = "plan_for_today"
    CHANGES_SINCE_LAST_VISIT = "changes_since_last_visit"
    RECOMMENDATIONS = "recommendations"
    HANDLED_FOR_YOU = "handled_for_you"
    COMING_NEXT = "coming_next"


class Band(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ChangeKind(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class RecommendationStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class AckMethod(StrEnum):
    VIEWED = "viewed"
    EXPLICIT = "explicit"
    VOICE = "voice"
    WHATSAPP = "whatsapp"


class PinKind(StrEnum):
    VOICE = "voice"
    CHAT = "chat"


class PinState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    EXPIRED = "expired"


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{e.value}'" for e in enum)


class Briefing(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "briefings_briefing"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_type: Mapped[str] = mapped_column(String(20), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BriefingStatus.GENERATING.value)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: highest version served as "the latest" to this user (for the "N updates" signal)
    served_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: generation failures since the last successful build (repeated failures open an admin obligation)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: the permission fingerprint the latest version's visible content was last verified against. A
    #: permission change that leaves the visible item set unchanged updates this, not the version.
    permission_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("uq_briefings_briefing_user_date", "company_id", "user_id", "work_date", unique=True),
        Index("ix_briefings_briefing_date", "company_id", "work_date", "status"),
        CheckConstraint(f"status IN ({_values(BriefingStatus)})", name="status_values"),
        CheckConstraint(f"trigger IN ({_values(BriefingTrigger)})", name="trigger_values"),
        CheckConstraint(f"day_type IN ({_values(DayType)})", name="day_type_values"),
        CheckConstraint("current_version >= 0 AND served_version >= 0", name="versions_non_negative"),
        CheckConstraint("consecutive_failures >= 0", name="failures_non_negative"),
    )


class BriefingVersion(IdMixin, TenantMixin, Base):
    """Immutable snapshot header."""

    __tablename__ = "briefings_version"
    __append_only__ = True

    briefing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("briefings_briefing.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    cause: Mapped[str] = mapped_column(String(30), nullable=False)
    cause_event_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: the change-log cutoff used for "Changes since your last visit"
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    permission_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    priority_rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    overview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sections: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    initial_issue_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    item_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    partial_families: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("uq_briefings_version", "briefing_id", "version", unique=True),
        CheckConstraint(f"cause IN ({_values(VersionCause)})", name="cause_values"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class BriefingItem(IdMixin, TenantMixin, Base):
    """One issue in one version (immutable; unchanged items are copied into later versions)."""

    __tablename__ = "briefings_item"
    __append_only__ = True

    briefing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("briefings_briefing.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("briefings_version.id"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    section: Mapped[str] = mapped_column(String(40), nullable=False)
    display_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String(2), nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason_codes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    family: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    fact_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    task_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    recommendation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    uncertainty_flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    allowed_actions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    proposal_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    blocked_by: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    members: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_since_last_visit: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_reminder: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        Index("uq_briefings_item_version_issue", "version_id", "issue_id", unique=True),
        Index("ix_briefings_item_issue", "company_id", "issue_id"),
        Index("ix_briefings_item_briefing", "briefing_id", "issue_id"),
        CheckConstraint(f"section IN ({_values(Section)})", name="section_values"),
        CheckConstraint(f"band IN ({_values(Band)})", name="band_values"),
        CheckConstraint(f"change_kind IN ({_values(ChangeKind)})", name="change_kind_values"),
        CheckConstraint("display_ordinal >= 1", name="ordinal_positive"),
    )


class Recommendation(IdMixin, TenantMixin, Base):
    """A rule-derived recommendation bound to the issue fingerprint it was computed from."""

    __tablename__ = "briefings_recommendation"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    effect_code: Mapped[str] = mapped_column(String(60), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    alternatives: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    based_on_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RecommendationStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_briefings_recommendation_active",
            "company_id",
            "user_id",
            "issue_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        CheckConstraint(f"status IN ({_values(RecommendationStatus)})", name="status_values"),
        CheckConstraint("status = 'active' OR invalidated_at IS NOT NULL", name="inactive_has_time"),
    )


class ItemState(IdMixin, TenantMixin, VersionMixin, Base):
    """Per-user state of an issue across versions: acknowledged fingerprint, handled, dismissed."""

    __tablename__ = "briefings_item_state"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    acked_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acked_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_task_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissal_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("uq_briefings_item_state_user_issue", "company_id", "user_id", "issue_id", unique=True),)


class Acknowledgement(IdMixin, TenantMixin, Base):
    __tablename__ = "briefings_acknowledgement"
    __append_only__ = True

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    briefing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("briefings_briefing.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_briefings_ack_user_time", "company_id", "user_id", "acknowledged_at"),
        Index("uq_briefings_ack_briefing_version", "briefing_id", "version", unique=True),
        Index(
            "uq_briefings_ack_channel_message",
            "company_id",
            "user_id",
            "channel_message_id",
            unique=True,
            postgresql_where="channel_message_id IS NOT NULL",
        ),
        CheckConstraint(f"method IN ({_values(AckMethod)})", name="method_values"),
    )


class Pin(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    """A pinned version for an active voice/chat session: stable ordinals, no re-sorting."""

    __tablename__ = "briefings_pin"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    briefing_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("briefings_briefing.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    pinned_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal_map: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=PinState.ACTIVE.value)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_briefings_pin_live",
            "company_id",
            "user_id",
            "kind",
            unique=True,
            postgresql_where="state IN ('active','paused')",
        ),
        CheckConstraint(f"kind IN ({_values(PinKind)})", name="kind_values"),
        CheckConstraint(f"state IN ({_values(PinState)})", name="state_values"),
        CheckConstraint("position >= 0", name="position_non_negative"),
    )


__all__ = [
    "AckMethod",
    "Acknowledgement",
    "Band",
    "Briefing",
    "BriefingItem",
    "BriefingStatus",
    "BriefingTrigger",
    "BriefingVersion",
    "ChangeKind",
    "DayType",
    "ItemState",
    "Pin",
    "PinKind",
    "PinState",
    "Recommendation",
    "RecommendationStatus",
    "Section",
    "VersionCause",
]
