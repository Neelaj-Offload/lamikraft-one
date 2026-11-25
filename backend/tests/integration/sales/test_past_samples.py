"""Samples sent before Lamikraft One are entered with their real dates (module 2).

Spec: docs/superpowers/specs/2026-11-25-customers-samples-design.md ("Past samples")
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ValidationFailed
from app.modules.parties import service as parties
from app.modules.parties.schemas import PartyCreate
from app.modules.sales import service as sales
from app.modules.sales.common import business_date
from app.modules.sales.samples import BACKFILL_REFERENCE
from app.modules.sales.schemas import SampleCreate, SampleTransition
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db

MEERA, PRIYA = keys.USERS.MEERA, keys.USERS.PRIYA


def _today(world: SalesWorld) -> date:
    with world.uow(MEERA) as uow:
        return business_date(uow)


def _lead(world: SalesWorld, name: str) -> uuid.UUID:
    with world.uow(MEERA) as uow:
        return parties.create_party(uow, PartyCreate.model_validate(
            {"legal_name": name, "country_code": "IT", "default_currency": "EUR", "roles": ["customer"], "status": "prospect"}
        )).id


def _create(world: SalesWorld, party_id: uuid.UUID, **extra: object):  # type: ignore[no-untyped-def]
    with world.uow(MEERA, idempotency_key=str(uuid.uuid7())) as uow:
        return sales.create_sample(uow, SampleCreate.model_validate(
            {"party_id": str(party_id), "description": "Chopping board CB07", "quantity": "2", **extra}))


def _step(world: SalesWorld, sample_id: uuid.UUID, action: str, **extra: object):  # type: ignore[no-untyped-def]
    with world.uow(MEERA, idempotency_key=str(uuid.uuid7())) as uow:
        version = sales.get_sample(uow, sample_id).version
        return sales.transition_sample(uow, sample_id, SampleTransition.model_validate(
            {"action": action, "expected_version": version, **extra}))


def test_already_sent_sample_is_dispatched_on_its_date_and_promotes(world: SalesWorld) -> None:
    lead = _lead(world, "Past Sample Srl")
    sent = _today(world) - timedelta(days=200)
    sample = _create(world, lead, sent_on=sent.isoformat())
    assert sample.status == "dispatched" and sample.requested_on == sent
    assert sample.dispatched_at is not None and sample.dispatched_at.date() == sent
    assert sample.dispatch_reference == BACKFILL_REFERENCE
    world.drain()
    with world.uow(PRIYA) as uow:
        assert parties.get_party(uow, lead).lead_stage == "won"

    delivered = _step(world, sample.id, "deliver", evidence_kind="customer_confirmation",
                      occurred_on=(sent + timedelta(days=6)).isoformat())
    assert delivered.delivered_at.date() == sent + timedelta(days=6)
    with pytest.raises(ValidationFailed):  # feedback before the delivery date
        _step(world, sample.id, "record_feedback", feedback="Liked the walnut", feedback_outcome="positive",
              occurred_on=(sent + timedelta(days=2)).isoformat())
    fb = _step(world, sample.id, "record_feedback", feedback="Liked the walnut", feedback_outcome="positive",
               occurred_on=(sent + timedelta(days=20)).isoformat())
    assert fb.feedback_at.date() == sent + timedelta(days=20)


def test_dates_cannot_be_in_the_future(world: SalesWorld) -> None:
    lead = _lead(world, "Future Sample Spa")
    tomorrow = (_today(world) + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationFailed):
        _create(world, lead, sent_on=tomorrow)
    with pytest.raises(ValidationFailed):  # a reference only makes sense with the date it was sent
        _create(world, lead, dispatch_reference="DHL 99")
    sample = _create(world, lead)
    with pytest.raises(ValidationFailed):
        _step(world, sample.id, "dispatch", dispatch_reference="DHL 1", occurred_on=tomorrow)
    with pytest.raises(ValidationFailed):  # cancel takes no date
        _step(world, sample.id, "cancel", reason="Not needed", occurred_on=_today(world).isoformat())


def test_quantity_unchanged_by_backfill(world: SalesWorld) -> None:
    sample = _create(world, _lead(world, "Quantity Check Srl"), sent_on=_today(world).isoformat(), dispatch_reference="Hand carried")
    assert sample.quantity == Decimal("2.000000") or sample.quantity == Decimal("2")
    assert sample.dispatch_reference == "Hand carried"
