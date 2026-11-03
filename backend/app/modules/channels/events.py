"""Channel events (docs/architecture/events.md §3.8; definitions live in the frozen platform catalogue) and the
module's subscriptions: the assistant's finished runs become WhatsApp replies, identity deactivation and
credential changes revoke channel sessions, approval outcomes void armed buttons, and a web acknowledgement
voids the matching WhatsApp acknowledge button (``channels.ack_sync``)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.platform.events.defs import Subscription
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

IDENTITY_LINKED = "channels.identity.linked"
IDENTITY_REVOKED = "channels.identity.revoked"
IDENTITY_SUSPENDED = "channels.identity.suspended"
MESSAGE_RECEIVED = "channels.message.received"
MESSAGE_STATUS_CHANGED = "channels.message.status_changed"
MESSAGE_DELIVERY_UNKNOWN = "channels.message.delivery_unknown"
CONSENT_CHANGED = "channels.consent.changed"
ACCOUNT_VERIFIED = "channels.account.verified"
TEMPLATE_STATUS_CHANGED = "channels.template.status_changed"
CONVERSATION_ESCALATED = "channels.conversation.escalated"

JOB_INBOX_PROCESS = "wa.inbox.process"
JOB_OUTBOX_SEND = "wa.outbox.send"
JOB_OUTBOX_RECONCILE = "wa.outbox.reconcile"
JOB_TEMPLATES_SYNC = "wa.templates.sync"
JOB_QUEUE = "channels"

REPLY_HANDLER = "channels.reply_to_whatsapp"
REVOKE_HANDLER = "channels.revoke_on_deactivation"
ACTION_REF_HANDLER = "channels.void_action_refs"
ACK_HANDLER = "channels.ack_sync"

#: the proposal kind of an approved customer send (``prepare_quote_send``)
SEND_PROPOSAL_KIND = "channels.message.send"


class IdentityPayload(BaseModel):
    identity_id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None = None
    origin: str | None = None


class MessageReceivedPayload(BaseModel):
    message_id: uuid.UUID
    identity_id: uuid.UUID
    identity_kind: str
    type: str
    origin: str | None = None


class StatusChangedPayload(BaseModel):
    message_id: uuid.UUID
    outbox_id: uuid.UUID | None
    status: str
    simulated: bool
    origin: str | None = None


class DeliveryUnknownPayload(BaseModel):
    message_id: uuid.UUID
    outbox_id: uuid.UUID
    origin: str | None = None


class ConsentChangedPayload(BaseModel):
    identity_id: uuid.UUID
    purpose: str
    status: str
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=True)


def _uuid(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _reply(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.channels.whatsapp import replies

    run_id = _uuid((event.payload or {}).get("run_id")) or event.aggregate_id
    if run_id is not None:
        replies.reply_for_run(uow, run_id, failed=event.event_type.endswith(".failed"))


def _revoke(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.channels.whatsapp import identity as identities

    data = event.payload or {}
    user_id = _uuid(data.get("user_id"))
    if event.event_type == "identity.user.credentials_changed" and data.get("kind") == "password_changed":
        return  # a routine password change keeps the linked phone; resets and MFA resets revoke
    if user_id is not None:
        identities.revoke_for_user(uow, user_id, reason=event.event_type.rsplit(".", 1)[-1], event_id=event.id)


def _void_refs(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.channels import action_refs

    proposal_id = _uuid((event.payload or {}).get("proposal_id")) or event.aggregate_id
    if proposal_id is not None:
        action_refs.void_for_proposal(uow, proposal_id, reason=event.event_type.rsplit(".", 1)[-1])


def _ack_sync(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.channels import action_refs

    data = event.payload or {}
    briefing_id = _uuid(data.get("briefing_id")) or event.aggregate_id
    if briefing_id is not None and data.get("channel") != "whatsapp":
        action_refs.void_for_target(uow, "briefings.briefing", briefing_id, reason="acknowledged_elsewhere")


REVOKE_EVENTS = ("identity.membership.deactivated", "identity.user.credentials_changed")
ACTION_REF_EVENTS = (
    "approvals.proposal.approved", "approvals.proposal.rejected", "approvals.proposal.expired",
    "approvals.proposal.invalidated", "approvals.proposal.superseded", "approvals.proposal.cancelled",
)

SUBSCRIPTIONS: list[Subscription] = (
    [Subscription(event=name, handler_key=f"{REPLY_HANDLER}:{name}", handler=_reply, queue=JOB_QUEUE) for name in ("agents.run.completed", "agents.run.failed")]
    + [Subscription(event=name, handler_key=f"{REVOKE_HANDLER}:{name}", handler=_revoke) for name in REVOKE_EVENTS]
    + [Subscription(event=name, handler_key=f"{ACTION_REF_HANDLER}:{name}", handler=_void_refs) for name in ACTION_REF_EVENTS]
    + [Subscription(event="briefings.briefing.acknowledged", handler_key=f"{ACK_HANDLER}:briefings.briefing.acknowledged", handler=_ack_sync)]
)

__all__ = [
    "ACCOUNT_VERIFIED", "CONSENT_CHANGED", "CONVERSATION_ESCALATED", "IDENTITY_LINKED", "IDENTITY_REVOKED", "IDENTITY_SUSPENDED",
    "JOB_INBOX_PROCESS", "JOB_OUTBOX_RECONCILE", "JOB_OUTBOX_SEND", "JOB_QUEUE", "JOB_TEMPLATES_SYNC", "MESSAGE_DELIVERY_UNKNOWN",
    "MESSAGE_RECEIVED", "MESSAGE_STATUS_CHANGED", "SEND_PROPOSAL_KIND", "SUBSCRIPTIONS", "TEMPLATE_STATUS_CHANGED",
    "ConsentChangedPayload", "DeliveryUnknownPayload", "IdentityPayload", "MessageReceivedPayload", "StatusChangedPayload", "payload",
]
