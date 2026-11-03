"""Customers on WhatsApp (design §15 "Customers and vendors") and the approved quote send.

A customer's message becomes a ``sales_customer_message`` for the owner's Inbox (external content) and never gets
an AI reply. ``prepare_quote_send`` binds recipient, text and the PDF hash into a ``channels.message.send``
proposal; nothing is queued until another person approves; the approved send re-renders the issued revision,
checks the hash, uploads the document and sends it — inside the 24-hour window only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.core.clock import FrozenClock
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.approvals import service as approvals
from app.modules.approvals.models import Proposal, ProposalDecision
from app.modules.channels.models import ChannelIdentity, OutboxMessage
from app.modules.channels.tools import PrepareQuoteSendInput, prepare_quote_send
from app.modules.parties.models import PartyContact
from app.modules.sales.models import CustomerMessage, Quote
from app.modules.voice import readback
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.channels.conftest import WhatsApp
from tests.support import drain

pytestmark = pytest.mark.db

LENA = "4915112345678"


@pytest.fixture
def nordhaus(wa: WhatsApp, world: World, sales_tools: object) -> World:
    """The sales world with a WhatsApp number on Nordhaus's primary contact."""
    with UnitOfWork(wa.system()) as uow:
        party_id = world.ref("NORDHAUS")
        uow.session.execute(update(PartyContact).where(PartyContact.party_id == party_id).values(phone=f"+{LENA}"))
    return world


def _quote(wa: WhatsApp, number: str) -> Quote:
    with UnitOfWork(wa.system()) as uow:
        quote = uow.session.scalars(select(Quote).where(Quote.quote_number == number)).one()
        uow.session.expunge(quote)
        return quote


def test_customer_message_goes_to_the_owners_inbox_without_an_ai_reply(wa: WhatsApp, nordhaus: World) -> None:
    wa.text(LENA, "Please send me the updated tray quote")
    with UnitOfWork(wa.system()) as uow:
        identity = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == LENA)).one()
        recorded = uow.session.scalars(select(CustomerMessage).where(CustomerMessage.party_id == nordhaus.ref("NORDHAUS"), CustomerMessage.channel == "whatsapp")).all()
    assert identity.kind == "customer" and identity.user_id is None and identity.party_id == nordhaus.ref("NORDHAUS")
    assert len(recorded) == 1 and recorded[0].body == "Please send me the updated tray quote"
    assert recorded[0].origin_ref and recorded[0].origin_ref.startswith("channels.message:")
    inbound = wa.messages(identity.id, "inbound")
    assert inbound[0]["provenance"] == "external" and inbound[0]["run_id"] is None
    assert wa.messages(identity.id, "outbound") == []  # no autonomous reply to a customer


def test_quote_send_needs_another_persons_approval_then_sends_the_bound_pdf(wa: WhatsApp, nordhaus: World) -> None:
    wa.text(LENA, "Can you send the quote here?")  # opens the 24-hour window
    quote = _quote(wa, keys.QUOTES.PRIOR_WON)
    with UnitOfWork(wa.actor(keys.USERS.MEERA)) as uow:
        prepared = prepare_quote_send(uow, PrepareQuoteSendInput(quote_id=quote.id))
    assert prepared.status == "pending" and prepared.recipient_masked.endswith(LENA[-4:]) and prepared.filename.endswith(".pdf")
    with UnitOfWork(wa.system()) as uow:
        assert uow.session.scalars(select(OutboxMessage).where(OutboxMessage.proposal_id == prepared.proposal_id)).first() is None
        proposal = uow.session.get(Proposal, prepared.proposal_id)
        assert proposal is not None and proposal.facts["document_sha256"] == prepared.document_sha256
        content_hash, version = proposal.content_hash, proposal.version
    with pytest.raises(Forbidden), UnitOfWork(wa.actor(keys.USERS.MEERA)) as uow:
        approvals.decide(uow, prepared.proposal_id, decision="approve", content_hash_seen=content_hash, expected_version=version)
    with UnitOfWork(wa.actor(keys.USERS.SAHIL)) as uow:
        decided = approvals.decide(uow, prepared.proposal_id, decision="approve", content_hash_seen=content_hash, expected_version=version)
        assert decided.status == "approved"
    drain()
    with UnitOfWork(wa.system()) as uow:
        outbox = uow.session.scalars(select(OutboxMessage).where(OutboxMessage.proposal_id == prepared.proposal_id)).one()
        assert outbox.kind == "media" and outbox.purpose == "transactional" and outbox.state == "accepted"
        assert outbox.payload["document_sha256"] == prepared.document_sha256 and outbox.payload["revision_id"]
        assert outbox.provider_message_id and outbox.provider_message_id.startswith("wamid.demo.")


