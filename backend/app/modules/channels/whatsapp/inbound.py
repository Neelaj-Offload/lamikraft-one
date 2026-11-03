"""Inbound processing (``wa.inbox.process``; design §15 "Processing", "Identity", "Message types").

1. The inbox row is parsed into typed payloads; each ``messages`` change is routed to the company that owns its
   ``phone_number_id`` (unknown numbers are ignored).
2. Fan-out: one ``inbound_event`` per message (key = wamid), status (wamid:status:timestamp), template update or
   error, inserted with ON CONFLICT DO NOTHING, so a replayed delivery has no second business effect.
3. Each event is processed in its own transaction, in ``provider_ts`` order, serially per sender (advisory lock);
   a message older than the identity's ``last_inbound_at`` is flagged ``late``. Group messages are ignored.
4. Identity: BSUID first, then wa_id. ``LINK <code>`` links an employee; unknown, revoked and suspended senders
   get the generic "not linked" reply (at most hourly) with no data and no tools; a BSUID change suspends.
5. Employees: text → a turn; audio → media fetch (≤ 10 MB, SHA-256 checked) → STT → "I heard: …" → a turn;
   image/document → stored as external content; buttons → action refs (no model); other types → a polite reply;
   STOP / UNSUBSCRIBE / "band karo" → opt-out with a confirmation.
6. Customers and vendors: stored as external content and recorded through ``sales.record_customer_message`` for the
   owner's Inbox. No AI reply is ever sent to them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.modules.channels import crypto
from app.modules.channels import events as ev
from app.modules.channels.models import (
    ChannelAccount,
    ChannelIdentity,
    ChannelMessage,
    InboundEvent,
    WebhookInbox,
)
from app.modules.channels.whatsapp import accounts, consent, enrolment, reconcile, replies, stt, templates
from app.modules.channels.whatsapp import identity as identities
from app.modules.channels.whatsapp.payloads import (
    Contact,
    Message,
    MessagesValue,
    Status,
    TemplateStatusValue,
    classify_message,
    messages_changes,
    parse_payload,
    status_event_key,
    template_changes,
    template_event_key,
)
from app.modules.channels.whatsapp.provider import MediaError, get_provider
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.channels.inbound")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
SYSTEM_SUSPEND_TYPES = frozenset({"user_id_update", "user_changed_user_id", "user_changed_number", "customer_changed_number", "customer_identity_changed"})


# ---- the inbox job -------------------------------------------------------------------------------------------------
def process_inbox_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    return process_inbox(uuid.UUID(str(payload["inbox_id"])))


def process_inbox(inbox_id: uuid.UUID) -> dict[str, Any]:
    with UnitOfWork(ActorContext.system(None, reason="channels.inbox")) as uow:
        inbox = uow.session.get(WebhookInbox, inbox_id)
        if inbox is None or inbox.status in ("done", "ignored"):
            return {"status": "skipped"}
        raw, simulated = dict(inbox.payload or {}), inbox.simulated
        inbox.attempts += 1
    try:
        parsed = parse_payload(raw)
        changes = messages_changes(parsed)
        template_updates = template_changes(parsed)
    except ValidationError as exc:
        _finish_inbox(inbox_id, "failed", None, f"invalid payload: {exc.error_count()} error(s)")
        return {"status": "failed"}
    pending: list[tuple[uuid.UUID, uuid.UUID]] = []
    company_seen: uuid.UUID | None = None
    account_seen: uuid.UUID | None = None
    for _waba_id, value in changes:
        owner = accounts.resolve_company(value.metadata.phone_number_id)
        if owner is None:
            log.info("channels.inbox.unknown_number", inbox_id=str(inbox_id))
            continue
        company_id, account_id = owner
        company_seen, account_seen = company_id, account_id
        pending += [(company_id, e) for e in fan_out(company_id, account_id, inbox_id, value, simulated=simulated)]
    for waba_id, value in template_updates:
        owner = _company_for_waba(waba_id)
        if owner is None:
            continue
        company_id, account_id = owner
        company_seen, account_seen = company_id, account_id
        pending += [(company_id, e) for e in fan_out_template(company_id, account_id, inbox_id, value, parsed_time=_entry_time(raw, waba_id), simulated=simulated)]
    failures = 0
    for company_id, event_id in _ordered(pending):
        if not process_event(company_id, event_id):
            failures += 1
    if company_seen is None:
        _finish_inbox(inbox_id, "ignored", None, "no known phone number id")
        return {"status": "ignored"}
    if failures:
        _finish_inbox(inbox_id, "pending", (company_seen, account_seen), f"{failures} event(s) failed; retried")
        raise RuntimeError(f"{failures} inbound event(s) failed")  # the job retries the failed events only
    _finish_inbox(inbox_id, "done", (company_seen, account_seen), None)
    return {"status": "done", "events": len(pending)}


def _entry_time(raw: dict[str, Any], waba_id: str) -> Any:
    for entry in raw.get("entry") or []:
        if str(entry.get("id")) == waba_id:
            return entry.get("time")
    return None


def _company_for_waba(waba_id: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    for company_id in accounts.active_company_ids():
        with UnitOfWork(ActorContext.system(company_id, reason="channels.resolve_waba")) as uow:
            row = uow.session.scalars(select(ChannelAccount).where(ChannelAccount.company_id == company_id, ChannelAccount.waba_id == waba_id)).first()
            if row is not None:
                return company_id, row.id
    return None


def _finish_inbox(inbox_id: uuid.UUID, status: str, owner: tuple[uuid.UUID | None, uuid.UUID | None] | None, error: str | None) -> None:
    with UnitOfWork(ActorContext.system(None, reason="channels.inbox")) as uow:
        inbox = uow.session.get(WebhookInbox, inbox_id)
        if inbox is None:
            return
        inbox.status = status if status != "pending" else "pending"
        inbox.error = error
        inbox.processed_at = uow.now() if status in ("done", "ignored", "failed") else None
        if owner is not None:
            inbox.company_id, inbox.account_id = owner


def _ordered(pending: list[tuple[uuid.UUID, uuid.UUID]]) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Events in provider-timestamp order (statuses after the messages of the same instant)."""
    keyed: list[tuple[datetime | None, int, uuid.UUID, uuid.UUID]] = []
    for company_id, event_id in pending:
        with UnitOfWork(ActorContext.system(company_id, reason="channels.order")) as uow:
            event = uow.session.get(InboundEvent, event_id)
            if event is not None:
                keyed.append((event.provider_ts, 1 if event.kind == "status" else 0, company_id, event_id))
    floor = datetime.min.replace(tzinfo=None)
    keyed.sort(key=lambda k: ((k[0].replace(tzinfo=None) if k[0] else floor), k[1], k[3]))
    return [(k[2], k[3]) for k in keyed]


