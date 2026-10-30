"""Authentication state: sessions, attempts, rate-limit counters and one-time demo sign-in tokens.

``auth_session``, ``auth_attempt`` and ``rate_limit_counter`` are RLS-exempt platform tables (conventions §3):
they are read before a tenant is known and only by identity code with explicit filters. Only hashes of
secrets are stored (session token, CSRF secret, demo token; IP and user agent as keyed HMACs).
``demo_sign_in_token`` is tenant-scoped: the token text carries its company id so the public endpoint
can bind the tenant before looking the hash up under RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin
from app.platform.identity.models import in_values


class SessionStage(StrEnum):
    ACTIVE = "active"
    MFA_PENDING = "mfa_pending"
    MFA_ENROLLMENT_REQUIRED = "mfa_enrollment_required"


class AuthMethod(StrEnum):
    PASSWORD = "password"  # noqa: S105 - an enum label, not a credential
    DEMO_LINK = "demo_link"
    TEST_SUPPORT = "test_support"


class AttemptKind(StrEnum):
    LOGIN = "login"
    DEMO_SIGN_IN = "demo_sign_in"
    TEST_SIGN_IN = "test_sign_in"
    MFA = "mfa"
    REAUTH = "reauth"
    INVITE_ACCEPT = "invite_accept"
    RESET_REQUEST = "reset_request"
    RESET_COMPLETE = "reset_complete"


class AttemptOutcome(StrEnum):
    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    RATE_LIMITED = "rate_limited"
    ACCOUNT_LOCKED = "account_locked"
    LINK_INVALID = "link_invalid_or_used"
    INVALID_CODE = "invalid_code"


class DemoTokenSource(StrEnum):
    CLI = "cli"
    SEED = "seed"
    TEST_SUPPORT = "test_support"


class AuthSession(IdMixin, Base):
    __tablename__ = "auth_session"
    __tenant_rls__ = False

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=True
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default=SessionStage.ACTIVE.value)
    auth_method: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recent_auth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: set when this session passed a TOTP or recovery-code check (sign-in, enrolment or step-up)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: wrong codes entered while ``mfa_pending``; the session is revoked after five
    mfa_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("auth_session.id", ondelete="SET NULL"), nullable=True
    )
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    user_agent_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)

    __table_args__ = (
        Index("uq_auth_session_token_hash", "token_hash", unique=True),
        Index("ix_auth_session_user_open", "user_id", postgresql_where=text("revoked_at IS NULL")),
        Index("ix_auth_session_absolute_expires", "absolute_expires_at"),
        CheckConstraint(in_values("stage", SessionStage), name="stage_values"),
        CheckConstraint(in_values("auth_method", AuthMethod), name="auth_method_values"),
        CheckConstraint("absolute_expires_at > created_at", name="expiry_after_creation"),
    )


class AuthAttempt(IdMixin, Base):
    __tablename__ = "auth_attempt"
    __tenant_rls__ = False

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    email_hmac: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_auth_attempt_email_time", "email_hmac", "occurred_at"),
        Index("ix_auth_attempt_ip_time", "ip_hash", "occurred_at"),
        CheckConstraint(in_values("kind", AttemptKind), name="kind_values"),
        CheckConstraint(in_values("outcome", AttemptOutcome), name="outcome_values"),
    )


class RateLimitCounter(Base):
    """Fixed-window counters (``count``) and lockout state (``blocked_until`` with exponential ``lock_count``)."""

    __tablename__ = "rate_limit_counter"
    __tenant_rls__ = False

    bucket_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_rate_limit_counter_expires", "expires_at"),
        CheckConstraint("count >= 0 AND lock_count >= 0", name="counts_non_negative"),
    )


class DemoSignInToken(IdMixin, TenantMixin, Base):
    __tablename__ = "demo_sign_in_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    issued_via: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("auth_session.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_demo_sign_in_token_hash", "token_hash", unique=True),
        Index("ix_demo_sign_in_token_user", "company_id", "user_id"),
        CheckConstraint(in_values("issued_via", DemoTokenSource), name="issued_via_values"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )
