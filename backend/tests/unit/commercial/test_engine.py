"""The commercial engine: scenario D (fixtures.md §11) and hypothesis properties (legacy item 7, PLAN parity rule 1)."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.commercial import engine
from app.modules.commercial.engine import CalculationInput, LineInput, calculate, recommended_quantity
from app.seed.world import keys

EUR_MIN = Decimal(keys.COMMERCIAL.EUR_MINIMUM)
SURCHARGE = Decimal(keys.COMMERCIAL.SURCHARGE)
OAK_TRAY_EUR = Decimal(keys.PRICES.OAK_TRAY_EUR)
CARTON = 24  # LK-OT-0450 carton_qty (fixtures.md §5)

RULES_V1 = engine.rules_from_params(
    code=keys.COMMERCIAL.RULE_SET,
    version_no=1,
    params={
        "thresholds": {"EUR": {"minimum_order_value": keys.COMMERCIAL.EUR_MINIMUM, "surcharge_amount": keys.COMMERCIAL.SURCHARGE}},
        "applicable_line_types": ["catalog", "custom", "manual"],
    },
)


def _calc(currency: str, *lines: LineInput, toggle: bool = False) -> engine.CalculationResult:
    return calculate(CalculationInput(currency=currency, lines=lines, surcharge_requested=toggle), RULES_V1)


def _line(qty: str | int, price: str | Decimal | None, *, key: str = "L1", carton: int | None = CARTON, **kw: object) -> LineInput:
    return LineInput(
        line_key=key, line_type="catalog", quantity=Decimal(qty),
        unit_price=None if price is None else Decimal(price), carton_qty=carton, **kw,  # type: ignore[arg-type]
    )


# ---- scenario D table ------------------------------------------------------------------------------------
def test_d_recommended_quantity_216_at_eur_24_carton_24() -> None:
    result = _calc("EUR", _line(240, OAK_TRAY_EUR))
    rec = result.lines[0].recommendation
    assert rec.status == "AVAILABLE"
    assert str(rec.quantity) == keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY == "216"
    assert math.ceil(EUR_MIN / OAK_TRAY_EUR) == 209  # rounded up to the carton multiple: 216
    assert "not a product MOQ" in rec.label
    assert recommended_quantity(EUR_MIN, OAK_TRAY_EUR, None) == 209
    assert recommended_quantity(EUR_MIN, OAK_TRAY_EUR, 0) == 209


def test_d_scenario_c_totals() -> None:
    result = _calc("EUR", _line(keys.EXPECTED.SCENARIO_C_QTY, OAK_TRAY_EUR))
    assert str(result.grand_total) == keys.EXPECTED.SCENARIO_C_TOTAL == "5760.00"
    assert result.minimum.status == "MEETS" and result.surcharge.reason_code == engine.AT_OR_ABOVE_MINIMUM
    assert str(result.gross_subtotal) == str(result.net_subtotal) == str(result.applicable_subtotal) == "5760.00"


@pytest.mark.parametrize(("toggle", "grand", "reason"), [(False, "4800.00", "TOGGLE_OFF"), (True, "5200.00", "APPLIED")])
def test_d_4800_toggle(toggle: bool, grand: str, reason: str) -> None:
    result = _calc("EUR", _line(200, OAK_TRAY_EUR), toggle=toggle)
    assert str(result.applicable_subtotal) == "4800.00"
    assert str(result.grand_total) == grand
    assert result.surcharge.reason_code == reason
    assert result.surcharge.applied is toggle
    assert str(result.surcharge.amount) == ("400.00" if toggle else "0.00")
    assert result.minimum.status == "BELOW" and str(result.minimum.shortfall) == "200.00"
    assert result.tax is None and result.tax_status == "not_calculated" and result.tax_label == "Excludes taxes"
    if toggle:
        assert [(a.kind, str(a.amount)) for a in result.adjustments] == [("surcharge", "400.00")]


def test_d_exactly_5000_has_no_surcharge() -> None:
    result = _calc("EUR", _line(200, "25"), toggle=True)
    assert str(result.applicable_subtotal) == "5000.00"
    assert result.surcharge.applied is False and result.surcharge.reason_code == engine.AT_OR_ABOVE_MINIMUM
    assert str(result.grand_total) == "5000.00" and result.minimum.status == "MEETS"


def test_d_4999_99_with_toggle_is_5399_99() -> None:
    result = _calc("EUR", _line(1, "4999.99", carton=None), toggle=True)
    assert str(result.grand_total) == "5399.99" and result.surcharge.applied


def test_d_discount_reduces_the_applicable_subtotal() -> None:
    result = _calc("EUR", _line(250, OAK_TRAY_EUR, discount_pct=Decimal(20)), toggle=True)
    line = result.lines[0]
    assert (str(line.gross), str(line.discount), str(line.net)) == ("6000.00", "1200.00", "4800.00")
    assert str(result.applicable_subtotal) == "4800.00" and result.surcharge.applied
    assert str(result.grand_total) == "5200.00"
    assert [a.kind for a in result.adjustments] == ["line_discount", "surcharge"]
    assert str(result.discount_total) == "1200.00"


@pytest.mark.parametrize("price", [None, "0"])
def test_d_missing_or_zero_price_is_unavailable_without_division(price: str | None) -> None:
    result = _calc("EUR", _line(240, price), toggle=True)
    line = result.lines[0]
    assert line.recommendation.status == "UNAVAILABLE" and line.recommendation.quantity is None
    assert "cannot be calculated" in line.recommendation.explanation
    assert result.grand_total is None and result.totals_complete is False
    assert result.surcharge.applied is False and result.surcharge.reason_code == engine.TOTALS_INCOMPLETE
    assert engine.TOTALS_INCOMPLETE in result.reason_codes


def test_d_usd_minimum_not_evaluated_and_no_surcharge() -> None:
    result = _calc("USD", _line(200, "24"), toggle=True)
    assert result.minimum.status == "NOT_EVALUATED" and result.minimum.minimum_order_value is None
    assert result.surcharge.applied is False and result.surcharge.reason_code == engine.CURRENCY_NOT_EVALUATED
    assert result.lines[0].recommendation.status == "NOT_EVALUATED"
    assert "no foreign-currency equivalent" in result.lines[0].recommendation.explanation
    assert str(result.grand_total) == "4800.00"


def test_zero_subtotal_has_no_surcharge() -> None:
    result = _calc("EUR", _line(0, OAK_TRAY_EUR), toggle=True)
    assert result.surcharge.reason_code == engine.ZERO_SUBTOTAL and str(result.grand_total) == "0.00"


def test_advisories_are_distinct_from_product_moq() -> None:
    result = _calc("EUR", _line(100, OAK_TRAY_EUR, product_moq=Decimal(120)))
    assert set(result.lines[0].advisories) == {
        engine.BELOW_ORDER_VALUE_RECOMMENDATION, engine.BELOW_PRODUCT_MOQ, engine.NOT_CARTON_MULTIPLE,
    }
    manual = LineInput(line_key="M1", line_type="manual", quantity=Decimal(1), unit_price=Decimal("150"))
    assert _calc("EUR", manual).lines[0].recommendation.status == "NOT_APPLICABLE"


def test_line_totals_round_half_up_to_the_minor_unit() -> None:
    result = _calc("EUR", _line("3", "0.0050", carton=None), _line("1", "0.0049", key="L2", carton=None))
    assert [str(ln.gross) for ln in result.lines] == ["0.02", "0.00"]  # 0.015 -> 0.02 (HALF_UP), 0.0049 -> 0.00


def test_floats_are_rejected_everywhere() -> None:
    with pytest.raises(TypeError):
        LineInput(line_key="L1", line_type="catalog", quantity=240.0, unit_price=Decimal(24))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LineInput(line_key="L1", line_type="catalog", quantity=Decimal(240), unit_price=24.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        engine.rules_from_params(code="x", version_no=1, params={
            "thresholds": {"EUR": {"minimum_order_value": 5000.0, "surcharge_amount": "400"}},
            "applicable_line_types": ["catalog"],
        })
    with pytest.raises(ValueError):
        _line(1, "-1")


def test_result_is_frozen_and_carries_its_inputs() -> None:
    result = _calc("EUR", _line(240, OAK_TRAY_EUR), toggle=True)
    with pytest.raises(AttributeError):
        result.grand_total = Decimal(0)  # type: ignore[misc]
    assert result.rule_set_code == keys.COMMERCIAL.RULE_SET and result.rule_set_version == 1
    assert result.engine_version == engine.ENGINE_VERSION
    data = result.as_dict()
    assert data["inputs"]["lines"][0]["unit_price"] == "24.0000" and data["grand_total"] == "5760.00"
    assert data["surcharge"] == {"applied": False, "amount": "0.00", "reason_code": "AT_OR_ABOVE_MINIMUM",
                                 "label": "Shipping surcharge"}


# ---- properties ------------------------------------------------------------------------------------------
prices = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("99999.9999"), places=4)
quantities = st.integers(min_value=0, max_value=50_000).map(Decimal)
cartons = st.one_of(st.none(), st.integers(min_value=0, max_value=500))


@settings(max_examples=300, derandomize=True)
@given(price=prices, carton=cartons)
def test_recommendation_is_the_minimal_carton_multiple_reaching_the_minimum(price: Decimal, carton: int | None) -> None:
    r = recommended_quantity(EUR_MIN, price, carton)
    step = carton if carton else 1
    assert r * price >= EUR_MIN
    assert r % step == 0
    assert (r - step) * price < EUR_MIN or r - step < 0


@settings(max_examples=300, derandomize=True)
@given(
    lines=st.lists(st.tuples(quantities, st.one_of(st.none(), prices), st.sampled_from(["catalog", "custom", "manual"])),
                   min_size=1, max_size=6),
    currency=st.sampled_from(["EUR", "USD", "GBP", "INR"]),
    toggle=st.booleans(),
)
def test_engine_invariants(lines: list[tuple[Decimal, Decimal | None, str]], currency: str, toggle: bool) -> None:
    inputs = [
        LineInput(line_key=f"L{i}", line_type=t, quantity=q, unit_price=p, carton_qty=CARTON)  # type: ignore[arg-type]
        for i, (q, p, t) in enumerate(lines)
    ]
    result = _calc(currency, *inputs, toggle=toggle)
    again = _calc(currency, *inputs, toggle=toggle)
    assert result == again and result.input_hash == again.input_hash  # deterministic
    complete = all(p is not None and p > 0 for _q, p, _t in lines)
    assert result.totals_complete is complete
    for line, (q, p, _t) in zip(result.lines, lines, strict=True):
        if p is not None and p > 0:
            assert line.gross == (q * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            assert abs(line.gross - q * p) <= Decimal("0.005")
    surcharge_expected = (
        currency == "EUR" and toggle and complete and Decimal(0) < result.applicable_subtotal < EUR_MIN
    )
    assert result.surcharge.applied is surcharge_expected
    assert result.surcharge.amount == (SURCHARGE if surcharge_expected else Decimal(0))
    if complete:
        assert result.grand_total == result.net_subtotal + result.surcharge.amount + (result.tax or 0)
        assert result.applicable_subtotal == result.net_subtotal  # v1: every line type is applicable
    else:
        assert result.grand_total is None
    if currency != "EUR":
        assert result.minimum.status == "NOT_EVALUATED"
        assert all(ln.recommendation.status in ("NOT_EVALUATED", "NOT_APPLICABLE") for ln in result.lines)
