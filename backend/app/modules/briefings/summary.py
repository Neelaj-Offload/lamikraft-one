"""The daily WhatsApp summary and cross-channel acknowledgements (design §14).

``send_summary(member, work_date)`` builds one short message from the member's **visible** briefing (counts, the
overview sentence and at most three titles within the channel's sensitivity limit) and hands it to a
``SummaryChannel``. It goes out only when every gate passes, checked here first so the reason is recorded and
audited, and again by the channels sender (defence in depth):

- a working day (no push on non-working days, holidays or leave);
- an active, linked employee identity with a live channel session;
- explicit opt-in for the ``daily_briefing`` purpose (STOP opts out);
- the 24-hour service window (an interactive message with "Got it" / "Open Today"), or else an approved UTILITY
  template (``lk_daily_briefing``).

One ``briefings_summary_push`` row per member and work date makes the job idempotent. "Got it" acknowledges the
version that was summarised as the member (method ``whatsapp``, idempotent on the inbound message id); an
acknowledgement on the web marks the summary acknowledged here and ``channels.ack_sync`` voids the armed buttons,
so neither channel asks again.

``SummaryChannel`` is the narrow seam: ``ChannelsSummaryChannel`` uses the channels module's real outbox
(``outbound.queue_message(purpose="daily_briefing")``); ``RecordingSummaryChannel`` records what would be sent for
tests that need no WhatsApp account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from sqlalchemy import select

from app.core.logging import get_logger
from app.modules.briefings.models import SummaryOutcome, SummaryPush
from app.platform.uow import UnitOfWork

log = get_logger("lk.briefings.summary")

PURPOSE = "daily_briefing"
TEMPLATE_NAME = "lk_daily_briefing"
TOP_TITLES = 3
#: families whose titles never travel to WhatsApp (design §12: costing, margin and finance stay on the web)
SENSITIVE_FAMILY_PREFIXES = ("finance.", "costing.", "sales.commercial_exceptions")
ACK_BUTTON_KIND = "briefing_ack"
OPEN_BUTTON_KIND = "review"
TARGET_TYPE = "briefings.briefing"


@dataclass(frozen=True)
class SummaryMessage:
    briefing_id: uuid.UUID
    version: int
    work_date: date
    text: str
    #: template parameters when the window is closed: [the date, the overview sentence]
    template_params: tuple[str, ...]
    titles: tuple[str, ...]


@dataclass(frozen=True)
class Target:
    """Where the summary would go: an identity reference and how (``interactive`` inside the window, ``template``
    outside it), or the reason it may not go at all."""

    identity_id: uuid.UUID | None
    kind: str | None
    reason: str | None
    template_id: uuid.UUID | None = None
    simulated: bool = False


@dataclass(frozen=True)
class Sent:
    outbox_id: uuid.UUID
    message_id: uuid.UUID | None


class SummaryChannel(Protocol):
    def target(self, uow: UnitOfWork, user_id: uuid.UUID) -> Target: ...

    def send(self, uow: UnitOfWork, user_id: uuid.UUID, target: Target, message: SummaryMessage) -> Sent: ...


# ---- the real channel (channels outbox) ---------------------------------------------------------------------------
class ChannelsSummaryChannel:
    """The channels module's WhatsApp outbox. The sender re-checks every gate before the provider call."""

    def target(self, uow: UnitOfWork, user_id: uuid.UUID) -> Target:
        from app.modules.channels.models import ChannelAccount, ChannelIdentity
        from app.modules.channels.whatsapp import consent, templates, window
        from app.modules.channels.whatsapp import identity as identities

        identity = uow.session.scalars(
            select(ChannelIdentity).where(
                ChannelIdentity.company_id == uow.actor.company_id, ChannelIdentity.user_id == user_id,
                ChannelIdentity.kind == "employee", ChannelIdentity.status == "active",
            ).order_by(ChannelIdentity.created_at.desc())
        ).first()
        if identity is None:
            return Target(None, None, "not_linked")
        now = uow.now()
        if not identities.is_authorised(uow, identity, now):
            return Target(identity.id, None, "session_expired")
        allowed, reason = consent.allows(uow, identity.id, PURPOSE)
        if not allowed:
            return Target(identity.id, None, reason or "consent_missing")
        account = uow.session.get(ChannelAccount, identity.account_id)
        simulated = account is not None and account.mode == "demo"
        if window.window_open(identity, now):
            return Target(identity.id, "interactive", None, simulated=simulated)
        template = templates.find_sendable(uow, account, TEMPLATE_NAME) if account is not None else None
        _row, block = window.template_check(uow, template.id if template else None)
        if template is None or block:
            return Target(identity.id, None, block or "template_missing")
        if template.category.upper() != "UTILITY":
            return Target(identity.id, None, "template_not_utility")
        return Target(identity.id, "template", None, template_id=template.id, simulated=simulated)

    def send(self, uow: UnitOfWork, user_id: uuid.UUID, target: Target, message: SummaryMessage) -> Sent:
        from app.modules.channels import action_refs
        from app.modules.channels.models import ChannelIdentity
        from app.modules.channels.whatsapp import outbound
        from app.modules.channels.whatsapp.render import plain

        identity = uow.session.get(ChannelIdentity, target.identity_id)
        assert identity is not None and identity.user_id == user_id
        key = f"briefings.summary:{message.briefing_id}:{message.work_date.isoformat()}"
        cause = f"briefings.briefing:{message.briefing_id}"
        if target.kind == "template":
            components = [{"type": "body", "parameters": [{"type": "text", "text": p[:900]} for p in message.template_params]}]
            text = plain(f"Your briefing for {message.template_params[0]}: {message.template_params[1]}", demo=target.simulated)
            outbox = outbound.queue_message(
                uow, identity, kind="template", payload={"type": "template", "name": TEMPLATE_NAME, "language": "en", "components": components},
                text=text, purpose=PURPOSE, idempotency_key=key, cause_ref=cause, template_id=target.template_id,
            )
            return Sent(outbox.id, outbox.message_id)
        text = plain(message.text, demo=target.simulated)
        target_data = {"target_type": TARGET_TYPE, "target_id": str(message.briefing_id)}
        got_it = action_refs.arm(
            uow, user_id=user_id, identity_id=identity.id, action="open",
            option_payload={"kind": ACK_BUTTON_KIND, "label": "Got it", "version": message.version, **target_data},
        )
        open_today = action_refs.arm(
            uow, user_id=user_id, identity_id=identity.id, action="open",
            # a fresh, short-lived review link to Today on each press; not voided by an acknowledgement elsewhere
            option_payload={"kind": OPEN_BUTTON_KIND, "label": "Open Today", "target_type": "briefings.today",
                            "target_id": str(message.briefing_id), "path": "/today"},
        )
        buttons = [{"id": action_refs.button_id(got_it), "title": "Got it"}, {"id": action_refs.button_id(open_today), "title": "Open Today"}]
        outbox = outbound.queue_message(
            uow, identity, kind="interactive", payload={"type": "interactive", "text": text, "buttons": buttons},
            text=text, purpose=PURPOSE, idempotency_key=key, cause_ref=cause,
        )
        action_refs.bind_message(uow, [got_it, open_today], outbox.message_id)
        return Sent(outbox.id, outbox.message_id)


