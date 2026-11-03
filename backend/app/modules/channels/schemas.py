"""Request and response models of the channels API (WhatsApp account, enrolment, identities, consents, messages,
outbox, templates, the demo simulator and review links). Enumerations mirror ``models.py`` CHECKs."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.http.capabilities import Capability


class AccountPurpose(StrEnum):
    EMPLOYEE_ASSISTANT = "employee_assistant"
    CUSTOMER_SERVICE = "customer_service"


class AccountProvider(StrEnum):
    WHATSAPP_CLOUD = "whatsapp_cloud"
    DEMO = "demo"


class AccountMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class AccountStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    VERIFIED = "verified"
    ERROR = "error"
    DISABLED = "disabled"


class IdentityKind(StrEnum):
    EMPLOYEE = "employee"
    CUSTOMER = "customer"
    VENDOR = "vendor"
    UNKNOWN = "unknown"


class IdentityStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class EnrolmentStatus(StrEnum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class InboxStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    IGNORED = "ignored"


class InboundKind(StrEnum):
    MESSAGE = "message"
    STATUS = "status"
    TEMPLATE_STATUS = "template_status"
    IDENTITY_CHANGE = "identity_change"
    ERROR = "error"


class InboundStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    IGNORED = "ignored"
    FAILED = "failed"
    PENDING_MATCH = "pending_match"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    ACCEPTED = "accepted"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    PLAYED = "played"
    FAILED = "failed"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class OutboxKind(StrEnum):
    SESSION = "session"
    INTERACTIVE = "interactive"
    TEMPLATE = "template"
    MEDIA = "media"


class OutboxState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    ACCEPTED = "accepted"
    UNKNOWN = "unknown"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


class ConsentPurpose(StrEnum):
    ASSISTANT_REPLIES = "assistant_replies"
    DAILY_BRIEFING = "daily_briefing"
    TRANSACTIONAL = "transactional"
    MARKETING = "marketing"


class ConsentStatus(StrEnum):
    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"


class TemplateStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    PAUSED = "paused"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class ReviewPurpose(StrEnum):
    VIEW = "view"
    DECIDE = "decide"


class ActionRefAction(StrEnum):
    CONFIRM = "confirm"
    APPROVE = "approve"
    REJECT = "reject"
    CHOOSE_OPTION = "choose_option"
    OPEN = "open"


#: proactive purposes need an explicit opt-in; replies to what the user started do not
PROACTIVE_PURPOSES = frozenset({ConsentPurpose.DAILY_BRIEFING, ConsentPurpose.MARKETING})

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


# ---- account -----------------------------------------------------------------------------------------------
class AccountChecks(BaseModel):
    graph_ok_at: datetime | None = None
    handshake_ok_at: datetime | None = None
    signed_event_ok_at: datetime | None = None


class AccountRead(BaseModel):
    id: uuid.UUID | None
    purpose: AccountPurpose
    provider: AccountProvider
    mode: AccountMode
    status: AccountStatus
    #: "Demo — not connected" in demo mode; "Connected" only after every check passed in live mode
    label_text: str
    phone_number_id: str | None
    waba_id: str | None
    display_phone: str | None
    api_version: str
    checks: AccountChecks
    missing_settings: list[str]
    live_outbound: bool
    last_error: str | None
    verified_at: datetime | None
    capabilities: dict[str, Capability]


class CheckResult(BaseModel):
    name: Literal["graph_api", "handshake", "signed_event"]
    ok: bool
    at: datetime | None
    detail: str | None


class VerifyResult(BaseModel):
    account: AccountRead
    checks: list[CheckResult]


# ---- enrolment and identities ------------------------------------------------------------------------------
class EnrolmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrolmentRead(BaseModel):
    id: uuid.UUID
    #: the one-time code, shown once (only its keyed hash is stored)
    code: str
    expires_at: datetime
    #: wa.me link prefilled with "LINK <code>" (None when the account has no display phone)
    wa_me_link: str | None
    message_text: str
    status: EnrolmentStatus
    mode: AccountMode


class IdentityRead(BaseModel):
    id: uuid.UUID
    kind: IdentityKind
    status: IdentityStatus
    wa_id_masked: str | None
    phone_masked: str | None
    username: str | None
    user_id: uuid.UUID | None
    user_name: str | None
    party_id: uuid.UUID | None
    last_inbound_at: datetime | None
    session_expires_at: datetime | None
    created_at: datetime
    consents: dict[str, ConsentStatus]
    capabilities: dict[str, Capability]


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: uuid.UUID
    purpose: ConsentPurpose
    status: ConsentStatus


class ConsentRead(BaseModel):
    identity_id: uuid.UUID
    purpose: ConsentPurpose
    status: ConsentStatus
    recorded_at: datetime
    source: str


# ---- messages and outbox -----------------------------------------------------------------------------------
class MessageRead(BaseModel):
    id: uuid.UUID
    identity_id: uuid.UUID
    direction: Direction
    type: str
    #: decrypted for callers who may read the message; None for media-only messages
    body: str | None
    status: MessageStatus
    status_provider_ts: datetime | None
    simulated: bool
    provider_message_id: str | None
    outbox_id: uuid.UUID | None
    outbox_state: OutboxState | None
    blocked_reason: str | None
    last_error: str | None
    created_at: datetime
    correlation_id: str | None
    buttons: list[dict[str, str]] = Field(default_factory=list)
    capabilities: dict[str, Capability] = Field(default_factory=dict)


class OutboxResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["resend", "cancel"]
    #: the person confirms a resend explicitly (a new message, never a replay)
    confirm: bool = False


class OutboxRead(BaseModel):
    id: uuid.UUID
    identity_id: uuid.UUID
    message_id: uuid.UUID | None
    kind: OutboxKind
    purpose: ConsentPurpose
    state: OutboxState
    attempts: int
    blocked_reason: str | None
    last_error: str | None
    provider_message_id: str | None
    sent_at: datetime | None
    escalated_at: datetime | None
    resend_of_id: uuid.UUID | None
    created_at: datetime


class TemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    language: str
    category: str
    status: TemplateStatus
    synced_at: datetime | None


# ---- demo simulator ----------------------------------------------------------------------------------------
class DemoInbound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)] | None = None
    #: an interactive button reply id (``a:<nonce>``) instead of text
    button_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    #: a voice note from the demo fixture set (``tests/fixtures/whatsapp/audio/<key>``)
    audio_fixture: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class DemoInboundResult(BaseModel):
    inbox_id: uuid.UUID
    identity_id: uuid.UUID | None
    processed: bool


class DemoThread(BaseModel):
    identity: IdentityRead | None
    messages: list[MessageRead]
    mode: AccountMode
    label_text: str
    wa_id_masked: str | None


# ---- review links ------------------------------------------------------------------------------------------
class ReviewLinkResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewLinkResolved(BaseModel):
    redirect_path: str
    target_type: str
    target_id: uuid.UUID
    proposal_id: uuid.UUID | None
    purpose: ReviewPurpose


class ReviewLinkOut(BaseModel):
    url_path: str
    expires_at: datetime
    purpose: ReviewPurpose


__all__ = [n for n in dir() if n[:1].isupper()]
