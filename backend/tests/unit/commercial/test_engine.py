"""The commercial engine: scenario D (fixtures.md §11) and hypothesis properties (legacy item 7, PLAN parity rule 1).

Test names follow the PARITY_MATRIX rows: BR-01 ``test_minimum_order_meets_below_not_evaluated``, BR-02/SCN-D2
``test_surcharge_table``, BR-03/SCN-D1/LM-61 ``test_recommended_quantity``, SCN-D4
``test_missing_zero_price_and_non_eur``, FG-PRC-10 ``test_product_moq_distinct_from_recommendation``."""

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
        line_key=key, line_type="catalog", quantity=Decimal(qty), uom="pcs",
        unit_price=None if price is None else Decimal(price), carton_qty=carton, **kw,  # type: ignore[arg-type]
    )


# ---- scenario D table ------------------------------------------------------------------------------------
def test_recommended_quantity() -> None:
    """SCN-D1 / BR-03 / LM-61: ceil(5000 / 24) = 209, rounded up to the carton of 24 -> 216 (advisory only)."""
    result = _calc("EUR", _line(240, OAK_TRAY_EUR))
    rec = result.lines[0].recommendation
    assert rec.status == "AVAILABLE"
    assert str(rec.quantity) == keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY == "216"
    assert rec.uom == "pcs" and result.as_dict()["lines"][0]["recommendation"]["quantity"] == {"value": "216", "uom": "pcs"}
    assert math.ceil(EUR_MIN / OAK_TRAY_EUR) == 209  # rounded up to the carton multiple: 216
    assert "not a product MOQ" in rec.label
    assert recommended_quantity(EUR_MIN, OAK_TRAY_EUR, None) == 209
    assert recommended_quantity(EUR_MIN, OAK_TRAY_EUR, 0) == 209
    standalone = engine.order_value_recommendation(RULES_V1, currency="EUR", unit_price=OAK_TRAY_EUR, carton_qty=CARTON, uom="pcs")
    assert standalone == rec  # the product-list column uses the same rule


def test_d_scenario_c_totals() -> None:
    result = _calc("EUR", _line(keys.EXPECTED.SCENARIO_C_QTY, OAK_TRAY_EUR))
    assert str(result.grand_total) == keys.EXPECTED.SCENARIO_C_TOTAL == "5760.00"
    assert result.minimum.status == "MEETS" and result.surcharge.reason_code == engine.AT_OR_ABOVE_MINIMUM
    assert str(result.gross_subtotal) == str(result.net_subtotal) == str(result.applicable_subtotal) == "5760.00"


@pytest.mark.parametrize(
    ("qty", "price", "toggle", "applicable", "grand", "reason"),
    [
        (200, OAK_TRAY_EUR, False, "4800.00", "4800.00", engine.TOGGLE_OFF),  # SCN-D2: 4,800 with the toggle off
        (200, OAK_TRAY_EUR, True, "4800.00", "5200.00", engine.APPLIED),  # SCN-D2: 4,800 + 400 with the toggle on
        (200, Decimal("25"), True, "5000.00", "5000.00", engine.AT_OR_ABOVE_MINIMUM),  # exactly 5,000: none
        (1, Decimal("4999.99"), True, "4999.99", "5399.99", engine.APPLIED),  # just below the minimum
        (0, OAK_TRAY_EUR, True, "0.00", "0.00", engine.ZERO_SUBTOTAL),  # nothing to surcharge
    ],
)
def test_surcharge_table(qty: int, price: Decimal, toggle: bool, applicable: str, grand: str, reason: str) -> None:
    """BR-02 / SCN-D2: EUR 400 only when EUR, toggled and 0 < applicable subtotal < 5,000."""
    result = _calc("EUR", _line(qty, price, carton=None), toggle=toggle)
    assert str(result.applicable_subtotal) == applicable
    assert str(result.grand_total) == grand
    assert result.surcharge.reason_code == reason
    applied = reason == engine.APPLIED
    assert result.surcharge.applied is applied
    assert str(result.surcharge.amount) == ("400.00" if applied else "0.00")
    assert result.tax is None and result.tax_status == "not_calculated" and result.tax_label == "Excludes taxes"
    assert [(a.kind, str(a.amount)) for a in result.adjustments] == ([("surcharge", "400.00")] if applied else [])


@pytest.mark.parametrize(
    ("qty", "price", "status", "shortfall"),
    [
        (240, OAK_TRAY_EUR, "MEETS", None),
        (200, OAK_TRAY_EUR, "BELOW", "200.00"),
        (200, Decimal("25"), "MEETS", None),  # exactly the minimum meets it
    ],
)
def test_minimum_order_meets_below_not_evaluated(qty: int, price: Decimal, status: str, shortfall: str | None) -> None:
    """BR-01: the EUR 5,000 minimum at quote level; other currencies are NOT_EVALUATED (no invented threshold)."""
    result = _calc("EUR", _line(qty, price))
    assert result.minimum.status == status and str(result.minimum.minimum_order_value) == keys.COMMERCIAL.EUR_MINIMUM
    assert (str(result.minimum.shortfall) if result.minimum.shortfall is not None else None) == shortfall
    for currency in ("USD", "GBP", "INR"):
        other = _calc(currency, _line(qty, price))
        assert other.minimum.status == "NOT_EVALUATED" and other.minimum.minimum_order_value is None
        assert other.minimum.reason_code == engine.CURRENCY_NOT_EVALUATED