@dataclass
class RecordingSummaryChannel:
    """Demo seam: every member is reachable inside the window; sends are recorded, nothing leaves the process."""

    sent: list[tuple[uuid.UUID, SummaryMessage]] = field(default_factory=list)
    reason: str | None = None

    def target(self, uow: UnitOfWork, user_id: uuid.UUID) -> Target:  # noqa: ARG002
        return Target(None, None, self.reason) if self.reason else Target(None, "interactive", None, simulated=True)

    def send(self, uow: UnitOfWork, user_id: uuid.UUID, target: Target, message: SummaryMessage) -> Sent:  # noqa: ARG002
        self.sent.append((user_id, message))
        return Sent(uuid.uuid7(), None)


_CHANNEL: list[SummaryChannel] = [ChannelsSummaryChannel()]


def get_channel() -> SummaryChannel:
    return _CHANNEL[0]


def set_channel(channel: SummaryChannel | None) -> SummaryChannel:
    """Swap the channel (tests); ``None`` restores the channels outbox. Returns the previous one."""
    previous = _CHANNEL[0]
    _CHANNEL[0] = channel if channel is not None else ChannelsSummaryChannel()
    return previous


# ---- content ------------------------------------------------------------------------------------------------------
def _sensitive(family: str) -> bool:
    return family.startswith(SENSITIVE_FAMILY_PREFIXES)


