"""resolve_price on real PostgreSQL: customer agreement -> customer-type list -> standard list, then currency, unit and
effective date; ambiguity never falls through; a currency label is never relabelled (legacy bug §10.1 #10)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, NotFound
from app.core.money import Money
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceListItemHistory
from app.modules.pricing.schemas import (
    PriceListCreate,
    PriceListItemCreate,
    PriceResolution,
    PriceType,
    ResolvePriceInput,
    SupersedeItem,
)
from app.modules.pricing.tools import RESOLVE_PRICE
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.pricing import item_ref
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

D0_DATE = date(2026, 10, 12)


def make_list(
    world: World,
    code: str,
    items: list[tuple[str, str, str]],
    *,
    scope: str = "standard",
    price_type: str = "export",
    currency: str = "EUR",
    party: str | None = None,
    customer_type: str | None = None,
    priority: int | None = None,
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = date(2026, 12, 31),
    activate: bool = True,
) -> uuid.UUID:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(
            uow,
            PriceListCreate.model_validate({
                "code": code, "name": code, "price_type": price_type, "scope_kind": scope, "currency": currency,
                "party_id": world.ref(party) if party else None, "customer_type": customer_type, "priority": priority,
                "valid_from": valid_from, "valid_to": valid_to,
            }),
        )
        for product, unit, price in items:
            pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref(product), unit_code=unit,  # type: ignore[arg-type]
                                                              unit_price=Decimal(price)))
        if activate:
            pricing.activate_price_list(uow, pl.id)
        return pl.id


def _amt(money: Money | None) -> str | None:
    """The amount of a wire Money as text (prices travel as {amount, currency}, api-conventions §4)."""
    return None if money is None else format(money.amount, "f")


def resolve(world: World, user: str, product: str, currency: str = "EUR", uom: str = "pcs", *, party: str | None = None,
            **kw: object) -> PriceResolution:
    return pricing.resolve_price(
        world.actor(user), currency=currency, uom=uom, product_id=world.ref(product),
        party_id=world.ref(party) if party else None, **kw,
    )


def test_standard_tier_with_full_provenance(world: World) -> None:
    r = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS")
    assert r.status == "found" and r.reason_code is None
    assert _amt(r.unit_price) == keys.PRICES.OAK_TRAY_EUR and r.currency == "EUR" and r.unit_code == "pcs"
    assert (r.tier, r.price_list_code) == ("standard", keys.PRICE_LISTS.EXP_EUR)
    assert r.item_id == world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY"))
    assert r.on_date == D0_DATE and r.customer_type == "standard"
    assert [(c.tier, c.outcome) for c in r.checks] == [("customer", "no_list"), ("customer_type", "no_list"),
                                                       ("standard", "matched")]
    assert r.price_basis is None and r.redacted_fields == []  # Meera holds no pricing.price_list.read


def test_customer_agreement_beats_customer_type_beats_standard(world: World) -> None:
    make_list(world, "CT-STD-EUR", [("OAK_TRAY", "pcs", "23.0000")], scope="customer_type", customer_type="standard")
    r = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS")
    assert (r.status, r.tier, r.price_list_code, _amt(r.unit_price)) == ("found", "customer_type", "CT-STD-EUR", "23.0000")
    make_list(world, "AGR-NORDHAUS", [("OAK_TRAY", "pcs", "22.5000")], scope="customer", party="NORDHAUS")
    r = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS")
    assert (r.status, r.tier, r.price_list_code, _amt(r.unit_price)) == ("found", "customer", "AGR-NORDHAUS", "22.5000")
    berg = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="BERG")  # the agreement belongs to Nordhaus only
    assert (berg.tier, _amt(berg.unit_price)) == ("customer_type", "23.0000")
    anonymous = resolve(world, keys.USERS.MEERA, "OAK_TRAY")
    assert (anonymous.tier, _amt(anonymous.unit_price)) == ("standard", keys.PRICES.OAK_TRAY_EUR)
    # a tier priced only in another currency falls through to the next tier in the requested currency
    gbp = resolve(world, keys.USERS.MEERA, "OAK_TRAY", "GBP", party="NORDHAUS")
    assert (gbp.tier, gbp.currency, _amt(gbp.unit_price)) == ("standard", "GBP", keys.PRICES.OAK_TRAY_GBP)


def test_ambiguous_overlap_without_priority_never_falls_through(world: World) -> None:
    # two customer-type lists of different price types both price the oak tray (activation allows it: the types
    # differ); without a price type or explicit priority the match is AMBIGUOUS and the standard list is not used
    make_list(world, "CT-EXP", [("OAK_TRAY", "pcs", "23.0000")], scope="customer_type", customer_type="standard")
    make_list(world, "CT-DIS", [("OAK_TRAY", "pcs", "22.0000")], scope="customer_type", customer_type="standard",
              price_type="distributor")
    r = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS")
    assert r.status == "ambiguous" and r.reason_code == "PRICE_AMBIGUOUS" and r.unit_price is None
    assert sorted(c.price_list_code for c in r.candidates) == ["CT-DIS", "CT-EXP"]
    assert [c.outcome for c in r.checks] == ["no_list", "ambiguous"]  # the standard tier was never consulted
    chosen = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS", price_type=PriceType.EXPORT)
    assert (chosen.status, chosen.price_list_code) == ("found", "CT-EXP")


def test_unique_explicit_priority_resolves_the_overlap(world: World) -> None:
    make_list(world, "CT-HI", [("OAK_TRAY", "pcs", "21.0000")], scope="customer_type", customer_type="standard",
              priority=20)
    make_list(world, "CT-LO", [("OAK_TRAY", "pcs", "20.0000")], scope="customer_type", customer_type="standard",
              price_type="sample", priority=10)
    r = resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS")
    assert (r.status, r.price_list_code, _amt(r.unit_price)) == ("found", "CT-HI", "21.0000")
    make_list(world, "CT-NOPRIO", [("OAK_TRAY", "pcs", "19.0000")], scope="customer_type", customer_type="standard",
              price_type="distributor")
    assert resolve(world, keys.USERS.MEERA, "OAK_TRAY", party="NORDHAUS").status == "ambiguous"


def test_legacy_multiple_eur_rows_are_selected_by_price_type(world: World) -> None:
    make_list(world, "SMP-EUR-2026", [("OAK_TRAY", "pcs", "30.0000")], price_type="sample")
    assert resolve(world, keys.USERS.MEERA, "OAK_TRAY").status == "ambiguous"  # never "the last EUR row wins"
    export = resolve(world, keys.USERS.MEERA, "OAK_TRAY", price_type=PriceType.EXPORT)
    sample = resolve(world, keys.USERS.MEERA, "OAK_TRAY", price_type=PriceType.SAMPLE)
    assert (export.price_list_code, _amt(export.unit_price)) == (keys.PRICE_LISTS.EXP_EUR, keys.PRICES.OAK_TRAY_EUR)
    assert (sample.price_list_code, _amt(sample.unit_price)) == ("SMP-EUR-2026", "30.0000")


def test_overlapping_list_activation_is_rejected(world: World) -> None:
    with pytest.raises(Conflict) as excinfo:
        make_list(world, "EXP-EUR-2026B", [("OAK_TRAY", "pcs", "25.0000")])
    assert excinfo.value.code == "price_list_overlap"
    assert excinfo.value.extra["conflicts"][0]["price_list_code"] == keys.PRICE_LISTS.EXP_EUR


def test_currency_is_never_relabelled_and_units_are_never_converted(world: World) -> None:
    usd = resolve(world, keys.USERS.MEERA, "OAK_TRAY", "USD", party="NORDHAUS")
    assert usd.status == "not_found" and usd.reason_code == "NO_PRICE_IN_CURRENCY"
    assert usd.unit_price is None and usd.currency is None and usd.requested_currency == "USD"
    assert any("EUR" in h and "not converted" in h for h in usd.hints)
    inr = resolve(world, keys.USERS.SAHIL, "WALNUT_BOARD", "INR", "sheets")
    assert (inr.status, _amt(inr.unit_price), inr.price_list_code) == ("found", keys.PRICES.WALNUT_BOARD_INR,
                                                                      keys.PRICE_LISTS.DOM_INR)
    wrong_unit = resolve(world, keys.USERS.SAHIL, "WALNUT_BOARD", "INR", "pcs")
    assert wrong_unit.status == "not_found" and wrong_unit.reason_code == "NO_PRICE_FOR_UNIT"


def test_effective_dates_and_supersede_history(world: World) -> None:
    before = resolve(world, keys.USERS.MEERA, "OAK_TRAY", on_date=date(2025, 12, 31))
    assert before.status == "not_found" and before.reason_code in {"NOT_EFFECTIVE", "NO_PRICE"}
    old_item = world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY"))
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        new = pricing.supersede_item(uow, old_item, SupersedeItem(unit_price=Decimal("26"), valid_from=date(2026, 11, 1),
                                                                  reason="2026 Q4 price"))
    assert _amt(new.unit_price) == "26.0000" and new.valid_from == date(2026, 11, 1)
    today = resolve(world, keys.USERS.MEERA, "OAK_TRAY")
    later = resolve(world, keys.USERS.MEERA, "OAK_TRAY", on_date=date(2026, 11, 1))
    assert (today.item_id, _amt(today.unit_price), today.valid_to) == (old_item, "24.0000", date(2026, 10, 31))
    assert (later.item_id, _amt(later.unit_price)) == (new.id, "26.0000")
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        kinds = [h.change_kind for h in uow.session.scalars(
            select(PriceListItemHistory).where(PriceListItemHistory.item_id.in_([old_item, new.id]))
            .order_by(PriceListItemHistory.occurred_at, PriceListItemHistory.id))]
        event = uow.session.scalars(select(DomainEvent).where(
            DomainEvent.event_type == "pricing.price_list_item.superseded")).one()
    assert kinds == ["created", "list_activated", "superseded", "created"]
    assert event.payload["item_id"] == str(old_item) and event.payload["superseded_by_item_id"] == str(new.id)
    with pytest.raises(Conflict):
        with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
            pricing.supersede_item(uow, old_item, SupersedeItem(unit_price=Decimal("27"), valid_from=date(2026, 12, 1)))


def test_zero_price_is_unavailable_and_does_not_fall_through(world: World) -> None:
    make_list(world, "AGR-BERG", [("MAPLE_TRIVET", "pcs", "0")], scope="customer", party="BERG")
    r = resolve(world, keys.USERS.MEERA, "MAPLE_TRIVET", party="BERG")
    assert r.status == "unavailable" and r.reason_code == "ZERO_PRICE" and r.unit_price is None
    assert r.price_list_code == "AGR-BERG" and r.tier == "customer"


def test_party_scope_applies_to_resolution_and_customer_lists(world: World) -> None:
    with pytest.raises(NotFound):  # Thornbury belongs to Neha: Meera cannot resolve its prices
        resolve(world, keys.USERS.MEERA, "OAK_TRAY", "GBP", party="THORNBURY")
    neha = resolve(world, keys.USERS.NEHA, "OAK_TRAY", "GBP", party="THORNBURY")
    assert (neha.status, neha.customer_type, _amt(neha.unit_price)) == ("found", "dealer", keys.PRICES.OAK_TRAY_GBP)
    agreement = make_list(world, "AGR-THORNBURY", [("OAK_TRAY", "pcs", "20.0000")], scope="customer", currency="GBP",
                          party="THORNBURY")
    assert "AGR-THORNBURY" not in [p.code for p in pricing.list_price_lists(world.actor(keys.USERS.MEERA)).items]
    with pytest.raises(NotFound):
        pricing.get_price_list(world.actor(keys.USERS.MEERA), agreement)
    assert pricing.get_price_list(world.actor(keys.USERS.NEHA), agreement).code == "AGR-THORNBURY"


def test_resolve_price_tool_uses_the_same_service(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        out = RESOLVE_PRICE.handler(uow, ResolvePriceInput(product_key=keys.PRODUCTS.OAK_TRAY, currency="EUR", uom="pcs",
                                                           party_id=world.ref("NORDHAUS")))
    assert isinstance(out, PriceResolution) and out.status == "found" and _amt(out.unit_price) == "24.0000"
    assert RESOLVE_PRICE.permission == "pricing.price.read" and RESOLVE_PRICE.effect == "read"