# ---- fan-out -------------------------------------------------------------------------------------------------------
def _insert_event(uow: UnitOfWork, *, account_id: uuid.UUID, inbox_id: uuid.UUID, kind: str, key: str, provider_ts: datetime | None,
                  payload: dict[str, Any], simulated: bool, status: str = "pending", error: str | None = None) -> uuid.UUID | None:
    now = uow.now()
    stmt = pg_insert(InboundEvent).values(
        id=uuid.uuid7(), company_id=uow.actor.company_id, inbox_id=inbox_id, account_id=account_id, kind=kind, provider_event_key=key[:200],
        provider_ts=provider_ts, late=False, simulated=simulated, status=status, error=error, payload=payload,
        correlation_id=uow.actor.correlation_id, created_at=now, updated_at=now,
    ).on_conflict_do_nothing(index_elements=["account_id", "provider_event_key"])
    row = uow.session.execute(stmt.returning(InboundEvent.id)).first()
    return row[0] if row else None


def fan_out(company_id: uuid.UUID, account_id: uuid.UUID, inbox_id: uuid.UUID, value: MessagesValue, *, simulated: bool) -> list[uuid.UUID]:
    """Insert the change's events (replays collide) and return the events of this inbox still to process."""
    from app.modules.channels.whatsapp.demo_provider import is_simulated_wamid

    with UnitOfWork(ActorContext.system(company_id, reason="channels.fan_out")) as uow:
        account = uow.session.get(ChannelAccount, account_id)
        assert account is not None
        if account.mode == "live" and not simulated:
            accounts.mark_check(uow, account, "signed_event_ok_at", uow.now())
        contacts = {c.wa_id: c for c in value.contacts if c.wa_id}
        for message in value.messages:
            contact = contacts.get(message.from_ or "") or (value.contacts[0] if len(value.contacts) == 1 else None)
            kind = "identity_change" if message.type == "system" else "message"
            data = {"message": message.model_dump(mode="json", by_alias=True, exclude_none=True),
                    "contact": contact.model_dump(mode="json", exclude_none=True) if contact else None}
            if message.is_group:
                _insert_event(uow, account_id=account_id, inbox_id=inbox_id, kind=kind, key=message.id, provider_ts=message.provider_ts,
                              payload={}, simulated=simulated, status="ignored", error="group message")
                continue
            _insert_event(uow, account_id=account_id, inbox_id=inbox_id, kind=kind, key=message.id, provider_ts=message.provider_ts,
                          payload=data, simulated=simulated)
        for status in value.statuses:
            _insert_event(uow, account_id=account_id, inbox_id=inbox_id, kind="status", key=status_event_key(status),
                          provider_ts=status.provider_ts, payload=status.model_dump(mode="json", exclude_none=True),
                          simulated=simulated or is_simulated_wamid(status.id))
        for index, error in enumerate(value.errors):
            _insert_event(uow, account_id=account_id, inbox_id=inbox_id, kind="error", key=f"err:{inbox_id}:{index}", provider_ts=None,
                          payload=error.model_dump(mode="json", exclude_none=True), simulated=simulated, status="ignored",
                          error=f"{error.code} {error.title or ''}"[:500])
        return list(uow.session.scalars(
            select(InboundEvent.id).where(InboundEvent.inbox_id == inbox_id, InboundEvent.account_id == account_id,
                                          InboundEvent.status.in_(("pending", "failed")))
        ))