def build_message(view: Any) -> SummaryMessage:
    """Counts, the overview sentence and up to three titles of the visible briefing (``BriefingView``)."""
    day = view.work_date.strftime("%a %d %b").replace(" 0", " ")
    sentence = view.overview.sentence if view.overview is not None else ""
    initial = set(view.initial_view)
    ordered = [i for i in view.items if i.issue_id in initial] + [i for i in view.items if i.issue_id not in initial]
    shareable = [i for i in ordered if not _sensitive(i.family) and i.section in ("needs_you_now", "plan_for_today", "recommendations")]
    top = shareable[:TOP_TITLES]
    lines = [f"Your briefing for {day}. {sentence}".strip()]
    for n, item in enumerate(top, start=1):
        lines.append(f"{n}. {item.title}")
    remaining = len(view.items) - len(top)
    if remaining > 0:
        lines.append(f"{remaining} more on Today.")
    return SummaryMessage(
        briefing_id=view.briefing_id, version=int(view.version), work_date=view.work_date, text="\n".join(lines)[:1000],
        template_params=(day, sentence or "Nothing needs you right now."), titles=tuple(i.title for i in top),
    )


# ---- the job --------------------------------------------------------------------------------------------------------
def existing(uow: UnitOfWork, user_id: uuid.UUID, work_date: date) -> SummaryPush | None:
    return uow.session.scalars(
        select(SummaryPush).where(SummaryPush.company_id == uow.actor.company_id, SummaryPush.user_id == user_id,
                                  SummaryPush.work_date == work_date)
    ).first()


def _record(uow: UnitOfWork, user_id: uuid.UUID, work_date: date, *, outcome: str, reason: str | None = None,
            view: Any = None, kind: str | None = None, sent: Sent | None = None, message: SummaryMessage | None = None,
            simulated: bool = False, row: SummaryPush | None = None) -> SummaryPush:
    """Write (or, after an earlier skip, update) the member's one row for the work date, and audit it."""
    if row is None:
        row = SummaryPush(company_id=uow.actor.company_id, user_id=user_id, work_date=work_date, outcome=outcome)
        uow.add(row)
    row.briefing_id = getattr(view, "briefing_id", None)
    row.version = getattr(view, "version", None)
    row.outcome = outcome
    row.reason = reason
    row.kind = kind
    row.outbox_id = sent.outbox_id if sent else None
    row.message_id = sent.message_id if sent else None
    row.text = message.text if message else None
    row.simulated = simulated
    uow.flush()
    uow.audit(
        "briefings.summary.queued" if outcome == SummaryOutcome.QUEUED.value else "briefings.summary.skipped",
        resource_type="briefings.summary_push", resource_id=row.id, reason=reason,
        details={"user_id": str(user_id), "work_date": work_date.isoformat(), "kind": kind, "version": row.version,
                 "simulated": simulated},
    )
    return row


