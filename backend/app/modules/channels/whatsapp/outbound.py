"""Outbound WhatsApp (design §15 "Outbound").

``queue_message`` writes the outbound ``channels_message`` and its ``channels_outbox_message`` in the caller's
transaction (the same transaction as the cause) and enqueues ``wa.outbox.send``. The sender claims the row with
``SKIP LOCKED``, runs every gate (identity active, consent, the 24-hour window or an approved template, the
live-outbound flag and the development allowlist), commits ``sending``, calls the provider with **no transaction
open**, then records the outcome:

- 2xx → ``accepted`` (not delivered) with the wamid;
- timeout, reset, 5xx, or a 2xx without a message id → ``unknown``: never resent automatically (escalated after
  15 minutes by ``reconcile``);
- 429 or a documented "not processed" code → back to ``pending`` with backoff (the reconcile sweep re-enqueues);
- 4xx validation → ``failed``; a policy code (closed window, paused template) → ``blocked`` with the reason.

Retry timing uses business time (``next_attempt_at``); the job queue's run_at is never set from it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.channels import crypto
from app.modules.channels import events as ev
from app.modules.channels.models import ChannelAccount, ChannelIdentity, ChannelMessage, OutboxMessage
from app.modules.channels.whatsapp import accounts, consent, window
from app.modules.channels.whatsapp import identity as identities
from app.modules.channels.whatsapp.provider import AccountConfig, MediaError, SendResult, get_provider
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.channels.outbound")

MAX_ATTEMPTS = 5
STATUS_RANK = {"queued": 0, "accepted": 1, "sent": 2, "delivered": 3, "read": 4, "played": 5}


def _backoff(attempt: int, retry_after: int | None) -> timedelta:
    if retry_after:
        return timedelta(seconds=min(max(retry_after, 1), 3600))
    return timedelta(seconds=min(30 * (2 ** max(attempt - 1, 0)), 3600))


def queue_message(
    uow: UnitOfWork, identity: ChannelIdentity, *, kind: str = "session", payload: dict[str, Any], text: str | None,
    purpose: str = "assistant_replies", idempotency_key: str, cause_ref: str | None = None, template_id: uuid.UUID | None = None,
    proposal_id: uuid.UUID | None = None, run_id: uuid.UUID | None = None, resend_of_id: uuid.UUID | None = None,
    reply_to: str | None = None,
) -> OutboxMessage:
    """Write the outbound message and its outbox row (idempotent on ``idempotency_key``) and enqueue the send."""
    existing = uow.session.scalars(
        select(OutboxMessage).where(OutboxMessage.company_id == uow.actor.company_id, OutboxMessage.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return existing
    account = uow.session.get(ChannelAccount, identity.account_id)
    assert account is not None
    now = uow.now()
    message_type = {"session": "text", "interactive": "interactive", "template": "template", "media": "document"}[kind]
    message = ChannelMessage(
        id=uuid.uuid7(), account_id=account.id, identity_id=identity.id, direction="outbound", type=message_type,
        body_encrypted=crypto.encrypt_text(text) if text else None, status="queued", status_rank=0,
        simulated=account.mode == "demo", correlation_id=uow.actor.correlation_id, proposal_id=proposal_id, run_id=run_id,
        reply_to_provider_id=reply_to, provenance="internal",
    )
    uow.add(message)
    uow.flush()
    body = dict(payload)
    if reply_to:
        body.setdefault("reply_to", reply_to)
    outbox = OutboxMessage(
        id=uuid.uuid7(), account_id=account.id, identity_id=identity.id, message_id=message.id, kind=kind, purpose=purpose,
        payload=body, template_id=template_id, idempotency_key=idempotency_key[:128], state="pending", attempts=0,
        next_attempt_at=now, proposal_id=proposal_id, cause_ref=(cause_ref or None) and cause_ref[:120],
        correlation_id=uow.actor.correlation_id, resend_of_id=resend_of_id,
    )
    uow.add(outbox)
    uow.flush()
    message.outbox_id = outbox.id
    enqueue_send(uow, outbox)
    return outbox


def enqueue_send(uow: UnitOfWork, outbox: OutboxMessage) -> None:
    uow.enqueue(
        ev.JOB_OUTBOX_SEND, {"company_id": str(outbox.company_id or uow.actor.company_id), "outbox_id": str(outbox.id)},
        dedupe_key=f"{ev.JOB_OUTBOX_SEND}:{outbox.id}:{outbox.attempts}", resource_type="channels.outbox_message", resource_id=outbox.id,
    )


@dataclass(frozen=True)
class _Claimed:
    outbox_id: uuid.UUID
    account: AccountConfig
    to: str
    body: dict[str, Any]
    attempts: int


def _block(outbox: OutboxMessage, message: ChannelMessage | None, reason: str) -> None:
    outbox.state = "blocked"
    outbox.blocked_reason = reason[:80]
    if message is not None:
        message.status = "blocked"


def _gate(uow: UnitOfWork, outbox: OutboxMessage, identity: ChannelIdentity, account: ChannelAccount, now: datetime) -> str | None:
    """The block reason, or None when every gate passes."""
    settings = get_settings()
    if identity.status != "active":
        return f"identity_{identity.status}"
    if account.mode == "live" and accounts.missing_settings(settings):
        return "not_configured"
    allowed, reason = consent.allows(uow, identity.id, outbox.purpose)
    if not allowed:
        return reason or "consent_missing"
    if outbox.kind == "template":
        template, reason = window.template_check(uow, outbox.template_id)
        if reason:
            return reason
        if outbox.purpose == "daily_briefing" and template is not None and template.category.upper() != "UTILITY":
            return "template_not_utility"  # a briefing push outside the window needs an approved utility template
    elif not window.window_open(identity, now):
        return "window_closed"
    if account.mode == "live":
        if not settings.whatsapp_live_outbound:
            return "live_outbound_disabled"
        allowlist = {identities.digits(n) for n in settings.whatsapp_dev_allowlist.split(",") if identities.digits(n)}
        # outside production every live recipient must be on the allowlist (empty = nobody); in production the
        # allowlist, when set, still restricts
        if (not settings.is_production or allowlist) and identities.digits(identity.wa_id) not in allowlist:
            return "not_in_dev_allowlist"
    return None


def _claim(company_id: uuid.UUID, outbox_id: uuid.UUID) -> _Claimed | None:
    """Transaction 1: claim, gate and commit ``sending`` (or the block)."""
    with UnitOfWork(ActorContext.system(company_id, reason="channels.outbox.send")) as uow:
        outbox = uow.session.scalars(
            select(OutboxMessage).where(OutboxMessage.id == outbox_id, OutboxMessage.state == "pending").with_for_update(skip_locked=True)
        ).first()
        if outbox is None:
            return None
        now = uow.now()
        if outbox.next_attempt_at > now:
            return None  # a backoff is still running; the reconcile sweep re-enqueues it when due
        identity = uow.session.get(ChannelIdentity, outbox.identity_id)
        account = uow.session.get(ChannelAccount, outbox.account_id)
        message = uow.session.get(ChannelMessage, outbox.message_id) if outbox.message_id else None
        assert identity is not None and account is not None
        reason = _gate(uow, outbox, identity, account, now)
        if reason is not None:
            _block(outbox, message, reason)
            uow.audit("channels.outbox.blocked", resource_type="channels.outbox_message", resource_id=outbox.id, outcome="failed", details={"reason": reason})
            return None
        body = dict(outbox.payload or {})
        config = accounts.account_config(account)
        if body.get("type") == "document" and not body.get("media_id"):
            body = _with_uploaded_document(uow, config, body)
        outbox.state = "sending"
        outbox.attempts += 1
        outbox.last_error = None
        to = identity.wa_id or identity.bsuid or ""
        return _Claimed(outbox.id, config, to, body, outbox.attempts)


def _with_uploaded_document(uow: UnitOfWork, config: AccountConfig, body: dict[str, Any]) -> dict[str, Any]:
    """Re-render the bound revision, verify its hash and upload it (the provider returns a media id)."""
    from app.modules.channels.send_approval import render_revision
    from app.modules.sales.models import QuoteRevision

    revision = uow.session.get(QuoteRevision, uuid.UUID(str(body["revision_id"])))
    if revision is None:
        raise MediaError("document_missing")
    pdf, digest, filename = render_revision(revision)
    if digest != body.get("document_sha256"):
        raise MediaError("document_changed")
    media_id = get_provider().upload_media(config, pdf, "application/pdf", filename)
    return {**body, "media_id": media_id, "filename": filename}


def _record(company_id: uuid.UUID, claimed: _Claimed, result: SendResult) -> str:
    """Transaction 2: the outcome."""
    with UnitOfWork(ActorContext.system(company_id, reason="channels.outbox.result")) as uow:
        outbox = uow.session.scalars(select(OutboxMessage).where(OutboxMessage.id == claimed.outbox_id).with_for_update()).first()
        assert outbox is not None
        message = uow.session.get(ChannelMessage, outbox.message_id) if outbox.message_id else None
        now = uow.now()
        outcome = result.outcome
        detail = " ".join(str(p) for p in (result.http_status, result.error_code, result.error_title) if p)
        if outcome == "accepted":
            outbox.state = "accepted"
            outbox.provider_message_id = result.wamid
            outbox.sent_at = now
            if message is not None:
                message.provider_message_id = message.provider_message_id or result.wamid
                if message.status_rank < STATUS_RANK["accepted"] and message.status in ("queued", "unknown"):
                    message.status, message.status_rank = "accepted", STATUS_RANK["accepted"]
        elif outcome == "unknown":
            outbox.state = "unknown"
            outbox.sent_at = now
            outbox.last_error = (detail or "unknown")[:300]
            if message is not None and message.status_rank == 0:
                message.status = "unknown"
        elif outcome in ("retry", "throttle"):
            if outbox.attempts >= MAX_ATTEMPTS:
                outbox.state = "failed"
                outbox.last_error = f"gave up after {outbox.attempts} attempts: {detail}"[:300]
                if message is not None:
                    message.status = "failed"
            else:
                outbox.state = "pending"
                outbox.next_attempt_at = now + _backoff(outbox.attempts, result.retry_after_seconds)
                outbox.last_error = (detail or outcome)[:300]
        elif outcome == "blocked":
            _block(outbox, message, f"provider_{result.error_code or 'policy'}")
            outbox.last_error = detail[:300] or None
        else:
            outbox.state = "failed"
            outbox.last_error = (detail or "failed")[:300]
            if message is not None:
                message.status = "failed"
        uow.audit(
            "channels.outbox.sent", resource_type="channels.outbox_message", resource_id=outbox.id,
            outcome="success" if outcome == "accepted" else "failed", details={"outcome": outcome, "http_status": result.http_status, "error_code": result.error_code},
        )
        return outbox.state


def send_one(company_id: uuid.UUID, outbox_id: uuid.UUID) -> str | None:
    """Claim, send and record one outbox row; returns the final state (None when nothing was claimed)."""
    try:
        claimed = _claim(company_id, outbox_id)
    except MediaError as exc:
        _fail_media(company_id, outbox_id, exc.code)
        return "failed"
    if claimed is None:
        return None
    provider = get_provider()
    try:
        result = provider.send(claimed.account, claimed.to, claimed.body, biz_opaque=str(claimed.outbox_id))
    except Exception as exc:  # the request may have left: never resend blindly
        log.warning("channels.outbox.send_error", outbox_id=str(claimed.outbox_id), error=type(exc).__name__)
        result = SendResult(outcome="unknown", error_title=type(exc).__name__)
    state = _record(company_id, claimed, result)
    simulate = getattr(provider, "simulate_statuses", None)
    if state == "accepted" and result.wamid and callable(simulate) and claimed.account.mode == "demo":
        clock_ts = int(_now(company_id).timestamp())
        simulate(claimed.account, result.wamid, claimed.to, biz_opaque=str(claimed.outbox_id), now_ts=clock_ts)
    return state


def _now(company_id: uuid.UUID) -> datetime:
    from app.core.clock import get_clock

    return get_clock(company_id).now()


def _fail_media(company_id: uuid.UUID, outbox_id: uuid.UUID, code: str) -> None:
    with UnitOfWork(ActorContext.system(company_id, reason="channels.outbox.media")) as uow:
        outbox = uow.session.get(OutboxMessage, outbox_id)
        if outbox is None or outbox.state != "pending":
            return
        outbox.state = "failed"
        outbox.last_error = code[:300]
        message = uow.session.get(ChannelMessage, outbox.message_id) if outbox.message_id else None
        if message is not None:
            message.status = "failed"


def send_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    company_id = uuid.UUID(str(payload["company_id"]))
    outbox_id = uuid.UUID(str(payload["outbox_id"]))
    return {"state": send_one(company_id, outbox_id)}


def resend_as_new(uow: UnitOfWork, original: OutboxMessage) -> OutboxMessage:
    """The confirmed "Resend as new message": a new outbox row with a new idempotency key (never a replay)."""
    identity = uow.session.get(ChannelIdentity, original.identity_id)
    assert identity is not None
    message = uow.session.get(ChannelMessage, original.message_id) if original.message_id else None
    text = crypto.decrypt_text(message.body_encrypted) if message is not None else None
    payload = {k: v for k, v in dict(original.payload or {}).items() if k != "media_id"}
    return queue_message(
        uow, identity, kind=original.kind, payload=payload, text=text, purpose=original.purpose,
        idempotency_key=f"resend:{original.id}:{uuid.uuid7().hex}", cause_ref=f"resend:{original.id}", template_id=original.template_id,
        proposal_id=original.proposal_id, resend_of_id=original.id,
    )


__all__ = ["MAX_ATTEMPTS", "STATUS_RANK", "enqueue_send", "queue_message", "resend_as_new", "send_job", "send_one"]
