"""Persisted totals (LM-49, LP-07.5, DEBT-03) and the quote-level scenario-D cases (fixtures.md §11)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.modules.commercial import engine
from app.modules.commercial import service as commercial
from app.modules.sales import service as sales
from app.modules.sales.models import Quote, QuoteLine
from app.modules.sales.schemas import QuoteLineCreate, QuoteLineUpdate, QuotePreviewIn, QuoteUpdate
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_totals_persisted_and_lines_renumbered_atomically(world: SalesWorld) -> None:
    d = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "100"), ("MAPLE_TRIVET", "100"), ("ASH_BOARD", "100"))
    assert [ln.line_no for ln in d.lines] == [1, 2, 3]
    assert [str(ln.line_total) for ln in d.lines] == ["2400.00", "950.00", "1800.00"]
    assert str(d.totals.gross_subtotal.amount) == "5150.00" and str(d.totals.grand_total.amount) == "5150.00"
    with world.uow(keys.USERS.SAHIL) as uow:  # the totals are columns, not client arithmetic
        row = uow.session.execute(
            select(Quote.grand_total_amount, Quote.line_count, Quote.net_subtotal_amount, Quote.calc_input_hash, Quote.content_hash)
            .where(Quote.id == d.id)
        ).one()
    assert (str(row[0]), row[1], str(row[2])) == ("5150.0000", 3, "5150.0000") and row[3] and row[4]
    assert d.totals.input_hash == row[3] and d.calculation is not None and d.calculation.input_hash == row[3]

    # remove the middle line: numbers close up, totals recomputed, one version bump
    with world.uow(keys.USERS.MEERA) as uow:
        after = sales.detail(uow, sales.remove_line(uow, d.id, d.lines[1].id, expected_version=d.version))
    assert [(ln.line_no, ln.product_snapshot.product_key) for ln in after.lines] == [(1, keys.PRODUCTS.OAK_TRAY), (2, keys.PRODUCTS.ASH_BOARD)]
    assert after.lines[1].line_key == d.lines[2].line_key  # stable identity across renumbering
    assert str(after.totals.grand_total.amount) == "4200.00" and after.totals.line_count == 2 and after.version == d.version + 1
    assert after.totals.minimum.status == "BELOW" and str(after.totals.minimum.shortfall) == "800.00"
    with world.uow(keys.USERS.SAHIL) as uow:
        numbers = list(uow.session.scalars(select(QuoteLine.line_no).where(QuoteLine.quote_id == d.id).order_by(QuoteLine.line_no)))
        deferrable = uow.session.execute(text(
            "SELECT condeferrable FROM pg_constraint WHERE conname = 'uq_sales_quote_line_line_no'")).scalar_one()
    assert numbers == [1, 2] and deferrable is True


def test_calc_input_hash_matches_recomputation(world: SalesWorld) -> None:
    d = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "200"), apply_minimum_surcharge=True)
    with world.uow(keys.USERS.MEERA) as uow:
        inputs = engine.CalculationInput(
            currency="EUR",
            lines=tuple(
                engine.LineInput(line_key=str(ln.line_key), line_type="catalog", quantity=Decimal(ln.quantity), unit_price=Decimal(ln.unit_price),
                                 uom=ln.unit_code, carton_qty=ln.packaging_snapshot.carton_qty, product_moq=None)
                for ln in d.lines
            ),
            surcharge_requested=True,
        )
        result = commercial.calculate(uow, inputs)
    assert result.input_hash == d.totals.input_hash and str(result.grand_total) == "5200.00" == str(d.totals.grand_total.amount)
    assert d.totals.surcharge_applied and str(d.totals.surcharge.amount) == "400.00" and d.totals.surcharge_reason_code == "APPLIED"


@pytest.mark.parametrize(
    ("qty", "price", "toggle", "expected", "surcharge", "minimum"),
    [
        ("200", None, False, "4800.00", "TOGGLE_OFF", "BELOW"),
        ("200", None, True, "5200.00", "APPLIED", "BELOW"),
        ("240", None, True, "5760.00", "AT_OR_ABOVE_MINIMUM", "MEETS"),
        ("200", "25", True, "5000.00", "AT_OR_ABOVE_MINIMUM", "MEETS"),
    ],
)
def test_scenario_d_quote_level(world: SalesWorld, qty: str, price: str | None, toggle: bool, expected: str, surcharge: str, minimum: str) -> None:
    d = world.new_draft(keys.USERS.SAHIL, "NORDHAUS", apply_minimum_surcharge=toggle)
    with world.uow(keys.USERS.SAHIL) as uow:
        quote, _ = sales.add_line(uow, d.id, QuoteLineCreate(expected_version=d.version, product_id=world.ref("OAK_TRAY"), quantity=Decimal(qty),
                                                              unit_price=Decimal(price) if price else None))
        d = sales.detail(uow, quote)
    assert str(d.totals.grand_total.amount) == expected and d.totals.surcharge_reason_code == surcharge and d.totals.minimum.status == minimum
    assert d.lines[0].recommendation is not None and d.lines[0].recommendation.quantity == int(keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY) or price


def test_scenario_d_discount_and_currencies(world: SalesWorld) -> None:
    # 250 x 24 less 20 % = 4,800.00 -> surcharge applies with the toggle on
    d = world.new_draft(keys.USERS.SAHIL, "NORDHAUS", apply_minimum_surcharge=True)
    with world.uow(keys.USERS.SAHIL) as uow:
        quote, _ = sales.add_line(uow, d.id, QuoteLineCreate(expected_version=d.version, product_id=world.ref("OAK_TRAY"), quantity=Decimal("250"),
                                                              discount_pct=Decimal("20")))
        d = sales.detail(uow, quote)
    assert str(d.totals.gross_subtotal.amount) == "6000.00" and str(d.totals.discount_total.amount) == "1200.00"
    assert str(d.totals.applicable_subtotal.amount) == "4800.00" and str(d.totals.grand_total.amount) == "5200.00"
    assert d.review.reasons == ["discount", "below_minimum"]
    # 4,999.99 with the toggle on -> 5,399.99 (manual line keeps the exact price)
    with world.uow(keys.USERS.SAHIL) as uow:
        quote = sales.update_quote(uow, d.id, QuoteUpdate(expected_version=d.version, apply_minimum_surcharge=True))
        quote = sales.remove_line(uow, d.id, d.lines[0].id, expected_version=quote.version)
        quote, _ = sales.add_line(uow, d.id, QuoteLineCreate(expected_version=quote.version, line_type="manual", description="Panels",
                                                              quantity=Decimal("1"), unit_code="set", unit_price=Decimal("4999.99")))
        d = sales.detail(uow, quote)
    assert str(d.totals.grand_total.amount) == "5399.99"
    # a GBP quote is not evaluated against the EUR rule; no surcharge even with the toggle on
    gbp = world.new_draft(keys.USERS.NEHA, "THORNBURY", ("OAK_TRAY", "100"), apply_minimum_surcharge=True)
    assert gbp.totals.minimum.status == "NOT_EVALUATED" and gbp.totals.surcharge_reason_code == "CURRENCY_NOT_EVALUATED"
    assert str(gbp.totals.grand_total.amount) == "2100.00" and gbp.lines[0].recommendation.status == "NOT_EVALUATED"


def test_calculate_preview_matches_persisted_totals(world: SalesWorld) -> None:
    d = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(keys.USERS.MEERA) as uow:
        preview = sales.calculate_preview(
            uow, QuotePreviewIn(currency="EUR", party_id=world.ref("NORDHAUS"),
                                lines=[{"product_id": world.ref("OAK_TRAY"), "quantity": "240"}]),  # type: ignore[list-item]
        )
    assert preview.calculation.grand_total is not None and str(preview.calculation.grand_total.amount) == keys.EXPECTED.SCENARIO_C_TOTAL
    assert preview.lines[0].default_unit_price is not None and str(preview.lines[0].default_unit_price) == keys.PRICES.OAK_TRAY_EUR
    assert preview.calculation.lines[0].recommendation.quantity.value == Decimal(keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY)
    with world.uow(keys.USERS.MEERA) as uow:  # nothing persisted
        assert sales.get_quote(uow, d.id).version == d.version
