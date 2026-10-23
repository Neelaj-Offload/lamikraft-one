"""Commercial rule sets and the calculate_quote tool over resolved price-list items (scenario C and D figures)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import Forbidden, NotConfigured, ValidationFailed
from app.modules.commercial import engine
from app.modules.commercial import service as commercial
from app.modules.commercial.schemas import CalculateQuoteInput, CalculateQuoteOutput, QuoteCommercialRulesV1
from app.modules.commercial.tools import CALCULATE_QUOTE
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.commercial import RULE_SET_REF
from app.seed.world.pricing import item_ref
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


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


def test_rule_set_v1_is_active_and_readable_by_management_only(world: World) -> None:
    sets = commercial.list_rule_sets(world.actor(keys.USERS.SAHIL))
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
                                           effective_from=date(2027, 1, 1)).id
    draft = commercial.get_rule_set(world.actor(keys.USERS.PRIYA), v2_id)
    assert draft.capabilities["activate"].allowed is True
    assert [(t.action, t.to_status) for t in draft.allowed_transitions] == [("activate", "active")]
    read_only = commercial.get_rule_set(world.actor(keys.USERS.SAHIL), v2_id)
    assert read_only.capabilities["activate"].reason_code == "permission_denied" and read_only.allowed_transitions == []
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        commercial.activate_rule_set(uow, v2_id)
    active = commercial.get_rule_set(world.actor(keys.USERS.PRIYA), v2_id)
    assert active.capabilities["activate"].reason_code == "rule_set_not_draft" and active.allowed_transitions == []
    statuses = {r.version_no: r.status.value for r in commercial.list_rule_sets(world.actor(keys.USERS.SAHIL))}
    assert statuses == {1: "retired", 2: "active"}
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        rules = commercial.active_rules(uow)
    assert rules.version_no == 2 and rules.thresholds["EUR"].minimum_order_value == Decimal("6000.00")
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:  # management may only read rules
        commercial.create_rule_set(uow, code="other", version_no=1, params=v2_params, effective_from=date(2027, 1, 1))


def test_scenario_c_line_through_the_tool(world: World) -> None:
    out = _calculate(world, [(item_ref("PL_EXP_EUR", "OAK_TRAY"), keys.EXPECTED.SCENARIO_C_QTY)])
    calc = out.calculation
    assert str(calc.grand_total) == keys.EXPECTED.SCENARIO_C_TOTAL
    assert calc.minimum.status == "MEETS" and calc.surcharge.reason_code == engine.AT_OR_ABOVE_MINIMUM
    assert str(calc.lines[0].recommendation.quantity) == keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY
    assert calc.lines[0].advisories == [] and calc.tax is None and calc.tax_label == "Excludes taxes"
    assert (calc.rule_set_id, calc.rule_set_version) == (world.ref(RULE_SET_REF), 1)
    ref = out.lines[0]
    assert (ref.price_list_code, ref.product_key, ref.unit_code) == (keys.PRICE_LISTS.EXP_EUR, keys.PRODUCTS.OAK_TRAY, "pcs")


@pytest.mark.parametrize(("toggle", "grand", "applied"), [(False, "4800.00", False), (True, "5200.00", True)])
def test_scenario_d_surcharge_through_the_tool(world: World, toggle: bool, grand: str, applied: bool) -> None:
    calc = _calculate(world, [(item_ref("PL_EXP_EUR", "OAK_TRAY"), "200")], toggle=toggle).calculation
    assert str(calc.applicable_subtotal) == "4800.00" and str(calc.grand_total) == grand
    assert calc.surcharge.applied is applied
    assert engine.BELOW_ORDER_VALUE_RECOMMENDATION in calc.lines[0].advisories


def test_mixed_lines_and_a_gbp_quote_are_not_evaluated_against_the_eur_rule(world: World) -> None:
    calc = _calculate(world, [(item_ref("PL_EXP_EUR", "MAPLE_TRIVET"), "100"), (item_ref("PL_EXP_EUR", "ASH_BOARD"), "100")],
                      toggle=True).calculation
    assert [str(ln.gross) for ln in calc.lines] == ["950.00", "1800.00"]
    assert str(calc.grand_total) == "3150.00"  # 2,750.00 + 400.00 surcharge
    gbp = _calculate(world, [(item_ref("PL_EXP_GBP", "OAK_TRAY"), "250")], currency="GBP", toggle=True,
                     user=keys.USERS.NEHA).calculation
    assert str(gbp.grand_total) == "5250.00" and gbp.minimum.status == "NOT_EVALUATED"
    assert gbp.surcharge.reason_code == engine.CURRENCY_NOT_EVALUATED


def test_prices_are_never_relabelled_and_items_must_be_visible(world: World) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        _calculate(world, [(item_ref("PL_EXP_GBP", "OAK_TRAY"), "240")], currency="EUR")
    assert excinfo.value.extra["errors"][0]["code"] == "currency_mismatch"
    with pytest.raises(Forbidden):  # warehouse holds no pricing.price.read
        _calculate(world, [(item_ref("PL_EXP_EUR", "OAK_TRAY"), "240")], user=keys.USERS.KABIR)
    with pytest.raises(ValidationError):  # floats are rejected at the tool boundary
        CalculateQuoteInput.model_validate({"currency": "EUR", "lines": [
            {"price_list_item_id": str(world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY"))), "quantity": 240.0}]})


def test_missing_rule_set_is_not_configured(personas: World) -> None:
    with pytest.raises(NotConfigured), UnitOfWork(personas.actor(keys.USERS.MEERA)) as uow:
        commercial.active_rules(uow)