def test_d_discount_reduces_the_applicable_subtotal() -> None:
    result = _calc("EUR", _line(250, OAK_TRAY_EUR, discount_pct=Decimal(20)), toggle=True)
    line = result.lines[0]
    assert (str(line.gross), str(line.discount), str(line.net)) == ("6000.00", "1200.00", "4800.00")
    assert str(result.applicable_subtotal) == "4800.00" and result.surcharge.applied
    assert str(result.grand_total) == "5200.00"
    assert [a.kind for a in result.adjustments] == ["line_discount", "surcharge"]
    assert str(result.discount_total) == "1200.00"


@pytest.mark.parametrize("price", [None, "0"])
def test_missing_zero_price_and_non_eur(price: str | None) -> None:
    """SCN-D4: a missing or zero price never fabricates a recommendation or a total; non-EUR is not evaluated."""
    result = _calc("EUR", _line(240, price), toggle=True)
    line = result.lines[0]
    assert line.recommendation.status == "UNAVAILABLE" and line.recommendation.quantity is None
    assert "cannot be calculated" in line.recommendation.explanation
    assert result.grand_total is None and result.totals_complete is False
    assert result.surcharge.applied is False and result.surcharge.reason_code == engine.TOTALS_INCOMPLETE
    assert engine.TOTALS_INCOMPLETE in result.reason_codes
    assert result.as_dict()["grand_total"] is None
    usd = _calc("USD", _line(200, "24"), toggle=True)
    assert usd.minimum.status == "NOT_EVALUATED" and usd.minimum.minimum_order_value is None
    assert usd.surcharge.applied is False and usd.surcharge.reason_code == engine.CURRENCY_NOT_EVALUATED
    assert usd.lines[0].recommendation.status == "NOT_EVALUATED"
    assert "no foreign-currency equivalent" in usd.lines[0].recommendation.explanation
    assert str(usd.grand_total) == "4800.00"
    assert usd.as_dict()["grand_total"] == {"amount": "4800.00", "currency": "USD"}  # never relabelled


def test_product_moq_distinct_from_recommendation() -> None:
    """FG-PRC-10: the product MOQ (from the price item) and the order-value recommendation are separate advisories."""
    result = _calc("EUR", _line(100, OAK_TRAY_EUR, product_moq=Decimal(120)))
    line = result.lines[0]
    assert set(line.advisories) == {
        engine.BELOW_ORDER_VALUE_RECOMMENDATION, engine.BELOW_PRODUCT_MOQ, engine.NOT_CARTON_MULTIPLE,
    }
    assert line.product_moq == Decimal(120) and line.recommendation.quantity == Decimal(216)
    data = result.as_dict()["lines"][0]
    assert data["product_moq"] == {"value": "120", "uom": "pcs"}
    assert data["recommendation"]["quantity"] == {"value": "216", "uom": "pcs"}
    manual = LineInput(line_key="M1", line_type="manual", quantity=Decimal(1), unit_price=Decimal("150"), uom="pcs")
    assert _calc("EUR", manual).lines[0].recommendation.status == "NOT_APPLICABLE"


def test_line_totals_round_half_up_to_the_minor_unit() -> None:
    result = _calc("EUR", _line("3", "0.0050", carton=None), _line("1", "0.0049", key="L2", carton=None))
    assert [str(ln.gross) for ln in result.lines] == ["0.02", "0.00"]  # 0.015 -> 0.02 (HALF_UP), 0.0049 -> 0.00


def test_floats_are_rejected_everywhere() -> None:
    with pytest.raises(TypeError):
        LineInput(line_key="L1", line_type="catalog", quantity=240.0, unit_price=Decimal(24), uom="pcs")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LineInput(line_key="L1", line_type="catalog", quantity=Decimal(240), unit_price=24.0, uom="pcs")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LineInput(line_key="L1", line_type="catalog", quantity=Decimal(240), unit_price=Decimal(24), uom="")
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
    with pytest.raises(TypeError):
        result.inputs["currency"] = "USD"  # type: ignore[index]
    assert result.rule_set_code == keys.COMMERCIAL.RULE_SET and result.rule_set_version == 1
    assert result.engine_version == engine.ENGINE_VERSION
    data = result.as_dict()
    assert data["inputs"]["lines"][0]["unit_price"] == "24.0000" and data["inputs"]["lines"][0]["uom"] == "pcs"
    assert data["grand_total"] == {"amount": "5760.00", "currency": "EUR"}
    assert data["lines"][0]["quantity"] == {"value": "240", "uom": "pcs"}
    assert data["lines"][0]["unit_price"] == {"amount": "24.0000", "currency": "EUR"}
    assert data["surcharge"] == {"applied": False, "amount": {"amount": "0.00", "currency": "EUR"},
                                 "reason_code": "AT_OR_ABOVE_MINIMUM", "label": "Shipping surcharge"}
    # as_dict is a fresh copy: mutating it never changes the result or its hashed inputs
    data["inputs"]["lines"][0]["unit_price"] = "1.0000"
    data["lines"][0]["unit_price"]["amount"] = "1.0000"
    assert result.inputs["lines"][0]["unit_price"] == "24.0000"
    assert result.as_dict()["inputs"]["lines"][0]["unit_price"] == "24.0000"
    assert result == _calc("EUR", _line(240, OAK_TRAY_EUR), toggle=True)


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
        LineInput(line_key=f"L{i}", line_type=t, quantity=q, unit_price=p, uom="pcs", carton_qty=CARTON)  # type: ignore[arg-type]
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
    data = result.as_dict()  # money always travels with its currency, quantities with their unit
    assert all(a["amount"]["currency"] == currency for a in data["adjustments"])
    assert data["net_subtotal"]["currency"] == currency and all(ln["quantity"]["uom"] == "pcs" for ln in data["lines"])
