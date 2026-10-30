"""Scenario C at service level (SCN-C1/C3, fixtures.md §11): Meera asks for Nordhaus's usual order."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.modules.commercial.schemas import CalculateQuoteInput
from app.modules.commercial.tools import CALCULATE_QUOTE
from app.modules.parties.schemas import ResolvePartyInput
from app.modules.parties.tools import RESOLVE_PARTY
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import ResolvePriceInput, SupersedeItem
from app.modules.pricing.tools import RESOLVE_PRICE
from app.modules.sales import service as sales
from app.modules.sales.schemas import DraftQuoteInput, FindUsualOrderInput, RefreshSnapshots
from app.modules.sales.tools import DRAFT_QUOTE, FIND_USUAL_ORDER
from app.platform.tools import FORBIDDEN_INPUT_FIELDS
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_scenario_c_nordhaus_repeat_quote(sales_world: SalesWorld) -> None:
    w = sales_world
    for tool in (RESOLVE_PARTY, FIND_USUAL_ORDER, RESOLVE_PRICE, CALCULATE_QUOTE, DRAFT_QUOTE):
        assert not FORBIDDEN_INPUT_FIELDS & set(tool.input_model.model_fields)
    with w.uow(keys.USERS.MEERA, idempotency_key=str(uuid.uuid7())) as uow:
        party = RESOLVE_PARTY.handler(uow, ResolvePartyInput(query="Nordhaus"))
        assert party.status == "unique" and party.candidates[0].display_name == keys.PARTY_NAMES["NORDHAUS"]
        usual = FIND_USUAL_ORDER.handler(uow, FindUsualOrderInput(party_id=party.candidates[0].party_id))
        assert usual.status == "found" and usual.quote_number == keys.QUOTES.PRIOR_WON and len(usual.lines) == 1
        basis = usual.lines[0]
        assert basis.product_key == keys.PRODUCTS.OAK_TRAY and str(basis.quantity) == "240.000000" and str(basis.unit_price) == keys.PRICES.OAK_TRAY_EUR
        price = RESOLVE_PRICE.handler(uow, ResolvePriceInput(product_id=basis.product_id, party_id=party.candidates[0].party_id, currency="EUR", uom="pcs"))
        assert price.status == "found" and str(price.unit_price.amount) == keys.PRICES.OAK_TRAY_EUR and price.tier == "standard"
        calc = CALCULATE_QUOTE.handler(uow, CalculateQuoteInput(currency="EUR", lines=[{"price_list_item_id": price.item_id, "quantity": "240"}]))  # type: ignore[list-item]
        assert str(calc.calculation.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL and calc.calculation.minimum.status == "MEETS"
        assert calc.calculation.surcharge.reason_code == "AT_OR_ABOVE_MINIMUM"
        assert str(calc.calculation.lines[0].recommendation.quantity.value) == keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY
        draft = DRAFT_QUOTE.handler(uow, DraftQuoteInput(party_id=party.candidates[0].party_id,
                                                         lines=[{"product_id": basis.product_id, "quantity": basis.quantity}]))  # type: ignore[list-item]
    assert draft.quote_number == keys.QUOTES.SCENARIO_C_NEW and draft.status == "draft" and draft.sent_at is None
    assert draft.owner.id == w.user_id(keys.USERS.MEERA) and draft.origin == "user"  # the tool runs as the user; agent runs mark origin
    assert str(draft.totals.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL and draft.totals.line_count == 1
    assert draft.lines[0].recommendation.quantity == int(keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY)
    assert draft.review.requires_approval is False and draft.capabilities["issue"].allowed
    with w.uow(keys.USERS.NEHA) as uow:  # Neha never sees it
        from app.core.errors import NotFound

        with pytest.raises(NotFound):
            sales.get_quote(uow, draft.id)

    # C (snapshot): a test-local supersede to 26.0000 and a rename leave the draft at 24.0000 until refresh
    with w.uow(keys.USERS.PRIYA) as uow:
        pricing.supersede_item(uow, draft.lines[0].price_list_item_id, SupersedeItem(unit_price=Decimal("26.0000"), valid_from=date(2026, 10, 12)))
    with w.uow(keys.USERS.MEERA) as uow:
        stale = sales.get_quote(uow, draft.id)
    assert str(stale.lines[0].unit_price) == keys.PRICES.OAK_TRAY_EUR and str(stale.totals.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL
    assert "PRICE_CHANGED_SINCE_SNAPSHOT" in stale.lines[0].advisories
    with w.uow(keys.USERS.MEERA) as uow:
        fresh = sales.detail(uow, sales.refresh_snapshots(uow, draft.id, RefreshSnapshots(expected_version=stale.version)))
    assert str(fresh.lines[0].unit_price) == "26.0000" and str(fresh.totals.grand_total.amount) == "6240.00"


def test_agent_actor_marks_origin_and_links_message(sales_world: SalesWorld) -> None:
    w = sales_world
    with w.uow(keys.USERS.MEERA, idempotency_key=str(uuid.uuid7()), actor_type="agent") as uow:
        draft = sales.draft_quote(uow, DraftQuoteInput(party_id=w.ref("NORDHAUS"), origin_message_id=w.ref(keys.MESSAGES.NORDHAUS),
                                                      lines=[{"product_key": keys.PRODUCTS.OAK_TRAY, "quantity": "240"}]))  # type: ignore[list-item]
        message = sales.get_customer_message(uow, w.ref(keys.MESSAGES.NORDHAUS))
    assert draft.origin == "agent" and draft.origin_message_id == w.ref(keys.MESSAGES.NORDHAUS)
    assert message.quote_id == w.ref("Q_NORDHAUS_DRAFT")  # the seeded draft already linked it; the link is not overwritten
    with w.uow(keys.USERS.MEERA) as uow:
        none = sales.find_repeat_quote_basis(uow, w.ref("MAISON"))
    assert none.status == "none" and none.lines == []