def fan_out_template(company_id: uuid.UUID, account_id: uuid.UUID, inbox_id: uuid.UUID, value: TemplateStatusValue, *, parsed_time: Any,
                     simulated: bool) -> list[uuid.UUID]:
    with UnitOfWork(ActorContext.system(company_id, reason="channels.fan_out")) as uow:
        _insert_event(uow, account_id=account_id, inbox_id=inbox_id, kind="template_status", key=template_event_key(value, parsed_time),
                      provider_ts=None, payload=value.model_dump(mode="json", exclude_none=True), simulated=simulated)
        return list(uow.session.scalars(
            select(InboundEvent.id).where(InboundEvent.inbox_id == inbox_id, InboundEvent.kind == "template_status",
                                          InboundEvent.status.in_(("pending", "failed")))
        ))


# ---- one event -----------------------------------------------------------------------------------------------------
def process_event(company_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    """Process one event in its own transaction; False when it failed (recorded on the event, retried)."""
    followups: list[dict[str, Any]] = []
    try:
        with UnitOfWork(ActorContext.system(company_id, reason="channels.inbound")) as uow:
            event = uow.session.scalars(select(InboundEvent).where(InboundEvent.id == event_id).with_for_update()).first()
            if event is None or event.status not in ("pending", "failed"):
                return True
            uow.actor = uow.actor.with_(correlation_id=event.correlation_id or str(uuid.uuid7()))
            account = uow.session.get(ChannelAccount, event.account_id)
            assert account is not None
            if event.kind == "status":
                event.status = reconcile.apply_status(uow, event, Status.model_validate(event.payload), simulated=event.simulated)
            elif event.kind == "template_status":
                templates.apply_status_update(uow, account, TemplateStatusValue.model_validate(event.payload))
                event.status = "done"
            else:
                followups = handle_message(uow, account, event)
                event.status = "done"
            event.error = None
            event.processed_at = uow.now()
    except Exception as exc:
        log.warning("channels.inbound.failed", event_id=str(event_id), error=type(exc).__name__, detail=str(exc)[:300])
        with UnitOfWork(ActorContext.system(company_id, reason="channels.inbound.failed")) as uow:
            event = uow.session.get(InboundEvent, event_id)
            if event is not None:
                event.status, event.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        return False
    for followup in followups:
        if followup.get("media") == "audio":
            process_audio(company_id, followup)
        elif followup.get("media") in ("image", "document"):
            process_attachment(company_id, followup)
        elif "turn" in followup:
            turn = followup["turn"]
            replies.submit_turn(company_id, followup["message_id"], text=turn["text"], wamid=followup["wamid"], selected_option=turn.get("selected_option"))
    return True


def _store_message(uow: UnitOfWork, account: ChannelAccount, identity: ChannelIdentity, event: InboundEvent, message: Message, *,
                   body: str | None, kind: str, provenance: str) -> ChannelMessage:
    row = ChannelMessage(
        id=uuid.uuid7(), account_id=account.id, identity_id=identity.id, direction="inbound", provider_message_id=message.id,
        type=kind, body_encrypted=crypto.encrypt_text(body) if body else None, reply_to_provider_id=message.context.id if message.context else None,
        inbound_event_id=event.id, status="delivered", status_rank=3, simulated=event.simulated, correlation_id=uow.actor.correlation_id,
        provider_ts=message.provider_ts, provenance=provenance,
    )
    uow.add(row)
    uow.flush()
    uow.emit(ev.MESSAGE_RECEIVED, aggregate_id=row.id, payload=ev.payload(ev.MessageReceivedPayload(
        message_id=row.id, identity_id=identity.id, identity_kind=identity.kind, type=kind)))
    return row


def _sender(event: InboundEvent) -> tuple[Message, Contact | None, str | None, str | None, str | None]:
    message = Message.model_validate(event.payload["message"])
    contact = Contact.model_validate(event.payload["contact"]) if event.payload.get("contact") else None
    wa_id = message.from_ or (contact.wa_id if contact else None)
    bsuid = message.from_user_id or (contact.user_id if contact else None)
    username = contact.username if contact else None
    return message, contact, wa_id, bsuid, username


def handle_message(uow: UnitOfWork, account: ChannelAccount, event: InboundEvent) -> list[dict[str, Any]]:
    message, _contact, wa_id, bsuid, username = _sender(event)
    uow.advisory_xact_lock("channels.identity", f"{account.id}:{bsuid or wa_id}")
    now = uow.now()
    provider_ts = message.provider_ts or now
    kind = classify_message(message)
    identity = identities.find_identity(uow, account, bsuid=bsuid, wa_id=wa_id)
    if identity is not None and identity.last_inbound_at is not None and provider_ts < identity.last_inbound_at:
        event.late = True
    if kind == "system":
        _handle_system(uow, identity, message)
        return []
    code = enrolment.parse_code(message.text.body) if kind == "text" and message.text else None
    if code is not None:
        return _handle_link(uow, account, event, message, code, wa_id=wa_id, bsuid=bsuid, username=username)
    if identity is None:
        identity = identities.ensure_unknown_identity(uow, account, wa_id=wa_id, bsuid=bsuid)
    event.identity_id = identity.id
    _touch_inbound(identity, provider_ts)
    if identity.kind in ("customer", "vendor") or (identity.kind == "unknown" and identities.match_customer(uow, account, wa_id=wa_id)):
        _handle_customer(uow, account, identity, event, message, kind, wa_id=wa_id, bsuid=bsuid)
        return []
    if not identities.is_authorised(uow, identity, now):
        _store_message(uow, account, identity, event, message, body=_text_of(message), kind=kind, provenance="external")
        if identity.last_generic_reply_at is None or now - identity.last_generic_reply_at >= identities.GENERIC_REPLY_INTERVAL:
            identity.last_generic_reply_at = now
            replies.notice(uow, identity, replies.NOT_LINKED, key=f"not_linked:{message.id}", reply_to=message.id)
        return []
    identities.touch_session(uow, identity, now)
    return _handle_employee(uow, account, identity, event, message, kind)


def _touch_inbound(identity: ChannelIdentity, provider_ts: datetime) -> None:
    if identity.last_inbound_at is None or provider_ts > identity.last_inbound_at:
        identity.last_inbound_at = provider_ts


def _text_of(message: Message) -> str | None:
    if message.text is not None:
        return message.text.body
    media = message.media
    if media is not None and media.caption:
        return media.caption
    if message.interactive is not None:
        reply = message.interactive.button_reply or message.interactive.list_reply
        return reply.title if reply is not None else None
    return None


def _handle_system(uow: UnitOfWork, identity: ChannelIdentity | None, message: Message) -> None:
    system_type = (message.system.type if message.system else None) or ""
    if identity is None or system_type not in SYSTEM_SUSPEND_TYPES:
        return
    if identity.status in ("active", "pending"):
        identities.suspend_identity(uow, identity, reason=system_type)


def _handle_link(uow: UnitOfWork, account: ChannelAccount, event: InboundEvent, message: Message, code: str, *,
                 wa_id: str | None, bsuid: str | None, username: str | None) -> list[dict[str, Any]]:
    outcome = enrolment.try_link(uow, account, code, wa_id=wa_id, bsuid=bsuid, username=username, simulated=event.simulated)
    identity = outcome.identity or identities.ensure_unknown_identity(uow, account, wa_id=wa_id, bsuid=bsuid)
    event.identity_id = identity.id
    _touch_inbound(identity, message.provider_ts or uow.now())
    # the code itself is never stored
    _store_message(uow, account, identity, event, message, body="LINK ••••••••", kind="text", provenance="internal")
    text = {
        "linked": f"Linked to Lamikraft One{(' as ' + outcome.user_name) if outcome.user_name else ''}. Send a message to ask the assistant. Reply STOP to stop proactive messages.",
        "expired": "That code has expired. Create a new one in Settings > WhatsApp on the web.",
        "invalid": "That code is not valid. Check it in Settings > WhatsApp on the web.",
        "locked": "Too many wrong codes. Wait ten minutes, then create a new code on the web.",
    }[outcome.outcome]
    replies.notice(uow, identity, text, key=f"link:{message.id}", reply_to=message.id)
    return []


def _handle_customer(uow: UnitOfWork, account: ChannelAccount, identity: ChannelIdentity, event: InboundEvent, message: Message, kind: str,
                     *, wa_id: str | None, bsuid: str | None) -> None:
    from app.modules.sales import service as sales
    from app.modules.sales.schemas import Channel, CustomerMessageCreate

    if identity.kind == "unknown":
        match = identities.match_customer(uow, account, wa_id=wa_id)
        assert match is not None
        identity = identities.ensure_customer_identity(uow, account, wa_id=wa_id, bsuid=bsuid, party_id=match[0], contact_id=match[1])
    body = _text_of(message)
    stored = _store_message(uow, account, identity, event, message, body=body, kind=kind, provenance="external")
    if kind == "text" and body and consent.is_opt_out(body):
        consent.opt_out_all(uow, identity, evidence_ref=f"wamid:{message.id}", now=uow.now())
        replies.notice(uow, identity, "You will not receive further promotional or proactive messages from us. Reply START to opt in again.",
                       key=f"optout:{message.id}", reply_to=message.id)
        return
    if identity.party_id is None:
        return
    summary = body or {"audio": "[voice note]", "image": "[image]", "document": "[document]"}.get(kind, f"[{message.type} message]")
    sales.record_customer_message(
        uow,
        CustomerMessageCreate(party_id=identity.party_id, contact_id=identity.contact_id, channel=Channel.WHATSAPP,
                              received_at=message.provider_ts or uow.now(), subject="WhatsApp message", body=summary[:20000]),
        origin="channels", origin_ref=f"channels.message:{stored.id}",
    )


def _handle_employee(uow: UnitOfWork, account: ChannelAccount, identity: ChannelIdentity, event: InboundEvent, message: Message,
                     kind: str) -> list[dict[str, Any]]:
    body = _text_of(message)
    stored = _store_message(uow, account, identity, event, message, body=body, kind=kind, provenance="external" if kind in ("image", "document") else "internal")
    if kind == "text" and body is not None:
        if consent.is_opt_out(body):
            consent.opt_out_all(uow, identity, evidence_ref=f"wamid:{message.id}", now=uow.now())
            replies.notice(uow, identity, "Proactive messages are off (daily briefing and updates). Replies to your own messages continue. Send START to turn them back on.",
                           key=f"optout:{message.id}", reply_to=message.id)
            return []
        if consent.is_opt_in(body):
            consent.opt_in_all(uow, identity, evidence_ref=f"wamid:{message.id}", now=uow.now())
            replies.notice(uow, identity, "Proactive messages are on again. Send STOP to turn them off.", key=f"optin:{message.id}", reply_to=message.id)
            return []
        stored.input_mode = "wa_text"
        return [{"turn": {"text": body}, "message_id": stored.id, "wamid": message.id}]
    media = message.media
    if kind in ("audio", "image", "document") and media is not None and media.id:
        return [{"media": kind, "kind": kind, "message_id": stored.id, "wamid": message.id, "account_id": account.id, "media_id": media.id,
                 "sha256": media.sha256, "filename": media.filename, "user_id": str(identity.user_id)}]
    if kind == "interactive" and message.interactive is not None and message.interactive.reply_id:
        stored.input_mode = "card_action"
        followup = replies.handle_button(uow, identity, message.interactive.reply_id, wamid=message.id, provider_ts=message.provider_ts)
        return [{**followup, "message_id": stored.id, "wamid": message.id}] if followup else []
    replies.notice(uow, identity, replies.UNSUPPORTED, key=f"unsupported:{message.id}", reply_to=message.id)
    return []


def _fetch(company_id: uuid.UUID, account_id: uuid.UUID, media_id: str, expected_sha256: str | None, max_bytes: int) -> tuple[bytes, str | None]:
    """Download inbound media with no transaction open (5-minute URL, bearer auth, size bound, SHA-256 check)."""
    with UnitOfWork(ActorContext.system(company_id, reason="channels.media")) as uow:
        account = uow.session.get(ChannelAccount, account_id)
        assert account is not None
        config = accounts.account_config(account)
    provider = get_provider()
    info = provider.get_media(config, media_id)
    if expected_sha256 and info.sha256 and expected_sha256 != info.sha256:
        raise MediaError("media_sha256_mismatch")
    return provider.download_media(config, info, max_bytes=max_bytes), info.mime_type


def _notice_for(company_id: uuid.UUID, message_id: uuid.UUID, text: str, key: str, **updates: Any) -> ChannelMessage | None:
    with UnitOfWork(ActorContext.system(company_id, reason="channels.media.reply")) as uow:
        stored = uow.session.get(ChannelMessage, message_id)
        if stored is None:
            return None
        for name, value in updates.items():
            setattr(stored, name, value)
        identity = uow.session.get(ChannelIdentity, stored.identity_id)
        if identity is not None:
            replies.notice(uow, identity, text, key=key, reply_to=stored.provider_message_id)
        return stored


AUDIO_ERRORS = {
    "media_too_large": "That voice note is longer than I can take (10 MB). Please send a shorter one or type your request.",
    "media_sha256_mismatch": "That voice note did not arrive intact. Please send it again.",
}


def process_audio(company_id: uuid.UUID, followup: dict[str, Any]) -> None:
    """Voice note: fetch, check, transcribe, echo "I heard: ...", then the same turn as text (``wa_voice``)."""
    import hashlib

    message_id, wamid = followup["message_id"], followup["wamid"]
    try:
        data, mime = _fetch(company_id, followup["account_id"], followup["media_id"], followup.get("sha256"), MAX_AUDIO_BYTES)
    except MediaError as exc:
        _notice_for(company_id, message_id, AUDIO_ERRORS.get(exc.code, "I could not download that voice note (the link expired). Please send it again."), f"audio:{wamid}")
        return
    digest = hashlib.sha256(data).hexdigest()
    transcript = stt.transcribe(data, mime, digest)
    text = transcript.text.strip()
    if transcript.empty or not text:
        _notice_for(company_id, message_id, "I could not make out that voice note. Please try again or type your request.", f"audio:{wamid}", media_sha256=digest)
        return
    label = f" ({transcript.provider_label} transcript)" if transcript.provider_label == "Demo" else ""
    _notice_for(company_id, message_id, f"I heard{label}: “{text}”", f"heard:{wamid}",
                media_sha256=digest, body_encrypted=crypto.encrypt_text(text), input_mode="wa_voice")
    replies.submit_turn(company_id, message_id, text=text, wamid=wamid)


def process_attachment(company_id: uuid.UUID, followup: dict[str, Any]) -> None:
    """Image or document: fetch (bounded), store as the linked user's restricted file, mark it external content."""
    import hashlib

    from app.platform.files import service as files

    message_id, wamid, kind = followup["message_id"], followup["wamid"], followup["kind"]
    try:
        data, _mime = _fetch(company_id, followup["account_id"], followup["media_id"], followup.get("sha256"), MAX_ATTACHMENT_BYTES)
    except MediaError:
        _notice_for(company_id, message_id, f"I could not download that {kind} (expired or larger than 10 MB). Please send it again.", f"media:{wamid}")
        return
    digest = hashlib.sha256(data).hexdigest()
    filename = str(followup.get("filename") or f"whatsapp-{kind}-{wamid[-8:]}")[:120]
    try:
        actor = replies.member_actor(company_id, uuid.UUID(str(followup["user_id"])), None)
        with UnitOfWork(actor) as uow:
            stored_file = files.store_generated(uow, data, filename=filename, purpose="image" if kind == "image" else "document", restricted=True)
    except Exception as exc:  # unsupported type or over the platform limit
        log.info("channels.attachment_refused", wamid=wamid, error=type(exc).__name__)
        _notice_for(company_id, message_id, f"I can keep PDF documents and PNG, JPEG or WebP images. That {kind} was not saved.", f"media:{wamid}", media_sha256=digest)
        return
    _notice_for(company_id, message_id, f"Saved {filename} to your files as external content. Open the web app to use it.", f"media:{wamid}",
                media_sha256=digest, media_file_id=stored_file.id)


__all__ = ["MAX_AUDIO_BYTES", "fan_out", "handle_message", "process_event", "process_inbox", "process_inbox_job"]
