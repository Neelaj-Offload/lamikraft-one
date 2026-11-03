"""Scenario K (docs/PLAN.md): WhatsApp safety rules with fixtures.

Out-of-order statuses never lower the rank and ``failed`` never overrides delivered; a status that beats the send
response matches through ``biz_opaque_callback_data``; employee unlink revokes the session and voids armed
buttons; a button for an expired approval does nothing; STOP opts out with a confirmation and blocks proactive
messages; a closed 24-hour window blocks with a reason; simulated statuses are labelled and only provider
evidence moves a message beyond ``accepted``; an unknown outcome is never resent and escalates after 15 minutes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.clock import FrozenClock
from app.modules.approvals import service as approvals
from app.modules.channels import action_refs
from app.modules.channels.models import ActionRef, ChannelSession, MessageStatusEvent, OutboxMessage
from app.modules.channels.whatsapp import outbound, reconcile
from app.modules.channels.whatsapp.demo_provider import DemoProvider
from app.modules.channels.whatsapp.provider import SendResult, set_provider_override
from app.platform.uow import UnitOfWork
from tests.integration.channels.conftest import WhatsApp, unix
from tests.support import drain

pytestmark = pytest.mark.db


class _Scripted(DemoProvider):
    """The Demo provider with a scripted send outcome and no simulated statuses."""

    def __init__(self, result: SendResult) -> None:
        super().__init__()
        self.result = result
        self.sent: list[dict] = []

    def send(self, account, to, body, *, biz_opaque):  # type: ignore[no-untyped-def]
        self.sent.append({"to": to, "body": body, "biz_opaque": biz_opaque})
        return self.result

    def simulate_statuses(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture
def scripted() -> object:
    def install(result: SendResult) -> _Scripted:
        provider = _Scripted(result)
        set_provider_override(provider)
        return provider

    yield install
    set_provider_override(None)


def _queue(wa: WhatsApp, identity_id: uuid.UUID, text: str, *, purpose: str = "assistant_replies", key: str | None = None) -> uuid.UUID:
    with UnitOfWork(wa.system()) as uow:
        from app.modules.channels.models import ChannelIdentity

        identity = uow.session.get(ChannelIdentity, identity_id)
        assert identity is not None
        row = outbound.queue_message(uow, identity, kind="session", payload={"type": "text", "text": text}, text=text, purpose=purpose,
                                     idempotency_key=key or f"test:{uuid.uuid4().hex}")
        return row.id


def _outbox(wa: WhatsApp, outbox_id: uuid.UUID) -> OutboxMessage:
    with UnitOfWork(wa.system()) as uow:
        row = uow.session.get(OutboxMessage, outbox_id)
        assert row is not None
        uow.session.expunge(row)
        return row


def test_k_simulated_statuses_are_labelled_and_reach_read_through_the_webhook(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    outbox_id = _queue(wa, identity.id, "hello")
    drain()
    sent = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == outbox_id)
    assert sent["wamid"].startswith("wamid.demo.") and sent["simulated"] is True
    assert sent["status"] == "read" and sent["rank"] == 4 and sent["body"].startswith("Demo:") is False  # raw text queued as given
    with UnitOfWork(wa.system()) as uow:
        events = list(uow.session.scalars(select(MessageStatusEvent).where(MessageStatusEvent.provider_message_id == sent["wamid"]).order_by(MessageStatusEvent.provider_ts)))
    assert [e.status for e in events] == ["sent", "delivered", "read"] and all(e.simulated for e in events)


def test_k_out_of_order_status_never_lowers_the_rank_and_failed_does_not_override_delivered(wa: WhatsApp, scripted) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    scripted(SendResult(outcome="accepted", wamid="wamid.REAL.1", http_status=200))
    outbox_id = _queue(wa, identity.id, "status test")
    drain()
    base = unix(wa.now())
    wa.statuses("wamid.REAL.1", wa.wa_id("MEERA"), [("read", base + 30)])
    wa.statuses("wamid.REAL.1", wa.wa_id("MEERA"), [("delivered", base + 20), ("sent", base + 10)])
    wa.statuses("wamid.REAL.1", wa.wa_id("MEERA"), [("failed", base + 40)])
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == outbox_id)
    assert message["status"] == "read" and message["rank"] == 4
    with UnitOfWork(wa.system()) as uow:
        kept = list(uow.session.scalars(select(MessageStatusEvent.status).where(MessageStatusEvent.provider_message_id == "wamid.REAL.1")))
    assert sorted(kept) == ["delivered", "failed", "read", "sent"]  # every event is kept
    assert _outbox(wa, outbox_id).state == "accepted"


def test_k_failed_applies_below_delivered(wa: WhatsApp, scripted) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    scripted(SendResult(outcome="accepted", wamid="wamid.REAL.2", http_status=200))
    outbox_id = _queue(wa, identity.id, "will fail")
    drain()
    wa.statuses("wamid.REAL.2", wa.wa_id("MEERA"), [("sent", unix(wa.now()) + 1)])
    wa.statuses("wamid.REAL.2", wa.wa_id("MEERA"), [("failed", unix(wa.now()) + 2)])
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == outbox_id)
    assert message["status"] == "failed"
    assert _outbox(wa, outbox_id).state == "failed"


def test_status_before_the_send_response_matches_by_biz_opaque(wa: WhatsApp, scripted) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    provider = scripted(SendResult(outcome="unknown", error_title="timeout"))
    outbox_id = _queue(wa, identity.id, "race")
    drain()
    assert _outbox(wa, outbox_id).state == "unknown" and len(provider.sent) == 1
    # Meta did process it: the status carries our outbox id even though we never learnt the wamid
    wa.statuses("wamid.LATE.1", wa.wa_id("MEERA"), [("delivered", unix(wa.now()) + 5)], biz_opaque=str(outbox_id))
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == outbox_id)
    assert message["status"] == "delivered" and message["wamid"] == "wamid.LATE.1"
    assert _outbox(wa, outbox_id).state == "accepted"  # provider evidence resolved the unknown outcome
    assert len(provider.sent) == 1  # never resent


def test_unmatched_status_is_pending_match_until_the_message_exists(wa: WhatsApp) -> None:
    wa.enrol("MEERA")
    wa.statuses("wamid.NOWHERE", wa.wa_id("MEERA"), [("sent", unix(wa.now()))])
    from app.modules.channels.models import InboundEvent

    with UnitOfWork(wa.system()) as uow:
        event = uow.session.scalars(select(InboundEvent).where(InboundEvent.provider_event_key.like("wamid.NOWHERE:%"))).one()
        assert event.status == "pending_match"
    result = reconcile.sweep(wa.company_id)
    assert result["matched"] == 0


def test_k_unknown_outcome_is_never_resent_and_escalates_after_15_minutes(wa: WhatsApp, scripted, frozen_clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    provider = scripted(SendResult(outcome="unknown", error_title="ReadTimeout"))
    outbox_id = _queue(wa, identity.id, "maybe sent")
    drain()
    assert _outbox(wa, outbox_id).state == "unknown"
    frozen_clock.advance(minutes=14)
    assert reconcile.sweep(wa.company_id)["escalated"] == 0
    frozen_clock.advance(minutes=2)
    assert reconcile.sweep(wa.company_id)["escalated"] == 1
    drain()
    assert len(provider.sent) == 1  # nothing was resent automatically
    row = _outbox(wa, outbox_id)
    assert row.state == "escalated" and row.escalated_at is not None
    from app.modules.tasks.models import Task
    from app.platform.events.models import DomainEvent

    with UnitOfWork(wa.system()) as uow:
        tasks = list(uow.session.scalars(select(Task).where(Task.owner_user_id == wa.world.user_id("MEERA"), Task.title.like("WhatsApp message delivery unknown%"))))
        unknown = uow.session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.event_type == "channels.message.delivery_unknown"))
    assert len(tasks) == 1 and unknown == 1


def test_resend_as_new_message_needs_confirmation_and_a_new_key(wa: WhatsApp, scripted, frozen_clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    from app.core.errors import ValidationFailed
    from app.modules.channels import service
    from app.modules.channels.schemas import OutboxResolve

    identity = wa.enrol("MEERA")
    provider = scripted(SendResult(outcome="unknown", error_title="timeout"))
    outbox_id = _queue(wa, identity.id, "resend me")
    drain()
    frozen_clock.advance(minutes=16)
    reconcile.sweep(wa.company_id)
    provider.result = SendResult(outcome="accepted", wamid="wamid.RESENT", http_status=200)
    with pytest.raises(ValidationFailed):
        with UnitOfWork(wa.actor("MEERA")) as uow:
            service.resolve_outbox(uow, outbox_id, OutboxResolve(action="resend", confirm=False))
    with UnitOfWork(wa.actor("MEERA")) as uow:
        new = service.resolve_outbox(uow, outbox_id, OutboxResolve(action="resend", confirm=True))
    drain()
    old, fresh = _outbox(wa, outbox_id), _outbox(wa, new.id)
    assert fresh.resend_of_id == outbox_id and fresh.idempotency_key != old.idempotency_key
    assert fresh.state == "accepted" and old.state == "cancelled" and len(provider.sent) == 2


def test_k_employee_unlink_revokes_the_session_and_voids_armed_buttons(wa: WhatsApp) -> None:
    from app.modules.channels import service

    identity = wa.enrol("MEERA")
    with UnitOfWork(wa.system()) as uow:
        ref = action_refs.arm(uow, user_id=wa.world.user_id("MEERA"), identity_id=identity.id, action="open", option_payload={"kind": "open", "path": "/today"})
        nonce = ref.nonce
    with UnitOfWork(wa.actor("MEERA")) as uow:
        service.revoke(uow, identity.id)
    with UnitOfWork(wa.system()) as uow:
        sessions = list(uow.session.scalars(select(ChannelSession).where(ChannelSession.identity_id == identity.id)))
        voided = uow.session.scalars(select(ActionRef).where(ActionRef.nonce == nonce)).one()
    assert sessions and all(s.revoked_at is not None for s in sessions)
    assert voided.voided_at is not None
    # the unlinked number is a stranger now: generic reply, no tools, no data
    wa.text(wa.wa_id("MEERA"), "show my quotes")
    replies = wa.replies(identity.id)
    assert "not linked" in replies[-1] and all(m["run_id"] is None for m in wa.messages(identity.id))
    wa.button(wa.wa_id("MEERA"), f"a:{nonce}")
    assert "not linked" in wa.replies(identity.id)[-1] or wa.replies(identity.id)[-1] == replies[-1]


def test_deactivation_revokes_through_the_event(wa: WhatsApp) -> None:
    wa.enrol("NEHA")
    with UnitOfWork(wa.system()) as uow:
        uow.emit("identity.membership.deactivated", aggregate_id=uuid.uuid7(),
                 payload={"membership_id": str(uuid.uuid7()), "user_id": str(wa.world.user_id("NEHA"))})
    drain()
    assert wa.identity("NEHA").status == "revoked"  # type: ignore[union-attr]


def test_k_button_for_an_expired_approval_does_nothing(wa: WhatsApp, frozen_clock: FrozenClock) -> None:
    from app.modules.approvals.models import Proposal

    identity = wa.enrol("SAHIL")
    with UnitOfWork(wa.system()) as uow:
        proposal = Proposal(kind="channels.message.send", status="pending", title="Send LK-QT test", content_hash="h" * 64, policy_key="t",
                            required_permission="channels.message.send", requested_by=wa.world.user_id("MEERA"), requested_via="web",
                            expires_at=wa.now() + timedelta(minutes=5), facts={})
        uow.add(proposal)
        uow.flush()
        ref = action_refs.arm(uow, user_id=wa.world.user_id("SAHIL"), identity_id=identity.id, action="approve", proposal_id=proposal.id,
                              content_hash=proposal.content_hash, option_payload={"kind": "approve"})
        nonce, proposal_id = ref.nonce, proposal.id
    frozen_clock.advance(minutes=6)
    with UnitOfWork(wa.system()) as uow:
        approvals.expire_due(uow)
    drain()
    wa.button(wa.wa_id("SAHIL"), f"a:{nonce}")
    assert wa.replies(identity.id)[-1].endswith("Nothing was done.")
    with UnitOfWork(wa.system()) as uow:
        assert uow.session.get(Proposal, proposal_id).status == "expired"  # type: ignore[union-attr]


def test_k_opt_out_confirms_and_blocks_proactive_messages_but_not_replies(wa: WhatsApp) -> None:
    identity = wa.enrol("MEERA")
    with UnitOfWork(wa.system()) as uow:
        from app.modules.channels.models import ChannelIdentity
        from app.modules.channels.whatsapp import consent

        consent.record(uow, uow.session.get(ChannelIdentity, identity.id), "daily_briefing", "opted_in", source="test")  # type: ignore[arg-type]
    wa.text(wa.wa_id("MEERA"), "band karo")
    assert "Proactive messages are off" in wa.replies(identity.id)[-1]
    briefing = _queue(wa, identity.id, "Your day", purpose="daily_briefing")
    reply = _queue(wa, identity.id, "Answer to your question", purpose="assistant_replies")
    drain()
    blocked = _outbox(wa, briefing)
    assert blocked.state == "blocked" and blocked.blocked_reason == "consent_opted_out"
    assert _outbox(wa, reply).state == "accepted"


def test_k_closed_window_blocks_with_a_reason(wa: WhatsApp, frozen_clock: FrozenClock) -> None:
    identity = wa.enrol("MEERA")
    frozen_clock.advance(hours=25)
    outbox_id = _queue(wa, identity.id, "too late for a session message")
    drain()
    row = _outbox(wa, outbox_id)
    assert row.state == "blocked" and row.blocked_reason == "window_closed"
    message = next(m for m in wa.messages(identity.id, "outbound") if m["outbox_id"] == outbox_id)
    assert message["status"] == "blocked"


def test_closed_window_with_an_approved_template_sends_and_paused_blocks(wa: WhatsApp, frozen_clock: FrozenClock) -> None:
    from app.modules.channels.models import ChannelIdentity
    from app.modules.channels.whatsapp import consent, templates

    identity = wa.enrol("MEERA")
    with UnitOfWork(wa.actor("PRIYA")) as uow:
        templates.sync(uow)
    with UnitOfWork(wa.system()) as uow:
        from app.modules.channels.whatsapp import accounts

        account = accounts.ensure_account(uow)  # never open a second unit of work inside this one
        row = uow.session.get(ChannelIdentity, identity.id)
        consent.record(uow, row, "daily_briefing", "opted_in", source="test")  # type: ignore[arg-type]
        approved = templates.find_sendable(uow, account, "lk_daily_briefing")
        paused = templates.find_sendable(uow, account, "lk_followup_offer")
        ids = []
        for template in (approved, paused):
            assert template is not None
            ids.append(outbound.queue_message(uow, row, kind="template", payload={"type": "template", "name": template.name, "language": "en", "components": []},  # type: ignore[arg-type]
                                              text=None, purpose="daily_briefing", idempotency_key=f"tpl:{template.name}", template_id=template.id).id)
    frozen_clock.advance(hours=30)
    drain()
    assert _outbox(wa, ids[0]).state == "accepted"
    assert (_outbox(wa, ids[1]).state, _outbox(wa, ids[1]).blocked_reason) == ("blocked", "template_paused")


def test_throttle_backs_off_and_the_sweep_requeues_when_due(wa: WhatsApp, scripted, frozen_clock: FrozenClock) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    provider = scripted(SendResult(outcome="throttle", http_status=429, error_code=130429, retry_after_seconds=60))
    outbox_id = _queue(wa, identity.id, "busy")
    drain()
    row = _outbox(wa, outbox_id)
    assert row.state == "pending" and row.attempts == 1 and row.next_attempt_at > wa.now()
    assert reconcile.sweep(wa.company_id)["requeued"] == 0
    provider.result = SendResult(outcome="accepted", wamid="wamid.AFTER.THROTTLE", http_status=200)
    frozen_clock.advance(seconds=61)
    assert reconcile.sweep(wa.company_id)["requeued"] == 1
    drain()
    assert _outbox(wa, outbox_id).state == "accepted" and len(provider.sent) == 2


def test_validation_error_fails_without_retry(wa: WhatsApp, scripted) -> None:  # type: ignore[no-untyped-def]
    identity = wa.enrol("MEERA")
    provider = scripted(SendResult(outcome="failed", http_status=400, error_code=131009, error_title="Invalid parameter value"))
    outbox_id = _queue(wa, identity.id, "bad")
    drain()
    row = _outbox(wa, outbox_id)
    assert row.state == "failed" and "131009" in (row.last_error or "") and len(provider.sent) == 1