def send_summary(uow: UnitOfWork, user_id: uuid.UUID, *, channel: SummaryChannel | None = None) -> SummaryPush:
    """One summary for the member's current work date (idempotent). ``uow`` runs as the member."""
    from app.modules.briefings import service
    from app.modules.briefings.models import BriefingTrigger
    from app.modules.tasks import responsibility

    channel = channel or get_channel()
    cal = responsibility.user_calendar(uow, user_id)
    work_date = cal.work_date(uow.now())
    done = existing(uow, user_id, work_date)
    if done is not None and done.outcome == SummaryOutcome.QUEUED.value:
        return done  # one summary per work date
    # a skip is not final: once the member links WhatsApp or opts in, asking again sends it
    if cal.day_type(work_date) != "working":
        return _record(uow, user_id, work_date, outcome=SummaryOutcome.SKIPPED.value, reason="non_working_day", row=done)
    target = channel.target(uow, user_id)
    if target.reason is not None or target.kind is None:
        return _record(uow, user_id, work_date, outcome=SummaryOutcome.SKIPPED.value, reason=target.reason or "not_eligible", row=done)
    view = service.today_view_for(uow, trigger=BriefingTrigger.WHATSAPP.value)
    if view.status != "ready" or view.briefing_id is None or view.version is None:
        return _record(uow, user_id, work_date, outcome=SummaryOutcome.SKIPPED.value, reason="briefing_unavailable", row=done)
    message = build_message(view)
    sent = channel.send(uow, user_id, target, message)
    return _record(uow, user_id, work_date, outcome=SummaryOutcome.QUEUED.value, view=view, kind=target.kind, sent=sent,
                   message=message, simulated=target.simulated, row=done)


def mark_acknowledged(uow: UnitOfWork, user_id: uuid.UUID, briefing_id: uuid.UUID, version: int, *, channel: str) -> None:
    """An acknowledgement (any channel) of the summarised version or a later one marks the summary acknowledged."""
    row = uow.session.scalars(
        select(SummaryPush).where(SummaryPush.company_id == uow.actor.company_id, SummaryPush.user_id == user_id,
                                  SummaryPush.briefing_id == briefing_id, SummaryPush.acknowledged_at.is_(None),
                                  SummaryPush.outcome == SummaryOutcome.QUEUED.value)
    ).first()
    if row is not None and (row.version or 0) <= version:
        row.acknowledged_at = uow.now()
        row.ack_channel = channel
        uow.flush()


def handle_ack_button(uow: UnitOfWork, identity: Any, ref: Any, wamid: str) -> str:
    """"Got it" on the WhatsApp summary: acknowledge the summarised version as the linked member (method
    ``whatsapp``; idempotent on the inbound message id). Returns the reply text."""
    from app.modules.briefings import service
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import view_as

    data = dict(ref.option_payload or {})
    try:
        briefing_id = uuid.UUID(str(data.get("target_id")))
        version = int(data.get("version") or 0)
    except (TypeError, ValueError):
        return "That button is not valid any more. Open Today on the web."
    actor = responsibility.member_actor(uow, identity.user_id)
    if actor is None or not actor.can("briefings.briefing.read"):
        return "That button is not valid any more. Open Today on the web."
    member = view_as(uow, actor.with_(channel="whatsapp", auth_strength="channel_linked"))
    try:
        ack = service.acknowledge(member, briefing_id, version=version, method="whatsapp", channel_message_id=wamid)
    except Exception as exc:  # the briefing is gone or no longer the member's: say so, change nothing
        log.info("briefings.summary_ack_failed", error=type(exc).__name__)
        return "That briefing is no longer available. Open Today on the web."
    if not ack.accepted:
        return "Already marked as seen."
    return "Marked as seen. New changes will be counted from now."


__all__ = [
    "ACK_BUTTON_KIND", "PURPOSE", "TEMPLATE_NAME", "ChannelsSummaryChannel", "RecordingSummaryChannel", "Sent", "SummaryChannel",
    "SummaryMessage", "Target", "build_message", "existing", "get_channel", "handle_ack_button", "mark_acknowledged",
    "send_summary", "set_channel",
]
