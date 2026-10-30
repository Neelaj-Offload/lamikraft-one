"""Source readers for tasks/briefings: the facts the work lane's fake readers promised (its briefings/world.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.platform import sources
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_quote_message_and_enquiry_facts(sales_world: SalesWorld) -> None:
    w = sales_world
    assert all(sources.has_reader(t) for t in ("sales.quote", "sales.customer_message", "sales.enquiry"))
    with w.uow(keys.USERS.SAHIL) as uow:
        berg = sources.read(uow, "sales.quote", w.ref("Q_BERG_EXPIRING"))
        won = sources.read(uow, "sales.quote", w.ref("Q_BERG_WON"))
        draft = sources.read(uow, "sales.quote", w.ref("Q_NORDHAUS_DRAFT"))
        msg = sources.read(uow, "sales.customer_message", w.ref(keys.MESSAGES.NORDHAUS))
        enq = sources.read(uow, "sales.enquiry", w.ref("ENQ_MAISON"))
        missing = sources.read(uow, "sales.quote", uuid.uuid7())
    assert missing is None
    assert berg is not None and berg.label == f"{keys.QUOTES.BERG_EXPIRING} · {keys.PARTY_NAMES['BERG']}" and berg.status == "sent"
    assert berg.owner_user_id == w.user_id(keys.USERS.MEERA) and berg.branch_id == w.branch_id and berg.required_permission == "sales.quote.read"
    assert berg.canonical_path == f"/sales/quotes/{w.ref('Q_BERG_EXPIRING')}" and berg.is_closed is False
    assert berg.deadlines == {"valid_until_end": datetime(2026, 10, 12, 18, 30, tzinfo=UTC)}  # end of 2026-10-12 IST
    assert berg.money[0].amount == "5700.0000" and berg.money[0].currency == "EUR"
    assert berg.facts["quote_number"] == keys.QUOTES.BERG_EXPIRING and berg.facts["party_name"] == keys.PARTY_NAMES["BERG"]
    assert berg.facts["valid_until"] == "2026-10-12" and berg.facts["revision_no"] == 1 and berg.facts["has_price_override"] is False
    assert won is not None and won.is_closed and won.deadlines == {} and won.version == 4
    assert draft is not None and draft.facts["origin_message_id"] == str(w.ref(keys.MESSAGES.NORDHAUS)) and draft.facts["review_proposal_id"]
    assert msg is not None and msg.label == f"Message from Lena Brandt ({keys.PARTY_NAMES['NORDHAUS']})" and msg.status == "received"
    assert msg.owner_user_id == w.user_id(keys.USERS.MEERA) and msg.canonical_path == f"/sales/messages/{w.ref(keys.MESSAGES.NORDHAUS)}"
    assert msg.facts["linked_quote_ids"] == [str(w.ref("Q_NORDHAUS_DRAFT"))] and msg.facts["linked_quote_number"] == keys.QUOTES.NORDHAUS_DRAFT
    assert msg.facts["received_at"] == "2026-10-11T13:50:00+00:00" and msg.deadlines == {} and "body" not in msg.facts
    assert enq is not None and enq.label == f"{keys.ENQUIRIES.MAISON} · {keys.PARTY_NAMES['MAISON']}" and enq.is_closed
    assert enq.facts["linked_quote_number"] == keys.QUOTES.MAISON_OVERRIDE and enq.required_permission == "sales.enquiry.read"
    with w.uow(keys.USERS.NEHA) as uow:  # readers follow the policies: invisible reads as None
        assert sources.read(uow, "sales.quote", w.ref("Q_BERG_EXPIRING")) is None
        assert sources.read(uow, "sales.customer_message", w.ref(keys.MESSAGES.NORDHAUS)) is None
        assert sources.read(uow, "sales.quote", w.ref("Q_THORNBURY_EXPIRING")) is not None
