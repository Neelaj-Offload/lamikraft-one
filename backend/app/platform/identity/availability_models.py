"""Delegation, leave (absence) and access requests: time-bounded, audited changes to who acts on what.

- ``delegation``: a delegator hands record reach for some delegable keys to a delegate for at most 90 days.
  It never adds permission keys: the delegate must already hold each key (permissions.md §10).
- ``user_absence``: leave and other absences (no medical detail). Approved absences drive owner-reassignment
  hints for the Inbox and briefings through ``identity.absence.*`` events and the ``identity.absence`` reader.
- ``access_request``: a member asks for a permission; an approver with ``identity.access_request.approve`` grants
  it as an expiring per-user override (or rejects it with a note).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ActorStampMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin
from app.platform.identity.models import ScopeLabel, in_values

MAX_DELEGATION_DAYS = 90


class DelegationReason(StrEnum):
    LEAVE = "leave"
    TRAVEL = "travel"
    WORKLOAD = "workload"
    OTHER = "other"


class AbsenceKind(StrEnum):
    LEAVE = "leave"
    HOLIDAY = "holiday"
    TRAINING = "training"
    OTHER = "other"


class AbsenceStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class AccessRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Delegation(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    __tablename__ = "delegation"

    delegator_membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    delegate_membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    permission_keys: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False)
    include_approvals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    #: set by the boundary job when ``identity.delegation.started`` / ``.ended`` was emitted
    started_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_delegation_delegate_window", "company_id", "delegate_membership_id", "starts_at", "ends_at"),
        Index("ix_delegation_delegator", "company_id", "delegator_membership_id", "starts_at"),
        CheckConstraint("delegator_membership_id <> delegate_membership_id", name="not_self"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint(f"ends_at - starts_at <= interval '{MAX_DELEGATION_DAYS} days'", name="max_duration"),
        CheckConstraint("cardinality(permission_keys) > 0", name="has_keys"),
        CheckConstraint(in_values("reason", DelegationReason), name="reason_values"),
    )


class UserAbsence(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    __tablename__ = "user_absence"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AbsenceStatus.REQUESTED.value)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: who should pick up the member's open work while away (a hint for the Inbox and briefings)
    cover_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_user_absence_member_dates", "company_id", "membership_id", "starts_on", "ends_on"),
        CheckConstraint("ends_on >= starts_on", name="ends_on_after_start"),
        CheckConstraint("cover_membership_id IS NULL OR cover_membership_id <> membership_id", name="cover_not_self"),
        CheckConstraint(in_values("kind", AbsenceKind), name="kind_values"),
        CheckConstraint(in_values("status", AbsenceStatus), name="status_values"),
    )


class AccessRequest(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    __tablename__ = "access_request"

    requester_membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    permission_key: Mapped[str] = mapped_column(
        String(120), ForeignKey("permission.key", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    #: requested length of the grant; the approver may shorten it
    duration_days: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AccessRequestStatus.PENDING.value)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    grant_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_permission_override.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("ix_access_request_status", "company_id", "status", "created_at"),
        Index("ix_access_request_requester", "company_id", "requester_membership_id", "created_at"),
        CheckConstraint(in_values("status", AccessRequestStatus), name="status_values"),
        CheckConstraint(in_values("scope", ScopeLabel), name="scope_values"),
        CheckConstraint("duration_days BETWEEN 1 AND 90", name="duration_range"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_present"),
    )
