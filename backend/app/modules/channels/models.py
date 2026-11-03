"""Channel tables (prefix ``channels_``): accounts, identities, enrolments, sessions, the webhook inbox and
rejections (RLS-exempt, no company context at ingress), inbound events, messages, status events, the outbox,
the append-only consent log, templates, review links and action refs (bound WhatsApp button nonces).

Enumerations are varchar + CHECK mirroring the StrEnums in ``schemas.py``; the lane contract test compares them.
``channels_message.body_encrypted`` holds the message text encrypted with the data-encryption key (``crypto.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, VersionMixin

ACCOUNT_PURPOSES = ("employee_assistant", "customer_service")
ACCOUNT_PROVIDERS = ("whatsapp_cloud", "demo")
ACCOUNT_MODES = ("demo", "live")
ACCOUNT_STATUSES = ("not_configured", "configured_unverified", "verified", "error", "disabled")
IDENTITY_KINDS = ("employee", "customer", "vendor", "unknown")
IDENTITY_STATUSES = ("pending", "active", "suspended", "revoked")
ENROLMENT_STATUSES = ("pending", "used", "expired", "cancelled")
INBOX_STATUSES = ("pending", "done", "failed", "ignored")
INBOUND_KINDS = ("message", "status", "template_status", "identity_change", "error")
INBOUND_STATUSES = ("pending", "done", "ignored", "failed", "pending_match")
DIRECTIONS = ("inbound", "outbound")
PROVENANCES = ("internal", "external")
MESSAGE_STATUSES = ("queued", "accepted", "sent", "delivered", "read", "played", "failed", "unknown", "blocked")
OUTBOX_KINDS = ("session", "interactive", "template", "media")
OUTBOX_STATES = ("pending", "sending", "accepted", "unknown", "failed", "blocked", "cancelled", "escalated")
CONSENT_PURPOSES = ("assistant_replies", "daily_briefing", "transactional", "marketing")
CONSENT_STATUSES = ("opted_in", "opted_out")
TEMPLATE_STATUSES = ("approved", "pending", "rejected", "paused", "disabled", "unknown")
REVIEW_PURPOSES = ("view", "decide")
ACTION_REF_ACTIONS = ("confirm", "approve", "reject", "choose_option", "open")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ChannelAccount(TenantEntity, VersionMixin, Base):
    __tablename__ = "channels_account"

    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="employee_assistant")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="demo")
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="demo")
    phone_number_id: Mapped[str] = mapped_column(String(64), nullable=False)
    waba_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_version: Mapped[str] = mapped_column(String(12), nullable=False, default="v26.0")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_configured")
    #: {graph_ok_at, handshake_ok_at, signed_event_ok_at} as RFC 3339 strings (None until the check passed)
    checks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("purpose", ACCOUNT_PURPOSES), name="purpose_values"),
        CheckConstraint(_in("provider", ACCOUNT_PROVIDERS), name="provider_values"),
        CheckConstraint(_in("mode", ACCOUNT_MODES), name="mode_values"),
        CheckConstraint(_in("status", ACCOUNT_STATUSES), name="status_values"),
        Index("uq_channels_account_phone", "company_id", "phone_number_id", unique=True),
    )


class ChannelIdentity(TenantEntity, VersionMixin, Base):
    __tablename__ = "channels_identity"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: business-scoped user id from Meta (preferred match key)
    bsuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wa_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: the employee's WhatsApp assistant conversation (agents module), created on the first text
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    #: when the last generic "not linked" reply went out (one per hour per unknown sender)
    last_generic_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("kind", IDENTITY_KINDS), name="kind_values"),
        CheckConstraint(_in("status", IDENTITY_STATUSES), name="status_values"),
        CheckConstraint(
            "(kind = 'employee' AND user_id IS NOT NULL AND party_id IS NULL) OR "
            "(kind IN ('customer','vendor') AND user_id IS NULL) OR kind = 'unknown'",
            name="kind_owner_consistency",
        ),
        Index("uq_channels_identity_bsuid", "account_id", "bsuid", unique=True, postgresql_where=text("bsuid IS NOT NULL")),
        Index("uq_channels_identity_wa_id", "account_id", "wa_id", unique=True, postgresql_where=text("wa_id IS NOT NULL")),
        Index("ix_channels_identity_user", "company_id", "user_id"),
    )


class ChannelEnrolment(TenantEntity, Base):
    __tablename__ = "channels_enrolment"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    identity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", ENROLMENT_STATUSES), name="status_values"),
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="attempts_bound"),
        Index("ix_channels_enrolment_open", "company_id", "account_id", "status", "expires_at"),
    )


class ChannelSession(TenantEntity, Base):
    __tablename__ = "channels_session"

    identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_identity.id", ondelete="RESTRICT"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (Index("ix_channels_session_identity", "identity_id", "revoked_at"),)


class WebhookInbox(IdMixin, Base):
    """Raw deliveries accepted by the webhook route (signature verified). No company at ingress, hence RLS-exempt;
    the worker resolves the company through ``channels_account.phone_number_id``."""

    __tablename__ = "channels_webhook_inbox"
    __tenant_rls__ = False

    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: payloads signed by the demo provider carry simulated statuses
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: raw payload purged after 30 days
    purge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_in("status", INBOX_STATUSES), name="status_values"),
        Index("ix_channels_webhook_inbox_status", "status", "received_at"),
    )


class WebhookRejection(IdMixin, Base):
    """A delivery refused for a missing or invalid signature: reason and hashes only, never the payload."""

    __tablename__ = "channels_webhook_rejection"
    __tenant_rls__ = False

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    remote_addr_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_channels_webhook_rejection_time", "received_at"),)


class InboundEvent(TenantEntity, Base):
    __tablename__ = "channels_inbound_event"

    inbox_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    #: wamid, or wamid:status:timestamp for statuses (replays collide and are ignored)
    provider_event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    identity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: the typed, validated event (message / status / template update) for retries and the trace
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("kind", INBOUND_KINDS), name="kind_values"),
        CheckConstraint(_in("status", INBOUND_STATUSES), name="status_values"),
        Index("uq_channels_inbound_event_key", "account_id", "provider_event_key", unique=True),
        Index("ix_channels_inbound_event_status", "company_id", "status", "provider_ts"),
    )


class ChannelMessage(TenantEntity, Base):
    __tablename__ = "channels_message"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_identity.id", ondelete="RESTRICT"), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    body_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    media_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    media_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reply_to_provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    inbound_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    status_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_provider_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: the agents input mode of the turn this message produced (wa_text, wa_voice, card_action)
    input_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``external`` for content from outside the company (customer messages, inbound media): never instructions
    provenance: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")

    __table_args__ = (
        CheckConstraint(_in("direction", DIRECTIONS), name="direction_values"),
        CheckConstraint(_in("provenance", PROVENANCES), name="provenance_values"),
        CheckConstraint(_in("status", MESSAGE_STATUSES), name="status_values"),
        Index("uq_channels_message_provider_id", "account_id", "provider_message_id", unique=True, postgresql_where=text("provider_message_id IS NOT NULL")),
        Index("ix_channels_message_identity", "identity_id", "created_at"),
        Index("ix_channels_message_run", "run_id"),
        Index("ix_channels_message_status", "company_id", "status", "created_at"),
    )


class MessageStatusEvent(IdMixin, TenantMixin, Base):
    """Every provider status ever received, kept in full (append-only); the message carries the highest rank."""

    __tablename__ = "channels_message_status_event"
    __append_only__ = True

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    errors: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    pricing: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    biz_opaque: Mapped[str | None] = mapped_column(String(200), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_channels_status_event", "account_id", "provider_message_id", "status", "provider_ts", unique=True),
        Index("ix_channels_status_event_message", "message_id"),
    )


class OutboxMessage(TenantEntity, VersionMixin, Base):
    __tablename__ = "channels_outbox_message"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_identity.id", ondelete="RESTRICT"), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="session")
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="assistant_replies")
    #: the provider-neutral content ({text} | {text, buttons[]} | {template, language, components} | {document...})
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    #: what caused the message (run id, briefing id, proposal id) for the trace
    cause_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: a resend creates a new row; this links back to the escalated original
    resend_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("kind", OUTBOX_KINDS), name="kind_values"),
        CheckConstraint(_in("state", OUTBOX_STATES), name="state_values"),
        CheckConstraint(_in("purpose", CONSENT_PURPOSES), name="purpose_values"),
        Index("uq_channels_outbox_idempotency", "company_id", "idempotency_key", unique=True),
        Index("ix_channels_outbox_claim", "state", "next_attempt_at"),
        Index("ix_channels_outbox_identity", "identity_id", "created_at"),
    )


class ChannelConsent(IdMixin, TenantMixin, Base):
    """Append-only consent log; the current status of a purpose is the latest row."""

    __tablename__ = "channels_consent"
    __append_only__ = True

    identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_identity.id", ondelete="RESTRICT"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(_in("purpose", CONSENT_PURPOSES), name="purpose_values"),
        CheckConstraint(_in("status", CONSENT_STATUSES), name="status_values"),
        Index("ix_channels_consent_identity", "identity_id", "purpose", "recorded_at"),
    )


class WaTemplate(TenantEntity, Base):
    __tablename__ = "channels_template"

    account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_account.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="UTILITY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    provider_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    components: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", TEMPLATE_STATUSES), name="status_values"),
        Index("uq_channels_template_name", "account_id", "name", "language", unique=True),
    )


class ReviewLink(TenantEntity, Base):
    __tablename__ = "channels_review_link"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    purpose: Mapped[str] = mapped_column(String(10), nullable=False, default="view")
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    redirect_path: Mapped[str] = mapped_column(String(300), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("purpose", REVIEW_PURPOSES), name="purpose_values"),
        Index("uq_channels_review_link_token", "token_hash", unique=True),
    )


class ActionRef(TenantEntity, Base):
    """A bound WhatsApp button: nonce -> (user, proposal, content hash, action). Consumed once; voided on unlink."""

    __tablename__ = "channels_action_ref"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("channels_identity.id", ondelete="RESTRICT"), nullable=False)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    option_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    outbound_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    armed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("action", ACTION_REF_ACTIONS), name="action_values"),
        Index("uq_channels_action_ref_nonce", "nonce", unique=True),
        Index("ix_channels_action_ref_identity", "identity_id", "consumed_at", "voided_at"),
    )


TENANT_TABLES = (
    "channels_account", "channels_identity", "channels_enrolment", "channels_session", "channels_inbound_event",
    "channels_message", "channels_message_status_event", "channels_outbox_message", "channels_consent",
    "channels_template", "channels_review_link", "channels_action_ref",
)
EXEMPT_TABLES = ("channels_webhook_inbox", "channels_webhook_rejection")
APPEND_ONLY_TABLES = ("channels_message_status_event", "channels_consent")

__all__ = [
    "APPEND_ONLY_TABLES", "EXEMPT_TABLES", "TENANT_TABLES", "ActionRef", "ChannelAccount", "ChannelConsent",
    "ChannelEnrolment", "ChannelIdentity", "ChannelMessage", "ChannelSession", "InboundEvent", "MessageStatusEvent",
    "OutboxMessage", "ReviewLink", "WaTemplate", "WebhookInbox", "WebhookRejection",
]
