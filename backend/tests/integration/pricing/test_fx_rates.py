"""FX snapshots (GAP-03, LP-05.4): dated, sourced rates proposed by one person and approved by another through the
approvals engine; only an approved rate within the policy's age limit converts a price (Pass B), never relabelled."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import FxDecision, FxPolicyUpdate, FxRateCreate, FxRateStatus
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.context import D0
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
SAHIL, ANANYA, MEERA, PRIYA = keys.USERS.SAHIL, keys.USERS.ANANYA, keys.USERS.MEERA, keys.USERS.PRIYA


def propose(world: World, person: str, rate: str, day: date, base: str = "EUR", quote: str = "USD") -> object:
    with UnitOfWork(world.actor(person)) as uow:
        row = pricing.propose_fx_rate(uow, FxRateCreate.model_validate({
            "base_currency": base, "quote_currency": quote, "rate": rate, "rate_date": day.isoformat(),
            "source_kind": "bank", "source_reference": "Demo rate (bank sheet)",
        }))
        return pricing.get_fx_rate(uow, row.id)


def decide(world: World, person: str, fx_rate_id: object, decision: str = "approve", reason: str | None = None) -> object:
    with UnitOfWork(world.actor(person)) as uow:
        pricing.decide_fx_rate(uow, fx_rate_id, FxDecision(decision=decision, reason=reason))  # type: ignore[arg-type]
        return pricing.get_fx_rate(uow, fx_rate_id)  # type: ignore[arg-type]


def test_fx_rate_needs_a_second_person_and_converts_only_when_approved(world: World) -> None:
    proposed = propose(world, SAHIL, "1.0850", date(2026, 10, 9))
    assert proposed.status == FxRateStatus.PROPOSED and proposed.rate == "1.085"  # type: ignore[attr-defined]
    assert not proposed.capabilities["decide"].allowed and proposed.capabilities["decide"].reason_code == "separation_of_duties"  # type: ignore[attr-defined]
    # a proposed rate converts nothing
    oak = world.ref("OAK_TRAY")
    pending = pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True)
    assert pending.status == "not_found" and pending.reason_code == "FX_UNAVAILABLE" and pending.unit_price is None
    with pytest.raises(Forbidden):  # the proposer can never approve
        decide(world, SAHIL, proposed.id)  # type: ignore[attr-defined]
    with pytest.raises(Forbidden):  # sales cannot approve rates
        decide(world, MEERA, proposed.id)  # type: ignore[attr-defined]
    approved = decide(world, ANANYA, proposed.id)  # type: ignore[attr-defined]
    assert approved.status == FxRateStatus.APPROVED and approved.decided_by_name  # type: ignore[attr-defined]
    found = pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True)
    assert found.status == "found" and found.currency == "USD"
    assert format(found.unit_price.amount, "f") == "26.0400" and found.unit_price.currency == "USD"  # type: ignore[union-attr]
    assert format(found.source_unit_price.amount, "f") == "24.0000" and found.source_unit_price.currency == "EUR"  # type: ignore[union-attr]
    assert found.fx is not None and found.fx.fx_rate_id == proposed.id and found.price_list_code == keys.PRICE_LISTS.EXP_EUR  # type: ignore[attr-defined]
    # without allow_fx the price is never converted or relabelled
    assert pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak).status == "not_found"
    with pytest.raises(Conflict) as exc:  # one approved rate per pair and day
        propose(world, SAHIL, "1.09", date(2026, 10, 9))
    assert exc.value.code == "fx_rate_exists"
    with UnitOfWork(world.actor(SAHIL)) as uow:
        names = [r for r in uow.session.scalars(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == proposed.id)
                                                 .order_by(DomainEvent.seq))]  # type: ignore[attr-defined]
    assert names == ["pricing.fx_rate.proposed", "pricing.fx_rate.approved"]


def test_stale_rejected_withdrawn_and_disabled_rates_do_not_convert(world: World) -> None:
    oak = world.ref("OAK_TRAY")
    stale = propose(world, SAHIL, "1.07", date(2026, 9, 1))
    decide(world, ANANYA, stale.id)  # type: ignore[attr-defined]
    too_old = pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True)
    assert too_old.status == "not_found" and too_old.reason_code == "FX_UNAVAILABLE"  # older than max_rate_age_days (7)
    rejected = propose(world, SAHIL, "1.5", date(2026, 10, 10))
    after = decide(world, ANANYA, rejected.id, "reject", "Not the bank's rate")  # type: ignore[attr-defined]
    assert after.status == FxRateStatus.REJECTED and after.decision_reason == "Not the bank's rate"  # type: ignore[attr-defined]
    withdrawn = propose(world, ANANYA, "1.08", date(2026, 10, 11))
    with pytest.raises(Forbidden), UnitOfWork(world.actor(SAHIL)) as uow:
        pricing.withdraw_fx_rate(uow, withdrawn.id)  # type: ignore[attr-defined]
    with UnitOfWork(world.actor(ANANYA)) as uow:
        pricing.withdraw_fx_rate(uow, withdrawn.id)  # type: ignore[attr-defined]
    assert pricing.get_fx_rate(world.actor(SAHIL), withdrawn.id).status == FxRateStatus.WITHDRAWN  # type: ignore[attr-defined]
    with pytest.raises(Conflict):
        decide(world, SAHIL, withdrawn.id)  # type: ignore[attr-defined]
    assert pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True).status == "not_found"
    # an approved, fresh rate converts until the policy disables conversion
    fresh = propose(world, SAHIL, "1.0850", date(2026, 10, 12))
    decide(world, ANANYA, fresh.id)  # type: ignore[attr-defined]
    assert pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True).status == "found"
    with pytest.raises(Forbidden), UnitOfWork(world.actor(SAHIL).with_(recent_auth_at=D0)) as uow:
        pricing.update_fx_policy(uow, FxPolicyUpdate(expected_version=0, conversion_enabled=False))
    with UnitOfWork(world.actor(ANANYA).with_(recent_auth_at=D0, auth_strength="mfa")) as uow:
        policy = pricing.update_fx_policy(uow, FxPolicyUpdate(expected_version=0, conversion_enabled=False))
    assert (policy.conversion_enabled, policy.max_rate_age_days, policy.version) == (False, 7, 1)
    with pytest.raises(Conflict), UnitOfWork(world.actor(ANANYA).with_(recent_auth_at=D0, auth_strength="mfa")) as uow:
        pricing.update_fx_policy(uow, FxPolicyUpdate(expected_version=0, conversion_enabled=True))
    assert pricing.resolve_price(world.actor(MEERA), currency="USD", uom="pcs", product_id=oak, allow_fx=True).status == "not_found"
    listed = pricing.list_fx_rates(world.actor(MEERA), status=[FxRateStatus.APPROVED])
    assert [r.rate_date for r in listed.items] == [date(2026, 10, 12), date(2026, 9, 1)]


def test_fx_input_validation(world: World) -> None:
    with pytest.raises(ValidationFailed):
        propose(world, SAHIL, "1.1", date(2026, 10, 12), base="EUR", quote="EUR")
    with pytest.raises(ValidationFailed):  # never dated in the future
        propose(world, SAHIL, "1.1", date(2026, 10, 13))
    with pytest.raises(PydanticValidationError):  # zero and floats are rejected by the RatioStr type
        FxRateCreate.model_validate({"base_currency": "EUR", "quote_currency": "USD", "rate": "0", "rate_date": "2026-10-12",
                                     "source_reference": "x"})
    with pytest.raises(Forbidden):  # sales cannot propose rates
        propose(world, MEERA, "1.1", date(2026, 10, 12))
    assert Decimal("1.0850") > 0