def test_a_voice_approval_of_the_quote_send_needs_a_fresh_readback(wa: WhatsApp, nordhaus: World) -> None:
    """Slice-3 stage-2 merge (voice-vision request 2): an approval spoken to the assistant names the quote out loud
    first — ``approvals.decide(channel="voice")`` calls ``voice.readback.require_presented_readback`` per readable
    target and records ``decided_via = voice``; the read-back is consumed by that one approval."""
    wa.text(LENA, "Can you send the quote here?")
    quote = _quote(wa, keys.QUOTES.PRIOR_WON)
    with UnitOfWork(wa.actor(keys.USERS.MEERA)) as uow:
        prepared = prepare_quote_send(uow, PrepareQuoteSendInput(quote_id=quote.id))
    with UnitOfWork(wa.system()) as uow:
        proposal = uow.session.get(Proposal, prepared.proposal_id)
        assert proposal is not None
        content_hash, version = proposal.content_hash, proposal.version

    def decide() -> Proposal:
        with UnitOfWork(wa.actor(keys.USERS.SAHIL)) as uow:
            return approvals.decide(uow, prepared.proposal_id, decision="approve", content_hash_seen=content_hash,
                                    expected_version=version, channel="voice")

    with pytest.raises(Conflict) as refused:
        decide()
    assert refused.value.code == "readback_required" and refused.value.extra["reason"] == "missing"
    with UnitOfWork(wa.actor(keys.USERS.SAHIL)) as uow:
        readback.present(uow, "sales.quote", quote.id)
    assert decide().status == "approved"
    with UnitOfWork(wa.system()) as uow:
        decision = uow.session.scalars(select(ProposalDecision).where(ProposalDecision.proposal_id == prepared.proposal_id)).one()
        assert decision.decided_via == "voice" and decision.decision == "approve"


def test_quote_send_outside_the_window_is_blocked_with_the_reason(wa: WhatsApp, nordhaus: World, frozen_clock: FrozenClock) -> None:
    wa.text(LENA, "Hello")
    frozen_clock.advance(hours=26)
    quote = _quote(wa, keys.QUOTES.PRIOR_WON)
    with UnitOfWork(wa.actor(keys.USERS.MEERA)) as uow:
        prepared = prepare_quote_send(uow, PrepareQuoteSendInput(quote_id=quote.id))
    with UnitOfWork(wa.actor(keys.USERS.SAHIL)) as uow:
        proposal = uow.session.get(Proposal, prepared.proposal_id)
        assert proposal is not None
        approvals.decide(uow, proposal.id, decision="approve", content_hash_seen=proposal.content_hash, expected_version=proposal.version)
    drain()
    with UnitOfWork(wa.system()) as uow:
        outbox = uow.session.scalars(select(OutboxMessage).where(OutboxMessage.proposal_id == prepared.proposal_id)).one()
    assert (outbox.state, outbox.blocked_reason) == ("blocked", "window_closed")


def test_a_draft_quote_cannot_be_prepared_for_sending(wa: WhatsApp, nordhaus: World) -> None:
    draft = _quote(wa, keys.QUOTES.NORDHAUS_DRAFT)
    with pytest.raises(ValidationFailed) as error, UnitOfWork(wa.actor(keys.USERS.MEERA)) as uow:
        prepare_quote_send(uow, PrepareQuoteSendInput(quote_id=draft.id))
    assert error.value.code == "quote_not_issued"


def test_customer_stop_opts_out_with_a_confirmation(wa: WhatsApp, nordhaus: World) -> None:
    wa.text(LENA, "STOP")
    with UnitOfWork(wa.system()) as uow:
        identity = uow.session.scalars(select(ChannelIdentity).where(ChannelIdentity.wa_id == LENA)).one()
        from app.modules.channels.whatsapp import consent

        state = consent.current(uow, identity.id)
    assert state == {"daily_briefing": "opted_out", "marketing": "opted_out"}
    assert "Reply START" in wa.replies(identity.id)[-1]
