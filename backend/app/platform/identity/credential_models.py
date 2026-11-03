"""Credentials beyond the password: TOTP factors, recovery codes, invitations and password resets.

- ``mfa_factor`` and ``mfa_recovery_code`` are user-level (RLS-exempt, like ``app_user``): a person has one
  authenticator whatever company they sign in to. The TOTP seed is AES-GCM encrypted (``identity.crypto``);
  recovery codes are stored as keyed HMACs and shown once.
- ``invitation`` is tenant-scoped. Its token is ``<company hex>.<secret>`` so the public accept endpoint can bind
  the tenant before looking up the hash under RLS (the same scheme as demo sign-in links).
- ``password_reset`` is user-level (RLS-exempt): a reset changes the person's one password.

Only SHA-256 hashes of link tokens are stored; tokens travel in URL fragments (``/invite#t=…``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin
from app.platform.identity.models import in_values


class FactorKind(StrEnum):
    TOTP = "totp"


class InvitationDelivery(StrEnum):
    EMAIL = "email"
    DEMO_OUTBOX = "demo_outbox"


class ResetKind(StrEnum):
    SELF_SERVICE = "self_service"
    ADMIN_ISSUED = "admin_issued"


class MfaFactor(IdMixin, Base):
    __tablename__ = "mfa_factor"
    __tenant_rls__ = False

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default=FactorKind.TOTP.value)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="Authenticator app")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: the last 30-second step accepted; a code from that step or an earlier one is a replay
    last_used_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    disabled_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("uq_mfa_factor_user_open", "user_id", unique=True, postgresql_where=text("disabled_at IS NULL")),
        CheckConstraint(in_values("kind", FactorKind), name="kind_values"),
    )


class MfaRecoveryCode(IdMixin, Base):
    __tablename__ = "mfa_recovery_code"
    __tenant_rls__ = False

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    factor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mfa_factor.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_mfa_recovery_code_factor", "factor_id"),
        Index("uq_mfa_recovery_code_hash", "user_id", "code_hash", unique=True),
    )


class Invitation(IdMixin, TenantMixin, Base):
    __tablename__ = "invitation"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    email_normalized: Mapped[str] = mapped_column(String(254), nullable=False)
    token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    delivery: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("uq_invitation_token_hash", "token_hash", unique=True),
        Index(
            "uq_invitation_open_membership",
            "company_id",
            "membership_id",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("ix_invitation_membership", "company_id", "membership_id", "created_at"),
        CheckConstraint(in_values("delivery", InvitationDelivery), name="delivery_values"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )


class PasswordReset(IdMixin, Base):
    __tablename__ = "password_reset"
    __tenant_rls__ = False

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    #: the company whose admin issued it, or the requester's home company (audit context)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_password_reset_token_hash", "token_hash", unique=True),
        Index("ix_password_reset_user_open", "user_id", postgresql_where=text("used_at IS NULL AND revoked_at IS NULL")),
        CheckConstraint(in_values("kind", ResetKind), name="kind_values"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )
