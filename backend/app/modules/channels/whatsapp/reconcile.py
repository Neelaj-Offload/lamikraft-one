"""Reconciliation (design §15): provider statuses → message state, and the sweep for stuck rows.

- A status matches its message by wamid, else by ``biz_opaque_callback_data`` (= the outbox id), which covers a
  status that arrives before the send response. An unmatched status is ``pending_match`` and retried by the sweep
  (given up after an hour: ``ignored``).
- Rank order accepted < sent < delivered < read < played; a status applies only when it raises the rank;
  ``failed`` applies only below delivered. Every status event is kept (append-only ``message_status_event``).
- Real delivery evidence comes only from provider statuses; simulated statuses (Demo provider) are kept and
  flagged ``simulated``.
- The sweep (``wa.outbox.reconcile``, every minute): escalates ``unknown`` rows with no status after 15 minutes
  (``channels.message.delivery_unknown`` and an Inbox task with a confirmed "Resend as new message"), retries
  ``pending_match`` events and re-enqueues pending rows whose backoff is over.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.modules.channels import events as ev
from app.modules.channels.models import (
    ChannelIdentity,
    ChannelMessage,
    InboundEvent,
    MessageStatusEvent,
    OutboxMessage,
)
from app.modules.channels.whatsapp.outbound import STATUS_RANK, enqueue_send
from app.modules.channels.whatsapp.payloads import Status
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

log = get_logger("lk.channels.reconcile")

UNKNOWN_ESCALATION = timedelta(minutes=15)
PENDING_MATCH_GIVE_UP = timedelta(hours=1)
FAILED_BELOW_RANK = STATUS_RANK["delivered"]


def _match(uow: UnitOfWork, account_id: uuid.UUID, status: Status) -> ChannelMessage | None:
    message = uow.session.scalars(
        select(ChannelMessage).where(ChannelMessage.account_id == account_id, ChannelMessage.provider_message_id == status.id).with_for_update()
    ).first()
    if message is not None:
        return message
    opaque = status.biz_opaque_callback_data
    if not opaque:
        return None
    try:
        outbox_id = uuid.UUID(opaque)
    except ValueError:
        return None
    outbox = uow.session.get(OutboxMessage, outbox_id)
    if outbox is None or outbox.account_id != account_id or outbox.message_id is None:
        return None
    message = uow.session.scalars(select(ChannelMessage).where(ChannelMessage.id == outbox.message_id).with_for_update()).first()
    if message is not None and message.provider_message_id is None:
        message.provider_message_id = status.id  # the status beat the send response: learn the wamid now
    if outbox.provider_message_id is None:
        outbox.provider_message_id = status.id
    return message


def apply_status(uow: UnitOfWork, event: InboundEvent, status: Status, *, simulated: bool) -> str:
    """Apply one status event; returns the inbound event status (``done``, ``pending_match`` or ``ignored``)."""
    message = _match(uow, event.account_id, status)
    if message is None:
        return "pending_match"
    provider_ts = status.provider_ts or uow.now()
    applied = _raises(message, status.status)
    row = pg_insert(MessageStatusEvent).values(
        id=uuid.uuid7(), company_id=uow.actor.company_id, account_id=event.account_id, message_id=message.id,
        provider_message_id=status.id, status=status.status[:20], provider_ts=provider_ts,
        errors=[e.model_dump(exclude_none=True) for e in status.errors] or None, pricing=status.pricing,
        biz_opaque=(status.biz_opaque_callback_data or None) and status.biz_opaque_callback_data[:200], simulated=simulated,
        applied=applied, created_at=uow.now(),
    ).on_conflict_do_nothing(index_elements=["account_id", "provider_message_id", "status", "provider_ts"])
    inserted = uow.session.execute(row.returning(MessageStatusEvent.id)).first()
    if inserted is None:
        return "done"  # a replayed status: no second business effect
    outbox = uow.session.get(OutboxMessage, message.outbox_id) if message.outbox_id else None
    if applied:
        if status.status == "failed":
            message.status = "failed"
            if outbox is not None and outbox.state in ("accepted", "unknown", "sending", "escalated"):
                outbox.state = "failed"
                error = status.errors[0] if status.errors else None
                outbox.last_error = (f"{error.code} {error.title or ''}".strip() if error else "failed")[:300]
        else:
            message.status = status.status
            message.status_rank = STATUS_RANK[status.status]
            message.status_provider_ts = provider_ts
            # provider evidence resolves an unknown outcome: the message did go out
            if outbox is not None and outbox.state in ("unknown", "sending", "escalated"):
                outbox.state = "accepted"
        message.simulated = message.simulated or simulated
        uow.emit(
            ev.MESSAGE_STATUS_CHANGED, aggregate_id=message.id,
            payload=ev.payload(ev.StatusChangedPayload(message_id=message.id, outbox_id=message.outbox_id, status=message.status, simulated=simulated)),
        )
    return "done"


def _raises(message: ChannelMessage, status: str) -> bool:
    if status == "failed":
        return message.status != "failed" and message.status_rank < FAILED_BELOW_RANK
    rank = STATUS_RANK.get(status)
    if rank is None:  # deleted, warning: kept as evidence, never applied
        return False
    if message.status == "failed":
        return False
    return rank > message.status_rank


# ---- the sweep ---------------------------------------------------------------------------------------------------
def escalate_unknown(uow: UnitOfWork, now: datetime) -> int:
    rows = list(uow.session.scalars(
        select(OutboxMessage).where(
            OutboxMessage.company_id == uow.actor.company_id, OutboxMessage.state == "unknown", OutboxMessage.sent_at <= now - UNKNOWN_ESCALATION,
        ).with_for_update(skip_locked=True)
    ))
    for outbox in rows:
        outbox.state = "escalated"
        outbox.escalated_at = now
        uow.emit(ev.MESSAGE_DELIVERY_UNKNOWN, aggregate_id=outbox.message_id or outbox.id,
                 payload=ev.payload(ev.DeliveryUnknownPayload(message_id=outbox.message_id or outbox.id, outbox_id=outbox.id)))
        _escalation_task(uow, outbox)
        uow.audit("channels.outbox.escalated", resource_type="channels.outbox_message", resource_id=outbox.id, outcome="failed",
                  details={"reason": "delivery_unknown"})
    return len(rows)


def _owner_of(uow: UnitOfWork, outbox: OutboxMessage) -> uuid.UUID | None:
    identity = uow.session.get(ChannelIdentity, outbox.identity_id)
    if identity is not None and identity.user_id is not None:
        return identity.user_id
    if outbox.proposal_id is not None:
        from app.modules.approvals.models import Proposal

        proposal = uow.session.get(Proposal, outbox.proposal_id)
        if proposal is not None:
            return proposal.requested_by
    return None


def _escalation_task(uow: UnitOfWork, outbox: OutboxMessage) -> None:
    """An Inbox task for the owner, written after the escalation commits, in the owner's own context: the outcome
    is unknown, so only a person may decide to resend (as a new message, with confirmation)."""
    owner = _owner_of(uow, outbox)
    company_id = uow.actor.company_id
    if owner is None or company_id is None:
        return
    outbox_id = outbox.id
    uow.after_commit(lambda: create_escalation_task(company_id, owner, outbox_id))


def create_escalation_task(company_id: uuid.UUID, owner: uuid.UUID, outbox_id: uuid.UUID) -> None:
    from app.modules.tasks import service as tasks
    from app.modules.tasks.schemas import TaskCreate
    from app.platform.authz.actors import actor_for_member

    try:
        member = actor_for_member(company_id, owner, channel="job")
        with UnitOfWork(member) as uow:
            tasks.create_task(uow, TaskCreate(
                title="WhatsApp message delivery unknown: check, then resend as a new message if needed",
                note=f"Open Settings > WhatsApp to resend (outbox {str(outbox_id)[-8:]}). Nothing was resent automatically.",
            ), origin="automation")
    except Exception as exc:  # an inactive owner or a task error never loses the escalation (the admin list shows it)
        log.warning("channels.escalation_task_failed", outbox_id=str(outbox_id), error=type(exc).__name__)


def retry_pending_match(uow: UnitOfWork, now: datetime) -> tuple[int, int]:
    from app.modules.channels.whatsapp.payloads import Status as StatusModel

    matched = gave_up = 0
    rows = list(uow.session.scalars(
        select(InboundEvent).where(InboundEvent.company_id == uow.actor.company_id, InboundEvent.status == "pending_match")
        .order_by(InboundEvent.created_at).limit(200).with_for_update(skip_locked=True)
    ))
    for event in rows:
        status = StatusModel.model_validate(event.payload)
        outcome = apply_status(uow, event, status, simulated=event.simulated)
        if outcome == "done":
            event.status, event.processed_at = "done", now
            matched += 1
        elif event.created_at <= now - PENDING_MATCH_GIVE_UP:
            event.status, event.error = "ignored", "no matching message after 1 hour"
            gave_up += 1
    return matched, gave_up


def requeue_due(uow: UnitOfWork, now: datetime) -> int:
    rows = list(uow.session.scalars(
        select(OutboxMessage).where(
            OutboxMessage.company_id == uow.actor.company_id, OutboxMessage.state == "pending", OutboxMessage.next_attempt_at <= now,
        ).limit(200)
    ))
    for outbox in rows:
        enqueue_send(uow, outbox)
    return len(rows)


def sweep(company_id: uuid.UUID) -> dict[str, int]:
    with UnitOfWork(ActorContext.system(company_id, reason="channels.reconcile")) as uow:
        now = uow.now()
        escalated = escalate_unknown(uow, now)
        matched, gave_up = retry_pending_match(uow, now)
        requeued = requeue_due(uow, now)
    return {"escalated": escalated, "matched": matched, "gave_up": gave_up, "requeued": requeued}


def reconcile_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.channels.whatsapp.accounts import active_company_ids

    totals: dict[str, int] = {}
    companies = [uuid.UUID(str(payload["company_id"]))] if payload.get("company_id") else active_company_ids()
    for company_id in companies:
        for key, value in sweep(company_id).items():
            totals[key] = totals.get(key, 0) + value
    return totals


__all__ = ["PENDING_MATCH_GIVE_UP", "UNKNOWN_ESCALATION", "apply_status", "escalate_unknown", "reconcile_job", "retry_pending_match", "sweep"]
