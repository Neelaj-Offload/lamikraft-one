"""The sales seed builds fixtures.md §7.1–§7.4 through the services, numbers follow creation order, re-runs are
idempotent."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.modules.approvals import service as approvals
from app.modules.sales import service as sales
from app.modules.sales.models import (
    CustomerMessage,
    Enquiry,
    Quote,
    QuoteLine,
    QuoteRevision,
    QuoteStatusHistory,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from app.seed.world.sales import seed_sales
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
IST = ZoneInfo("Asia/Kolkata")
SAHIL = keys.USERS.SAHIL


def _counts(world: SalesWorld) -> dict[str, int]:
    with world.uow(SAHIL) as uow:
        return {m.__tablename__: int(uow.session.scalar(select(func.count()).select_from(m)) or 0)
                for m in (Enquiry, CustomerMessage, Quote, QuoteLine, QuoteRevision, QuoteStatusHistory, DomainEvent)}


def test_numbers_follow_creation_order_and_facts_match(sales_world: SalesWorld) -> None:
    w = sales_world
    expected = {
        "Q_BERG_WON": (keys.QUOTES.BERG_WON, "won", "5700.00", "EUR", keys.USERS.MEERA, 1),
        "Q_THORNBURY_LOST": (keys.QUOTES.THORNBURY_LOST, "lost", "5250.00", "GBP", keys.USERS.NEHA, 1),
        "PRIOR_WON": (keys.QUOTES.PRIOR_WON, "won", "5760.00", "EUR", keys.USERS.MEERA, 1),
        "Q_THORNBURY_EXPIRING": (keys.QUOTES.THORNBURY_EXPIRING, "sent", "5880.00", "GBP", keys.USERS.NEHA, 1),
        "Q_MAISON_OVERRIDE": (keys.QUOTES.MAISON_OVERRIDE, "internal_review", "5280.00", "EUR", keys.USERS.MEERA, 0),
        "Q_BERG_EXPIRING": (keys.QUOTES.BERG_EXPIRING, "sent", "5700.00", "EUR", keys.USERS.MEERA, 1),
        "Q_THORNBURY_OVERRIDE": (keys.QUOTES.THORNBURY_OVERRIDE, "internal_review", "5850.00", "GBP", keys.USERS.NEHA, 0),
        "Q_NORDHAUS_DRAFT": (keys.QUOTES.NORDHAUS_DRAFT, "internal_review", "5760.00", "EUR", keys.USERS.MEERA, 0),
    }
    for key, (number, status, total, currency, owner, revision_no) in expected.items():
        q = w.quote(SAHIL, key)
        assert (q.quote_number, q.status, str(q.totals.grand_total.amount), q.currency, q.owner.id, q.revision_no) == (
            number, status, total, currency, w.user_id(owner), revision_no), key
    with w.uow(SAHIL) as uow:
        by_number = {n: w for n, w in uow.session.execute(select(Quote.quote_number, Quote.won_at)).all()}
    assert set(by_number) == {getattr(keys.QUOTES, k) for k in ("BERG_WON", "THORNBURY_LOST", "PRIOR_WON", "THORNBURY_EXPIRING",
                                                                "MAISON_OVERRIDE", "BERG_EXPIRING", "THORNBURY_OVERRIDE", "NORDHAUS_DRAFT")}
    assert by_number[keys.QUOTES.PRIOR_WON] == datetime(2026, 8, 21, 11, 0, tzinfo=IST)
    for key in ("Q_THORNBURY_EXPIRING", "Q_BERG_EXPIRING"):
        q = w.quote(SAHIL, key)
        assert q.valid_until == date(2026, 10, 12) and q.sent_at.astimezone(IST).date() == date(2026, 9, 12)
    maison = w.quote(SAHIL, "Q_MAISON_OVERRIDE")
    assert str(maison.lines[0].default_unit_price) == keys.PRICES.ASH_BOARD_EUR and str(maison.lines[0].unit_price) == "16.5000"
    assert maison.lines[0].override_reason == "Volume price agreed for launch order" and maison.review.reasons == ["price_override"]
    assert maison.enquiry_id == w.ref("ENQ_MAISON")
    thornbury = w.quote(SAHIL, "Q_THORNBURY_OVERRIDE")
    assert str(thornbury.lines[0].unit_price) == "19.5000" and thornbury.lines[0].override_reason == "Dealer volume discount requested"
    assert thornbury.enquiry_id == w.ref("ENQ_THORNBURY") and thornbury.created_at.astimezone(IST).date() == date(2026, 10, 9)
    nordhaus = w.quote(SAHIL, "Q_NORDHAUS_DRAFT")
    assert nordhaus.origin == "agent" and nordhaus.origin_message_id == w.ref(keys.MESSAGES.NORDHAUS)
    assert nordhaus.created_at == datetime(2026, 10, 12, 8, 40, tzinfo=IST) and nordhaus.review.reasons == []
    for ref, quote_key, at in ((keys.PROPOSALS.MAISON, "Q_MAISON_OVERRIDE", (8, 20)), (keys.PROPOSALS.THORNBURY, "Q_THORNBURY_OVERRIDE", (8, 30)),
                               (keys.PROPOSALS.NORDHAUS, "Q_NORDHAUS_DRAFT", (8, 45))):
        review_proposal_id = w.quote(SAHIL, quote_key).review.review_proposal_id  # its own unit of work (no nesting)
        with w.uow(SAHIL) as uow:
            proposal = approvals.get(uow, w.ref(ref))
            assert proposal.status == "pending" and proposal.kind == "sales.quote.review" and proposal.version == 1
            assert proposal.created_at == datetime(2026, 10, 12, at[0], at[1], tzinfo=IST)
            assert proposal.expires_at == datetime(2026, 10, 13, at[0], at[1], tzinfo=IST)
            assert approvals.targets_of(uow, proposal)[0].target_id == w.ref(quote_key)
            assert approvals.is_eligible(uow, proposal)
            assert review_proposal_id == proposal.id
    with w.uow(SAHIL) as uow:
        enq = sales.get_enquiry(uow, w.ref("ENQ_MAISON"))
        enq2 = sales.get_enquiry(uow, w.ref("ENQ_THORNBURY"))
        msg = sales.get_customer_message(uow, w.ref(keys.MESSAGES.NORDHAUS))
        msg2 = sales.get_customer_message(uow, w.ref(keys.MESSAGES.BERG))
    assert (enq.enquiry_number, enq.status, enq.quote_number, enq.channel) == (keys.ENQUIRIES.MAISON, "quoted", keys.QUOTES.MAISON_OVERRIDE, "email")
    assert (enq2.enquiry_number, enq2.status, enq2.quote_number, enq2.channel) == (keys.ENQUIRIES.THORNBURY, "quoted", keys.QUOTES.THORNBURY_OVERRIDE, "phone")
    assert enq.received_at == datetime(2026, 9, 8, 10, 0, tzinfo=IST) and enq.owner.id == w.user_id(keys.USERS.MEERA)
    assert msg.received_at == datetime(2026, 10, 11, 19, 20, tzinfo=IST) and msg.quote_number == keys.QUOTES.NORDHAUS_DRAFT and msg.status == "received"
    assert msg2.received_at == datetime(2026, 10, 11, 17, 40, tzinfo=IST) and msg2.quote_number == keys.QUOTES.BERG_EXPIRING and msg2.contact_name == "Erik Lindqvist"
    assert w.ctx.clock.now() == keys.CLOCK_D0


def test_seed_is_idempotent(sales_world: SalesWorld) -> None:
    before = _counts(sales_world)
    refs = dict(sales_world.ctx.refs)
    seed_sales(sales_world.ctx)
    assert _counts(sales_world) == before and sales_world.ctx.refs == refs
    assert before["sales_quote"] == 8 and before["sales_quote_line"] == 8 and before["sales_quote_revision"] == 5
    assert before["sales_enquiry"] == 2 and before["sales_customer_message"] == 2


def test_seeded_reviews_are_decidable(sales_world: SalesWorld) -> None:
    """The proposals bind to the quote version after submit_review, so Sahil's decision lands (never ``target_changed``):
    approving Maison records the approval and unlocks the issue; rejecting Thornbury returns it to draft."""
    w = sales_world
    for ref, decision in ((keys.PROPOSALS.MAISON, "approve"), (keys.PROPOSALS.THORNBURY, "reject")):
        with w.uow(SAHIL) as uow:
            proposal = approvals.get(uow, w.ref(ref))
            decided = approvals.decide(uow, proposal.id, decision=decision, content_hash_seen=proposal.content_hash,
                                       expected_version=proposal.version, reason="Checked")
            assert decided.status == ("approved" if decision == "approve" else "rejected")
    maison = w.quote(keys.USERS.MEERA, "Q_MAISON_OVERRIDE")
    assert maison.status == "internal_review" and maison.review.approval_current and maison.capabilities["issue"].allowed
    thornbury = w.quote(SAHIL, "Q_THORNBURY_OVERRIDE")
    assert thornbury.status == "draft" and thornbury.review.review_proposal_id is None
