"""Enquiries and customer messages (ADR-036, GAP-09): numbering, assignment, quoted/closed, replies, events, scope."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, VersionConflict
from app.modules.sales import service as sales
from app.modules.sales.schemas import (
    CustomerMessageCreate,
    CustomerMessageFilters,
    EnquiryCreate,
    EnquiryFilters,
    EnquiryUpdate,
    MarkReplied,
    QuoteCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
IST = ZoneInfo("Asia/Kolkata")


def _events(world: SalesWorld, aggregate_id):  # type: ignore[no-untyped-def]
    with world.uow(keys.USERS.SAHIL) as uow:
        return [(r[0], r[1]) for r in uow.session.execute(
            select(DomainEvent.event_type, DomainEvent.payload).where(DomainEvent.aggregate_id == aggregate_id).order_by(DomainEvent.seq)).all()]


def test_enquiry_lifecycle_and_events(world: SalesWorld) -> None:
    w = world
    with w.uow(keys.USERS.MEERA) as uow:
        first = sales.create_enquiry(uow, EnquiryCreate(party_id=w.ref("MAISON"), channel="email", subject="Boards", body="<external> please quote"))
        second = sales.create_enquiry(uow, EnquiryCreate(party_id=w.ref("NORDHAUS"), channel="phone",
                                                          received_at=datetime(2026, 10, 7, 15, 0, tzinfo=IST)))
    assert (first.enquiry_number, second.enquiry_number) == (keys.ENQUIRIES.MAISON, keys.ENQUIRIES.THORNBURY)
    assert first.status == "received" and first.owner.id == w.user_id(keys.USERS.MEERA) and first.party.display_name == keys.PARTY_NAMES["MAISON"]
    assert first.body == "<external> please quote" and first.channel == "email" and first.contact_id is None
    assert second.received_at == datetime(2026, 10, 7, 15, 0, tzinfo=IST) and second.capabilities["update"].allowed
    received = [p for n, p in _events(w, first.id) if n == "sales.enquiry.received"][0]
    assert received == {"enquiry_id": str(first.id), "enquiry_number": first.enquiry_number, "party_id": str(w.ref("MAISON")),
                        "channel": "email", "owner_user_id": str(w.user_id(keys.USERS.MEERA)), "origin": "user"}
    # a sales user cannot assign; management can (emits assigned); the quote created from it marks it quoted
    with pytest.raises(Forbidden):
        with w.uow(keys.USERS.MEERA) as uow:
            sales.update_enquiry(uow, first.id, EnquiryUpdate(expected_version=first.version, owner_user_id=w.user_id(keys.USERS.NEHA)))
    with w.uow(keys.USERS.SAHIL) as uow:
        assigned = sales.update_enquiry(uow, first.id, EnquiryUpdate(expected_version=first.version, owner_user_id=w.user_id(keys.USERS.NEHA)))
    assert assigned.status == "assigned" and assigned.owner.id == w.user_id(keys.USERS.NEHA)
    assert [n for n, _p in _events(w, first.id)] == ["sales.enquiry.received", "sales.enquiry.assigned"]
    with pytest.raises(NotFound):  # now outside Meera's own scope
        with w.uow(keys.USERS.MEERA) as uow:
            sales.get_enquiry(uow, first.id)
    with w.uow(keys.USERS.NEHA) as uow:
        with pytest.raises(NotFound):  # Neha may not see Maison (Meera's party): the quote cannot be created
            sales.create_quote(uow, QuoteCreate(party_id=w.ref("MAISON"), enquiry_id=first.id))
    with w.uow(keys.USERS.MEERA) as uow:
        quote = sales.create_quote(uow, QuoteCreate(party_id=w.ref("NORDHAUS"), enquiry_id=second.id))
        quoted = sales.get_enquiry(uow, second.id)
    assert quoted.status == "quoted" and quoted.quote_id == quote.id and quoted.quote_number == quote.quote_number
    assert [n for n, _p in _events(w, second.id)][-1] == "sales.enquiry.quoted"
    with pytest.raises(VersionConflict):  # second moved on when it was quoted: its creation version is stale
        with w.uow(keys.USERS.SAHIL) as uow:
            sales.update_enquiry(uow, second.id, EnquiryUpdate(expected_version=second.version, subject="late"))
    with w.uow(keys.USERS.SAHIL) as uow:
        closed = sales.update_enquiry(uow, first.id, EnquiryUpdate(expected_version=assigned.version, status="closed", outcome_code="no_response"))
    with pytest.raises(Forbidden, match="enquiry_closed"):  # a closed enquiry is frozen
        with w.uow(keys.USERS.SAHIL) as uow:
            sales.update_enquiry(uow, first.id, EnquiryUpdate(expected_version=closed.version, subject="late"))
    assert closed.status == "closed" and closed.outcome_code == "no_response" and closed.closed_at is not None
    assert closed.capabilities["update"].reason_code == "enquiry_closed" and closed.allowed_transitions == []
    assert [n for n, _p in _events(w, first.id)][-1] == "sales.enquiry.closed"
    with w.uow(keys.USERS.SAHIL) as uow:
        listed = sales.list_enquiries(uow, EnquiryFilters(status=["closed"]))  # type: ignore[list-item]
        by_q = sales.list_enquiries(uow, EnquiryFilters(q="0002"))
    assert [e.id for e in listed.items] == [first.id] and [e.id for e in by_q.items] == [second.id]


def test_customer_messages_recorded_and_replied(world: SalesWorld) -> None:
    w = world
    when = datetime(2026, 10, 11, 19, 20, tzinfo=IST)
    with w.uow(keys.USERS.MEERA) as uow:
        m = sales.record_customer_message(
            uow, CustomerMessageCreate(party_id=w.ref("NORDHAUS"), channel="email", received_at=when, subject="Repeat order",
                                       body="Hi Meera, please quote our usual trays. Lena"),
        )
    assert m.status == "received" and m.assignee.id == w.user_id(keys.USERS.MEERA) and m.contact_name == "Lena Brandt"
    assert m.received_at == when and m.quote_id is None and m.capabilities["mark_replied"].allowed
    assert m.allowed_transitions[0].action == "mark_replied"
    received = [p for n, p in _events(w, m.id) if n == "sales.customer_message.received"][0]
    assert received["message_id"] == str(m.id) and received["assignee_user_id"] == str(w.user_id(keys.USERS.MEERA))
    assert received["contact_id"] == str(m.contact_id) and received["quote_id"] is None and "body" not in received
    with pytest.raises(NotFound):  # Neha is not the assignee
        with w.uow(keys.USERS.NEHA) as uow:
            sales.get_customer_message(uow, m.id)
    with w.uow(keys.USERS.MEERA) as uow:
        now_received = sales.record_customer_message(uow, CustomerMessageCreate(party_id=w.ref("BERG"), channel="whatsapp", body="hi"))
    assert now_received.received_at == w.ctx.clock.now()  # the Clock, never datetime.now()
    with w.uow(keys.USERS.MEERA) as uow:
        replied = sales.mark_replied(uow, m.id, MarkReplied(expected_version=m.version, reply_ref_type="email"))
    assert replied.status == "replied" and replied.replied_at == w.ctx.clock.now() and replied.reply_ref_type == "email"
    assert replied.capabilities["update"].reason_code == "message_replied" and replied.allowed_transitions == []
    assert [n for n, _p in _events(w, m.id)] == ["sales.customer_message.received", "sales.customer_message.replied"]
    with w.uow(keys.USERS.SAHIL) as uow:
        open_ = sales.list_customer_messages(uow, CustomerMessageFilters(status=["received"]))  # type: ignore[list-item]
        for_party = sales.list_customer_messages(uow, CustomerMessageFilters(party_id=w.ref("NORDHAUS")))
    assert [x.id for x in open_.items] == [now_received.id] and [x.id for x in for_party.items] == [m.id]
