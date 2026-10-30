"""Commercial rule sets and the calculate_quote tool over resolved price-list items (scenario C and D figures)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.errors import Conflict, Forbidden, NotConfigured, ValidationFailed
from app.core.money import Money
from app.modules.commercial import engine
from app.modules.commercial import service as commercial
from app.modules.commercial.schemas import CalculateQuoteInput, CalculateQuoteOutput, QuoteCommercialRulesV1
from app.modules.commercial.tools import CALCULATE_QUOTE
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceList
from app.modules.pricing.schemas import PriceListCreate, PriceListItemCreate, SupersedeItem
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.commercial import RULE_SET_REF
from app.seed.world.pricing import item_ref
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

D0_DATE = date(2026, 10, 12)


def _calculate(world: World, lines: list[tuple[str, str]], *, currency: str = "EUR", toggle: bool = False,
               user: str = keys.USERS.MEERA) -> CalculateQuoteOutput:
    data = CalculateQuoteInput.model_validate({
        "currency": currency, "surcharge_requested": toggle,
        "lines": [{"price_list_item_id": world.ref(ref), "quantity": qty} for ref, qty in lines],
    })
    with UnitOfWork(world.actor(user)) as uow:
        out = CALCULATE_QUOTE.handler(uow, data)
    assert isinstance(out, CalculateQuoteOutput)
    return out


def _amount(money: Money | None) -> str | None:
    """The amount of a wire Money as text (money travels as {amount, currency}, api-conventions §4)."""
    return None if money is None else format(money.amount, "f")


def test_rule_set_v1_is_active_and_readable_by_management_only(world: World) -> None:
    page = commercial.list_rule_sets(world.actor(keys.USERS.SAHIL))
    sets = page.items
    assert (page.total, page.limit, page.offset) == (1, 50, 0)
    assert [(r.code, r.version_no, r.status.value) for r in sets] == [(keys.COMMERCIAL.RULE_SET, 1, "active")]
    params = sets[0].params
    assert str(params.thresholds["EUR"].minimum_order_value) == keys.COMMERCIAL.EUR_MINIMUM
    assert str(params.thresholds["EUR"].surcharge_amount) == keys.COMMERCIAL.SURCHARGE
    assert params.applicable_line_types == ["catalog", "custom", "manual"] and set(params.thresholds) == {"EUR"}
    assert commercial.get_rule_set(world.actor(keys.USERS.ANANYA), world.ref(RULE_SET_REF)).version_no == 1
    with pytest.raises(Forbidden):
        commercial.list_rule_sets(world.actor(keys.USERS.MEERA))
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        event = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "commercial.rule_set.activated")).one()
    assert event.payload == {"rule_set_id": str(world.ref(RULE_SET_REF)), "code": keys.COMMERCIAL.RULE_SET,
                             "version_no": 1, "origin": "user"}


def test_activating_a_new_version_retires_the_previous_one(world: World) -> None:
    v2_params = QuoteCommercialRulesV1.model_validate({
        "thresholds": {"EUR": {"minimum_order_value": "6000.00", "surcharge_amount": "450.00"}},
        "applicable_line_types": ["catalog", "custom"],
    })
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        v2_id = commercial.create_rule_set(uow, code=keys.COMMERCIAL.RULE_SET, version_no=2, params=v2_params,
                                           effective_from=D0_DATE).id
    draft = commercial.get_rule_set(world.actor(keys.USERS.PRIYA), v2_id)
    assert draft.capabilities["activate"].allowed is True
    assert [(t.action, t.to_status) for t in draft.allowed_transitions] == [("activate", "active")]
    read_only = commercial.get_rule_set(world.actor(keys.USERS.SAHIL), v2_id)
    assert read_only.capabilities["activate"].reason_code == "permission_denied" and read_only.allowed_transitions == []
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        commercial.activate_rule_set(uow, v2_id)
    active = commercial.get_rule_set(world.actor(keys.USERS.PRIYA), v2_id)
    assert active.capabilities["activate"].reason_code == "rule_set_not_draft" and active.allowed_transitions == []
    statuses = {r.version_no: r.status.value for r in commercial.list_rule_sets(world.actor(keys.USERS.SAHIL)).items}
    assert statuses == {1: "retired", 2: "active"}
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        rules = commercial.active_rules(uow)
    assert rules.version_no == 2 and rules.thresholds["EUR"].minimum_order_value == Decimal("6000.00")
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:  # management may only read rules
        commercial.create_rule_set(uow, code="other", version_no=1, params=v2_params, effective_from=date(2027, 1, 1))


def test_future_rule_set_is_not_activated_before_its_effective_date(world: World) -> None:
    """effective_from is binding: activation retires the current version at once, so a version effective in the future
    cannot be activated early (the active v1 keeps pricing calculations until then)."""
    params = QuoteCommercialRulesV1.model_validate({
        "thresholds": {"EUR": {"minimum_order_value": "6000.00", "surcharge_amount": "450.00"}},
        "applicable_line_types": ["catalog", "custom"],
    })
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        v2_id = commercial.create_rule_set(uow, code=keys.COMMERCIAL.RULE_SET, version_no=2, params=params,
                                           effective_from=date(2027, 1, 1)).id
    draft = commercial.get_rule_set(world.actor(keys.USERS.PRIYA), v2_id)
    assert (draft.capabilities["activate"].allowed, draft.capabilities["activate"].reason_code) == (
        False, "rule_set_not_yet_effective",
    )
    with pytest.raises(Conflict) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        commercial.activate_rule_set(uow, v2_id)
    assert excinfo.value.code == "rule_set_not_yet_effective"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        assert commercial.active_rules(uow).version_no == 1


def test_scenario_c_line_through_the_tool(world: World) -> None:
    out = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), keys.EXPECTED.SCENARIO_C_QTY)])
    calc = out.calculation
    assert calc.grand_total is not None and calc.grand_total.currency == "EUR"
    assert _amount(calc.grand_total) == keys.EXPECTED.SCENARIO_C_TOTAL
    assert calc.minimum.status == "MEETS" and calc.surcharge.reason_code == engine.AT_OR_ABOVE_MINIMUM
    recommended = calc.lines[0].recommendation.quantity
    assert recommended is not None and recommended.uom == "pcs"
    assert format(recommended.value, "f") == keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY
    assert calc.lines[0].quantity.model_dump(mode="json") == {"value": keys.EXPECTED.SCENARIO_C_QTY, "uom": "pcs"}
    assert calc.lines[0].advisories == [] and calc.tax is None and calc.tax_label == "Excludes taxes"
    assert (calc.rule_set_id, calc.rule_set_version) == (world.ref(RULE_SET_REF), 1)
    ref = out.lines[0]
    assert (ref.price_list_code, ref.product_key, ref.unit_code) == (keys.PRICE_LISTS.EXP_EUR, keys.PRODUCTS.OAK_TRAY, "pcs")


@pytest.mark.parametrize(("toggle", "grand", "applied"), [(False, "4800.00", False), (True, "5200.00", True)])
def test_scenario_d_surcharge_through_the_tool(world: World, toggle: bool, grand: str, applied: bool) -> None:
    calc = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), "200")], toggle=toggle).calculation
    assert _amount(calc.applicable_subtotal) == "4800.00" and _amount(calc.grand_total) == grand
    assert calc.surcharge.applied is applied
    assert engine.BELOW_ORDER_VALUE_RECOMMENDATION in calc.lines[0].advisories


def test_mixed_lines_and_a_gbp_quote_are_not_evaluated_against_the_eur_rule(world: World) -> None:
    calc = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "MAPLE_TRIVET"), "100"), (item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "ASH_BOARD"), "100")],
                      toggle=True).calculation
    assert [_amount(ln.gross) for ln in calc.lines] == ["950.00", "1800.00"]
    assert _amount(calc.grand_total) == "3150.00"  # 2,750.00 + 400.00 surcharge
    gbp = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_GBP, "OAK_TRAY"), "250")], currency="GBP", toggle=True,
                     user=keys.USERS.NEHA).calculation
    assert gbp.grand_total == Money(amount=Decimal("5250.00"), currency="GBP")  # never relabelled
    assert gbp.minimum.status == "NOT_EVALUATED"
    assert gbp.surcharge.reason_code == engine.CURRENCY_NOT_EVALUATED


def test_prices_are_never_relabelled_and_items_must_be_visible(world: World) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_GBP, "OAK_TRAY"), "240")], currency="EUR")
    assert excinfo.value.extra["errors"][0]["code"] == "currency_mismatch"
    with pytest.raises(Forbidden):  # warehouse holds no pricing.price.read
        _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), "240")], user=keys.USERS.KABIR)
    with pytest.raises(ValidationError):  # floats are rejected at the tool boundary
        CalculateQuoteInput.model_validate({"currency": "EUR", "lines": [
            {"price_list_item_id": str(world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))), "quantity": 240.0}]})


def test_missing_rule_set_is_not_configured(personas: World) -> None:
    with pytest.raises(NotConfigured), UnitOfWork(personas.actor(keys.USERS.MEERA)) as uow:
        commercial.active_rules(uow)


def _list(world: World, code: str, *, price_type: str, currency: str, product: str, unit: str, price: str,
          valid_from: date = date(2026, 1, 1), valid_to: date | None = None, activate: bool = True) -> uuid.UUID:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": code, "name": code, "price_type": price_type, "currency": currency,
            "valid_from": valid_from, "valid_to": valid_to,
        }))
        item = pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref(product), unit_code=unit,  # type: ignore[arg-type]
                                                                 unit_price=Decimal(price)))
        if activate:
            pricing.activate_price_list(uow, pl.id)
        return item.id


def _tool_errors(world: World, item_id: uuid.UUID, quantity: str, *, currency: str = "EUR") -> list[tuple[str, object]]:
    data = CalculateQuoteInput.model_validate({
        "currency": currency, "lines": [{"price_list_item_id": item_id, "quantity": quantity}],
    })
    with pytest.raises(ValidationFailed) as excinfo, UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        CALCULATE_QUOTE.handler(uow, data)
    return [(e["code"], e["loc"][-1]) for e in excinfo.value.extra["errors"]]


def test_draft_retired_or_expired_prices_are_never_totalled(world: World) -> None:
    """A line is priced only from an active list effective on the business date, with an item effective that day:
    draft, retired, expired and not-yet-effective prices are rejected (price_not_current), never totalled."""
    draft_item = _list(world, "SMP-DRAFT", price_type="sample", currency="EUR", product="OAK_TRAY", unit="pcs",
                       price="1.0000", valid_to=date(2026, 12, 31), activate=False)
    assert _tool_errors(world, draft_item, "240") == [("price_not_current", "price_list_item_id")]
    expired_item = _list(world, "SMP-Q1", price_type="sample", currency="EUR", product="OAK_TRAY", unit="pcs",
                         price="1.0000", valid_to=date(2026, 3, 31))
    assert _tool_errors(world, expired_item, "240") == [("price_not_current", "price_list_item_id")]
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # the seeded EUR item, superseded from next month
        later = pricing.supersede_item(uow, world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY")),
                                       SupersedeItem(unit_price=Decimal("26"), valid_from=date(2026, 11, 1)))
    assert _tool_errors(world, later.id, "240") == [("price_not_current", "price_list_item_id")]  # not yet effective
    current = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), "240")], user=keys.USERS.SAHIL)
    assert _amount(current.calculation.grand_total) == keys.EXPECTED.SCENARIO_C_TOTAL  # today's price still prices
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(PriceList).where(PriceList.id == world.ref(keys.PRICE_LIST_REFS.EXP_GBP)).values(status="retired"))
    assert _tool_errors(world, world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_GBP, "OAK_TRAY")), "240", currency="GBP") == [
        ("price_not_current", "price_list_item_id"),
    ]


def test_quantities_follow_the_unit_entry_rule(world: World) -> None:
    """conventions.md §6: integer units take whole numbers; other units at most 4 decimal places (422 otherwise)."""
    oak = world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))
    assert _tool_errors(world, oak, "240.5") == [("uom_integer_only", "quantity")]
    walnut = world.ref(item_ref(keys.PRICE_LIST_REFS.DOM_INR, "WALNUT_BOARD"))
    assert _tool_errors(world, walnut, "2.5", currency="INR") == [("uom_integer_only", "quantity")]  # sheets
    sqm = _list(world, "SMP-INR-SQM", price_type="sample", currency="INR", product="WALNUT_BOARD", unit="sqm",
                price="100")
    assert _tool_errors(world, sqm, "1.12345", currency="INR") == [("uom_max_decimals", "quantity")]
    data = CalculateQuoteInput.model_validate({"currency": "INR", "lines": [{"price_list_item_id": sqm, "quantity": "1.2500"}]})
    with UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        out = CALCULATE_QUOTE.handler(uow, data)
    assert isinstance(out, CalculateQuoteOutput)
    assert out.calculation.lines[0].quantity.model_dump(mode="json") == {"value": "1.2500", "uom": "sqm"}
    assert _amount(out.calculation.grand_total) == "125.00"
    whole = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), "240.000")])  # a whole number written with zeros
    assert _amount(whole.calculation.grand_total) == "5760.00"


@pytest.mark.parametrize("quantity", ["1e27", "100000000000000", "1.1234567"])
def test_out_of_range_quantities_are_a_422_never_an_arithmetic_error(world: World, quantity: str) -> None:
    with pytest.raises(ValidationError):
        CalculateQuoteInput.model_validate({"currency": "EUR", "lines": [
            {"price_list_item_id": str(world.ref(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"))), "quantity": quantity}]})


def test_largest_wire_quantity_is_calculated(world: World) -> None:
    out = _calculate(world, [(item_ref(keys.PRICE_LIST_REFS.EXP_EUR, "OAK_TRAY"), "99999999999999")])
    assert _amount(out.calculation.grand_total) == "2399999999999976.00"
