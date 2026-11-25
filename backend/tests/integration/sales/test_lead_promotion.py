"""A lead becomes a customer when it is sent a sample, wins a quotation or confirms an order (module 2).

Spec: docs/superpowers/specs/2026-11-25-customers-samples-design.md
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.modules.orders.manifest import _on_order_confirmed
from app.modules.parties import leads
from app.modules.parties import service as parties
from app.modules.parties.models import Party
from app.modules.parties.schemas import LeadStageChange, PartyCreate
from app.modules.sales import service as sales
from app.modules.sales.manifest import _on_quote_won
from app.modules.sales.models import Quote
from app.modules.sales.schemas import SampleCreate, SampleTransition
from app.modules.tasks.models import Task
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db

MEERA, PRIYA, SAHIL = keys.USERS.MEERA, keys.USERS.PRIYA, keys.USERS.SAHIL


def _lead(world: SalesWorld, name: str, roles: tuple[str, ...] = ("customer",)) -> uuid.UUID:
    with world.uow(MEERA) as uow:
        return parties.create_party(uow, PartyCreate.model_validate(
            {"legal_name": name, "country_code": "DE", "default_currency": "EUR", "roles": list(roles), "status": "prospect"}
        )).id


def _party(world: SalesWorld, party_id: uuid.UUID) -> Party:
    with world.uow(PRIYA) as uow:
        row = uow.session.get(Party, party_id)
        assert row is not None
        uow.session.expunge(row)
        return row


def _send_sample(world: SalesWorld, party_id: uuid.UUID) -> None:
    with world.uow(MEERA, idempotency_key=str(uuid.uuid7())) as uow:
        sample = sales.create_sample(uow, SampleCreate(party_id=party_id, description="Walnut platter", quantity=Decimal("1")))
        sales.transition_sample(uow, sample.id, SampleTransition(action="dispatch", expected_version=sample.version,
                                                                 dispatch_reference="DHL 1234"))


def test_sample_dispatch_makes_the_lead_a_customer(world: SalesWorld) -> None:
    lead = _lead(world, "Promo Sample GmbH")
    _send_sample(world, lead)
    world.drain()
    party = _party(world, lead)
    assert (party.status, party.lead_stage) == ("active", "won")
    with world.uow(PRIYA) as uow:
        reasons = uow.session.execute(text(
            "SELECT payload->>'reason' FROM domain_event WHERE event_type = 'parties.lead.stage_changed' AND aggregate_id = :id"
        ), {"id": lead}).scalars().all()
    assert reasons == ["sample_sent"]
    _send_sample(world, lead)  # a second sample changes nothing
    world.drain()
    assert _party(world, lead).version == party.version


def test_lost_lead_with_open_follow_up_is_promoted_and_task_closed(world: SalesWorld) -> None:
    lead = _lead(world, "Promo Lost Srl")
    with world.uow(MEERA) as uow:
        detail = parties.get_party(uow, lead)
        leads.change_lead_stage(uow, lead, LeadStageChange(expected_version=detail.version, stage="lost", lost_reason="Price"))  # type: ignore[arg-type]
    _send_sample(world, lead)
    world.drain()
    party = _party(world, lead)
    assert (party.status, party.lead_stage, party.lost_reason) == ("active", "won", None)
    with world.uow(PRIYA) as uow:
        open_tasks = uow.session.scalars(select(Task).where(Task.primary_ref_id == lead, Task.state == "open")).all()
    assert open_tasks == []


def test_vendor_and_blocked_parties_are_left_alone(world: SalesWorld) -> None:
    vendor = _lead(world, "Promo Vendor Pvt", roles=("vendor",))
    with world.uow(SAHIL) as uow:
        assert leads.promote_to_customer(uow, vendor, reason="sample_sent") is False
    blocked = _lead(world, "Promo Blocked Ltd")
    with world.uow(PRIYA) as uow:
        uow.session.execute(text("UPDATE parties_party SET status = 'blocked' WHERE id = :id"), {"id": blocked})
    with world.uow(SAHIL) as uow:
        assert leads.promote_to_customer(uow, blocked, reason="order_confirmed") is False
    assert _party(world, blocked).status == "blocked"


def test_won_quote_and_confirmed_order_promote(sales_world: SalesWorld) -> None:
    world = sales_world
    quote_id = world.ref(keys.QUOTE_REFS.BERG_WON)
    with world.uow(PRIYA) as uow:
        party_id = uow.session.scalar(select(Quote.party_id).where(Quote.id == quote_id))
        uow.session.execute(text("UPDATE parties_party SET status = 'prospect', lead_stage = 'negotiating' WHERE id = :id"),
                            {"id": party_id})
    with world.uow(SAHIL) as uow:
        _on_quote_won(uow, SimpleNamespace(payload={"quote_id": str(quote_id)}, aggregate_id=quote_id))
    assert (_party(world, party_id).status, _party(world, party_id).lead_stage) == ("active", "won")

    # the sales world has no order at this slice: the handler reads the order's party through the session, so a
    # stand-in order record proves the wiring (the confirm flow itself is covered by the orders tests)
    from app.modules.orders.models import SalesOrder

    lead = _lead(world, "Promo Order AG")
    stand_in = SimpleNamespace(id=uuid.uuid7(), party_id=lead)

    class _Session:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def get(self, model: object, ident: object) -> object:
            return stand_in if model is SalesOrder else self._inner.get(model, ident)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    class _Uow:
        def __init__(self, inner: object) -> None:
            self._inner = inner
            self.session = _Session(inner.session)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    with world.uow(SAHIL) as uow:
        _on_order_confirmed(_Uow(uow), SimpleNamespace(payload={"order_id": str(stand_in.id)}, aggregate_id=stand_in.id))
    assert (_party(world, lead).status, _party(world, lead).lead_stage) == ("active", "won")


def test_customer_facts(sales_world: SalesWorld) -> None:
    from app.modules.parties import activities
    from app.modules.parties.schemas import ActivityCreate
    from app.modules.sales.customer_facts import customer_facts

    world = sales_world
    quote_id = world.ref(keys.QUOTE_REFS.BERG_WON)
    with world.uow(PRIYA) as uow:
        quote = uow.session.get(Quote, quote_id)
        assert quote is not None
        party_id, currency, total = quote.party_id, quote.currency, quote.grand_total_amount
    with world.uow(SAHIL) as uow:
        activities.log_activity(uow, party_id, ActivityCreate(kind="call", outcome="Reorder next month"))  # type: ignore[arg-type]
    facts = customer_facts(world.actor(SAHIL), party_id)
    won = {w.currency: w for w in facts.won}
    assert currency in won and Decimal(won[currency].amount) >= Decimal(total or 0)
    assert facts.last_activity_at is not None
    assert facts.customer_since is not None
    lead = _lead(world, "Facts Lead GmbH")
    fresh = customer_facts(world.actor(MEERA), lead)
    assert fresh.won == [] and fresh.customer_since is None and fresh.last_activity_at is None
