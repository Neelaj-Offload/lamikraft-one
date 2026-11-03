"""Channels API services: identities (own, or every identity with ``channels.identity.manage``), revocation,
consent switches, the admin message list (unknown / failed / blocked) and outbox resolution, and the demo
simulator (inbound from the user's demo number through the real signed webhook ingest, and the thread view)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.modules.channels import crypto
from app.modules.channels.models import ChannelIdentity, ChannelMessage, ChannelSession, OutboxMessage
from app.modules.channels.policies import CONSENT_UPDATE, IDENTITY_MANAGE, OUTBOX_MANAGE
from app.modules.channels.schemas import (
    PROACTIVE_PURPOSES,
    ConsentRead,
    ConsentUpdate,
    DemoInbound,
    DemoInboundResult,
    DemoThread,
    IdentityRead,
    MessageRead,
    OutboxRead,
    OutboxResolve,
)
from app.modules.channels.whatsapp import accounts, consent, outbound
from app.modules.channels.whatsapp import identity as identities
from app.platform.uow import UnitOfWork

ASSISTANT_USE = "agents.assistant.use"
ADMIN_STATES = ("unknown", "failed", "blocked", "escalated")


def _cap(allowed: bool, reason: str | None = "permission_denied") -> Capability:
    return Capability(allowed=allowed, reason_code=None if allowed else reason)


def _require_user(uow: UnitOfWork) -> uuid.UUID:
    if uow.actor.user_id is None or uow.actor.is_system:
        raise Forbidden(code="permission_denied")
    return uow.actor.user_id


def _session_expiry(uow: UnitOfWork, identity: ChannelIdentity) -> Any:
    session = identities.active_session(uow, identity, uow.now())
    if session is None:
        return None
    return min(session.idle_expires_at, session.absolute_expires_at)


def identity_read(uow: UnitOfWork, identity: ChannelIdentity) -> IdentityRead:
    from app.platform.identity.models import AppUser

    user = uow.session.get(AppUser, identity.user_id) if identity.user_id else None
    own = identity.user_id is not None and identity.user_id == uow.actor.user_id
    manage = uow.actor.can(IDENTITY_MANAGE)
    revocable = identity.status in ("active", "pending", "suspended") and (own or manage)
    return IdentityRead(
        id=identity.id, kind=identity.kind, status=identity.status, wa_id_masked=identities.mask(identity.wa_id),  # type: ignore[arg-type]
        phone_masked=identities.mask(identity.phone_e164), username=identity.username, user_id=identity.user_id,
        user_name=user.display_name if user else None, party_id=identity.party_id, last_inbound_at=identity.last_inbound_at,
        session_expires_at=_session_expiry(uow, identity), created_at=identity.created_at,
        consents=consent.current(uow, identity.id),  # type: ignore[arg-type]
        capabilities={
            "revoke": _cap(revocable, "permission_denied" if not (own or manage) else "not_active"),
            "update_consent": _cap((own or uow.actor.can(CONSENT_UPDATE)) and identity.status == "active",
                                   "not_active" if identity.status != "active" else "permission_denied"),
        },
    )


def list_identities(uow: UnitOfWork, *, scope: str = "mine") -> list[IdentityRead]:
    user_id = _require_user(uow)
    account = accounts.ensure_account(uow)
    stmt = select(ChannelIdentity).where(ChannelIdentity.company_id == uow.actor.company_id, ChannelIdentity.account_id == account.id)
    if scope == "all":
        uow.actor.require(IDENTITY_MANAGE)
        stmt = stmt.where(ChannelIdentity.kind == "employee")
    else:
        stmt = stmt.where(ChannelIdentity.user_id == user_id)
    rows = uow.session.scalars(stmt.order_by(ChannelIdentity.created_at.desc()).limit(200))
    return [identity_read(uow, r) for r in rows]


def _visible_identity(uow: UnitOfWork, identity_id: uuid.UUID, *, for_update: bool = False) -> ChannelIdentity:
    user_id = _require_user(uow)
    stmt = select(ChannelIdentity).where(ChannelIdentity.company_id == uow.actor.company_id, ChannelIdentity.id == identity_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None or (row.user_id != user_id and not uow.actor.can(IDENTITY_MANAGE)):
        raise NotFound(code="not_found", resource_type="channels.identity")
    return row


def revoke(uow: UnitOfWork, identity_id: uuid.UUID) -> None:
    identity = _visible_identity(uow, identity_id, for_update=True)
    if identity.status == "revoked":
        return
    reason = "unlinked_by_user" if identity.user_id == uow.actor.user_id else "unlinked_by_admin"
    identities.revoke_identity(uow, identity, reason=reason)


def update_consent(uow: UnitOfWork, data: ConsentUpdate) -> ConsentRead:
    identity = _visible_identity(uow, data.identity_id, for_update=True)
    if identity.user_id != uow.actor.user_id:
        uow.actor.require(CONSENT_UPDATE)
    if identity.status != "active":
        raise Conflict("This WhatsApp link is not active", code="identity_not_active")
    row = consent.record(uow, identity, data.purpose, data.status, source="web_settings", evidence_ref=f"user:{uow.actor.user_id}")
    return ConsentRead(identity_id=identity.id, purpose=data.purpose, status=data.status, recorded_at=row.recorded_at, source=row.source)


# ---- messages ------------------------------------------------------------------------------------------------------
def _buttons(outbox: OutboxMessage | None) -> list[dict[str, str]]:
    if outbox is None:
        return []
    return [{"title": str(b.get("title", ""))} for b in (outbox.payload or {}).get("buttons") or []]


def message_read(uow: UnitOfWork, message: ChannelMessage, outbox: OutboxMessage | None, *, admin: bool) -> MessageRead:
    try:
        body = crypto.decrypt_text(message.body_encrypted)
    except crypto.DecryptError:
        body = None
    own = False
    if outbox is not None:
        identity = uow.session.get(ChannelIdentity, outbox.identity_id)
        own = identity is not None and identity.user_id == uow.actor.user_id
    resendable = outbox is not None and outbox.state in ("unknown", "escalated", "failed", "blocked") and (admin or own)
    return MessageRead(
        id=message.id, identity_id=message.identity_id, direction=message.direction, type=message.type, body=body,  # type: ignore[arg-type]
        status=message.status, status_provider_ts=message.status_provider_ts, simulated=message.simulated,  # type: ignore[arg-type]
        provider_message_id=message.provider_message_id if admin else None, outbox_id=outbox.id if outbox else None,
        outbox_state=outbox.state if outbox else None, blocked_reason=outbox.blocked_reason if outbox else None,  # type: ignore[arg-type]
        last_error=outbox.last_error if outbox and admin else None, created_at=message.created_at, correlation_id=message.correlation_id,
        buttons=_buttons(outbox),
        capabilities={"resend": _cap(resendable, "permission_denied" if not (admin or own) else "not_resendable"),
                      "cancel": _cap(outbox is not None and outbox.state in ("pending", "blocked", "unknown", "escalated") and (admin or own))},
    )


def admin_messages(uow: UnitOfWork, state: str | None) -> list[MessageRead]:
    uow.actor.require(OUTBOX_MANAGE)
    states = (state,) if state else ADMIN_STATES
    if any(s not in ADMIN_STATES for s in states):
        raise ValidationFailed("state must be unknown, failed, blocked or escalated", code="invalid_state")
    rows = list(uow.session.scalars(
        select(OutboxMessage).where(OutboxMessage.company_id == uow.actor.company_id, OutboxMessage.state.in_(states))
        .order_by(OutboxMessage.created_at.desc()).limit(200)
    ))
    out = []
    for outbox in rows:
        message = uow.session.get(ChannelMessage, outbox.message_id) if outbox.message_id else None
        if message is not None:
            out.append(message_read(uow, message, outbox, admin=True))
    return out


def outbox_read(outbox: OutboxMessage) -> OutboxRead:
    return OutboxRead(
        id=outbox.id, identity_id=outbox.identity_id, message_id=outbox.message_id, kind=outbox.kind, purpose=outbox.purpose,  # type: ignore[arg-type]
        state=outbox.state, attempts=outbox.attempts, blocked_reason=outbox.blocked_reason, last_error=outbox.last_error,  # type: ignore[arg-type]
        provider_message_id=outbox.provider_message_id, sent_at=outbox.sent_at, escalated_at=outbox.escalated_at,
        resend_of_id=outbox.resend_of_id, created_at=outbox.created_at,
    )


def resolve_outbox(uow: UnitOfWork, outbox_id: uuid.UUID, data: OutboxResolve) -> OutboxRead:
    """Admins (``channels.outbox.manage``) or the person the message was for: resend as a NEW message (explicit
    confirmation; never a replay of the old request) or cancel."""
    user_id = _require_user(uow)
    outbox = uow.session.scalars(
        select(OutboxMessage).where(OutboxMessage.company_id == uow.actor.company_id, OutboxMessage.id == outbox_id).with_for_update()
    ).first()
    identity = uow.session.get(ChannelIdentity, outbox.identity_id) if outbox else None
    if outbox is None or identity is None or not (uow.actor.can(OUTBOX_MANAGE) or identity.user_id == user_id):
        raise NotFound(code="not_found", resource_type="channels.outbox_message")
    if data.action == "cancel":
        if outbox.state not in ("pending", "blocked", "unknown", "escalated"):
            raise Conflict(f"A message in state {outbox.state} cannot be cancelled", code="outbox_not_cancellable")
        outbox.state = "cancelled"
        uow.audit("channels.outbox.cancelled", resource_type="channels.outbox_message", resource_id=outbox.id)
        return outbox_read(outbox)
    if not data.confirm:
        raise ValidationFailed("Confirm that a new message should be sent", code="confirmation_required",
                               errors=[{"loc": ["body", "confirm"], "msg": "must be true", "type": "confirmation_required"}])
    if outbox.state not in ("unknown", "escalated", "failed", "blocked"):
        raise Conflict(f"A message in state {outbox.state} cannot be resent", code="outbox_not_resendable")
    new = outbound.resend_as_new(uow, outbox)
    outbox.state = "cancelled" if outbox.state in ("unknown", "escalated", "blocked") else outbox.state
    uow.audit("channels.outbox.resent", resource_type="channels.outbox_message", resource_id=outbox.id, details={"new_outbox_id": str(new.id)})
    return outbox_read(new)


# ---- demo simulator ------------------------------------------------------------------------------------------------
def demo_wa_id(user_id: uuid.UUID) -> str:
    """A stable, obviously fake demo number per user (+99 is not an assigned country code)."""
    return "99" + str(int(hashlib.sha256(user_id.bytes).hexdigest()[:12], 16))[:10].rjust(10, "0")


def _require_demo(uow: UnitOfWork) -> Any:
    if get_settings().whatsapp_mode != "demo":
        raise Forbidden("The simulator is available in demo mode only", code="demo_mode_only")
    uow.actor.require(ASSISTANT_USE)
    return accounts.ensure_account(uow)


def demo_inbound(uow: UnitOfWork, data: DemoInbound) -> tuple[DemoInboundResult, bytes, str]:
    """Build a Cloud-API-shaped inbound payload from the user's demo number and sign it; the router ingests it
    through the real webhook function after this transaction commits. Returns (result, body, signature)."""
    from app.modules.channels.whatsapp import demo_provider

    user_id = _require_user(uow)
    account = _require_demo(uow)
    if sum(x is not None for x in (data.text, data.button_id, data.audio_fixture)) != 1:
        raise ValidationFailed("Send exactly one of text, button_id or audio_fixture", code="invalid_simulation")
    wa_id = demo_wa_id(user_id)
    wamid = f"wamid.demo.in.{uuid.uuid4().hex}"
    if data.text is not None:
        message: dict[str, Any] = {"id": wamid, "type": "text", "text": {"body": data.text}}
    elif data.button_id is not None:
        message = {"id": wamid, "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": data.button_id, "title": "button"}}}
    else:
        if data.audio_fixture not in demo_provider.DEMO_AUDIO_FIXTURES:
            raise ValidationFailed("Unknown demo voice note", code="unknown_fixture")
        media_id, mime, sha = demo_provider.register_fixture_audio(data.audio_fixture)  # type: ignore[arg-type]
        message = {"id": wamid, "type": "audio", "audio": {"id": media_id, "mime_type": mime, "sha256": sha, "voice": True}}
    payload = demo_provider.inbound_payload(accounts.account_config(account), wa_id=wa_id, bsuid=None, message=message,
                                            name=uow.actor.display_name or "Demo user")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(int(uow.now().timestamp()))
    body, signature = demo_provider.signed_webhook_body(payload)
    identity = identities.find_identity(uow, account, bsuid=None, wa_id=wa_id)
    return DemoInboundResult(inbox_id=uuid.uuid7(), identity_id=identity.id if identity else None, processed=False), body, signature


def demo_thread(uow: UnitOfWork) -> DemoThread:
    user_id = _require_user(uow)
    account = _require_demo(uow)
    wa_id = demo_wa_id(user_id)
    identity = identities.find_identity(uow, account, bsuid=None, wa_id=wa_id)
    messages: list[MessageRead] = []
    if identity is not None:
        rows = list(uow.session.scalars(
            select(ChannelMessage).where(ChannelMessage.identity_id == identity.id).order_by(ChannelMessage.created_at.desc(), ChannelMessage.id.desc()).limit(60)
        ))
        rows.reverse()
        for row in rows:
            outbox = uow.session.get(OutboxMessage, row.outbox_id) if row.outbox_id else None
            messages.append(message_read(uow, row, outbox, admin=False))
    # the demo number is derived from the signed-in user's id, so this thread is theirs alone
    return DemoThread(
        identity=identity_read(uow, identity) if identity is not None else None, messages=messages,
        mode=account.mode, label_text=accounts.label_text(account), wa_id_masked=identities.mask(wa_id),  # type: ignore[arg-type]
    )


def session_count(uow: UnitOfWork, identity_id: uuid.UUID) -> int:
    return len(list(uow.session.scalars(select(ChannelSession.id).where(ChannelSession.identity_id == identity_id, ChannelSession.revoked_at.is_(None)))))


__all__ = [
    "PROACTIVE_PURPOSES", "admin_messages", "demo_inbound", "demo_thread", "demo_wa_id", "identity_read", "list_identities", "message_read",
    "outbox_read", "resolve_outbox", "revoke", "update_consent",
]
