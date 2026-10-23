"""The commercial calculation engine: pure, deterministic, Decimal-only, no I/O (ADR-017, legacy item 7).

- Line totals: ``gross = qty x unit price`` rounded HALF_UP to the currency minor unit; a percentage or fixed line
  discount (never both, never above gross) gives ``net``.
- Order-value recommendation (catalog and custom lines): ``ceil(minimum / positive unit price)`` rounded up to a
  carton multiple when ``carton_qty > 0`` (EUR 24, carton 24 -> 216). It is labelled separately from the product
  MOQ. A missing or zero price makes it unavailable with an explanation; a currency without a configured threshold
  is NOT_EVALUATED (no invented FX equivalent).
- Applicable merchandise subtotal: net of the rule set's applicable line types after line discounts, excluding tax
  and surcharge.
- Surcharge: only when a threshold exists for the currency (v1: EUR only), every line is priced, the toggle is on and
  ``0 < applicable < minimum``; exactly the minimum has none.
- Tax is not calculated (``tax`` is null; totals exclude taxes). The grand total is null while any line is unpriced.

Floats are rejected with ``TypeError`` everywhere; the result is a frozen object with a canonical input hash.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Literal

from app.core.money import CURRENCY_EXPONENT

ENGINE_VERSION = "commercial-engine/1"
LINE_TYPES = ("catalog", "custom", "manual")
RECOMMENDATION_LINE_TYPES = frozenset({"catalog", "custom"})
TAX_LABEL = "Excludes taxes"

# reason / advisory codes
BELOW_ORDER_VALUE_RECOMMENDATION = "BELOW_ORDER_VALUE_RECOMMENDATION"
BELOW_PRODUCT_MOQ = "BELOW_PRODUCT_MOQ"
NOT_CARTON_MULTIPLE = "NOT_CARTON_MULTIPLE"
PRICE_MISSING = "PRICE_MISSING"
PRICE_ZERO = "PRICE_ZERO"
TOTALS_INCOMPLETE = "TOTALS_INCOMPLETE"
CURRENCY_NOT_EVALUATED = "CURRENCY_NOT_EVALUATED"
TOGGLE_OFF = "TOGGLE_OFF"
ZERO_SUBTOTAL = "ZERO_SUBTOTAL"
AT_OR_ABOVE_MINIMUM = "AT_OR_ABOVE_MINIMUM"
APPLIED = "APPLIED"
TAX_NOT_CALCULATED = "TAX_NOT_CALCULATED"


def _decimal(value: Any, name: str, *, optional: bool = False) -> Decimal | None:
    if value is None:
        if optional:
            return None
        raise TypeError(f"{name} is required")
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal (floats are rejected), got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _q(amount: Decimal, currency: str) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-CURRENCY_EXPONENT[currency]), rounding=ROUND_HALF_UP)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


# =====================================================================================================
# inputs
# =====================================================================================================
@dataclass(frozen=True)
class Threshold:
    minimum_order_value: Decimal
    surcharge_amount: Decimal

    def __post_init__(self) -> None:
        if _decimal(self.minimum_order_value, "minimum_order_value") <= 0:  # type: ignore[operator]
            raise ValueError("minimum_order_value must be positive")
        if _decimal(self.surcharge_amount, "surcharge_amount") < 0:  # type: ignore[operator]
            raise ValueError("surcharge_amount must not be negative")


@dataclass(frozen=True)
class RuleSet:
    code: str
    version_no: int
    thresholds: Mapping[str, Threshold]
    applicable_line_types: frozenset[str]
    rule_set_id: uuid.UUID | None = None
    surcharge_label: str = "Shipping surcharge"

    def __post_init__(self) -> None:
        if isinstance(self.version_no, bool) or not isinstance(self.version_no, int) or self.version_no < 1:
            raise TypeError("version_no must be a positive int")
        for currency, threshold in self.thresholds.items():
            if currency not in CURRENCY_EXPONENT:
                raise ValueError(f"threshold currency {currency} is not enabled")
            if not isinstance(threshold, Threshold):
                raise TypeError("thresholds must map currency codes to Threshold")
        if not self.applicable_line_types or not set(self.applicable_line_types) <= set(LINE_TYPES):
            raise ValueError("applicable_line_types must be a non-empty subset of catalog, custom, manual")
        object.__setattr__(self, "thresholds", dict(self.thresholds))
        object.__setattr__(self, "applicable_line_types", frozenset(self.applicable_line_types))


@dataclass(frozen=True)
class LineInput:
    line_key: str
    line_type: Literal["catalog", "custom", "manual"]
    quantity: Decimal
    unit_price: Decimal | None
    discount_pct: Decimal | None = None
    discount_amount: Decimal | None = None
    carton_qty: int | None = None
    product_moq: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.line_key, str) or not self.line_key:
            raise TypeError("line_key must be a non-empty string")
        if self.line_type not in LINE_TYPES:
            raise ValueError(f"line_type must be one of {LINE_TYPES}")
        if _decimal(self.quantity, "quantity") < 0:  # type: ignore[operator]
            raise ValueError("quantity must not be negative")
        price = _decimal(self.unit_price, "unit_price", optional=True)
        if price is not None and price < 0:
            raise ValueError("unit_price must not be negative")
        pct = _decimal(self.discount_pct, "discount_pct", optional=True)
        amount = _decimal(self.discount_amount, "discount_amount", optional=True)
        if pct is not None and amount is not None:
            raise ValueError("a line has either a percentage or an amount discount, never both")
        if pct is not None and not Decimal(0) <= pct <= Decimal(100):
            raise ValueError("discount_pct must be between 0 and 100")
        if amount is not None and amount < 0:
            raise ValueError("discount_amount must not be negative")
        if self.carton_qty is not None and (isinstance(self.carton_qty, bool) or not isinstance(self.carton_qty, int)):
            raise TypeError("carton_qty must be an int")
        if self.carton_qty is not None and self.carton_qty < 0:
            raise ValueError("carton_qty must not be negative")
        moq = _decimal(self.product_moq, "product_moq", optional=True)
        if moq is not None and moq <= 0:
            raise ValueError("product_moq must be positive")


@dataclass(frozen=True)
class CalculationInput:
    currency: str
    lines: tuple[LineInput, ...]
    surcharge_requested: bool = False

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_EXPONENT:
            raise ValueError(f"currency {self.currency!r} is not enabled")
        if not isinstance(self.surcharge_requested, bool):
            raise TypeError("surcharge_requested must be a bool")
        lines = tuple(self.lines)
        if any(not isinstance(line, LineInput) for line in lines):
            raise TypeError("lines must be LineInput objects")
        keys = [line.line_key for line in lines]
        if len(keys) != len(set(keys)):
            raise ValueError("line keys must be unique")
        object.__setattr__(self, "lines", lines)


# =====================================================================================================
# results
# =====================================================================================================
@dataclass(frozen=True)
class Recommendation:
    status: Literal["AVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", "NOT_APPLICABLE"]
    quantity: int | None
    basis_unit_price: Decimal | None
    minimum_order_value: Decimal | None
    carton_qty: int | None
    explanation: str
    label: str = "Order-value recommendation (not a product MOQ)"


@dataclass(frozen=True)
class LineResult:
    line_key: str
    line_type: str
    quantity: Decimal
    unit_price: Decimal | None
    price_status: Literal["priced", "missing", "zero"]
    gross: Decimal | None
    discount: Decimal | None
    net: Decimal | None
    applicable: bool
    recommendation: Recommendation
    product_moq: Decimal | None
    advisories: tuple[str, ...]


@dataclass(frozen=True)
class Adjustment:
    kind: Literal["line_discount", "surcharge"]
    line_key: str | None
    label: str
    amount: Decimal


@dataclass(frozen=True)
class MinimumResult:
    status: Literal["MEETS", "BELOW", "NOT_EVALUATED"]
    minimum_order_value: Decimal | None
    shortfall: Decimal | None
    reason_code: str | None


@dataclass(frozen=True)
class SurchargeResult:
    applied: bool
    amount: Decimal
    reason_code: str
    label: str


@dataclass(frozen=True)
class CalculationResult:
    engine_version: str
    rule_set_code: str
    rule_set_id: uuid.UUID | None
    rule_set_version: int
    currency: str
    surcharge_requested: bool
    lines: tuple[LineResult, ...]
    line_count: int
    priced_line_count: int
    totals_complete: bool
    gross_subtotal: Decimal
    discount_total: Decimal
    net_subtotal: Decimal
    applicable_subtotal: Decimal
    adjustments: tuple[Adjustment, ...]
    minimum: MinimumResult
    surcharge: SurchargeResult
    tax: Decimal | None
    tax_status: str
    tax_label: str
    grand_total: Decimal | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    input_hash: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict (decimals as strings) for persistence, API output and tool results."""
        return {
            "engine_version": self.engine_version,
            "rule_set_code": self.rule_set_code,
            "rule_set_id": str(self.rule_set_id) if self.rule_set_id else None,
            "rule_set_version": self.rule_set_version,
            "currency": self.currency,
            "surcharge_requested": self.surcharge_requested,
            "lines": [
                {
                    "line_key": ln.line_key,
                    "line_type": ln.line_type,
                    "quantity": _s(ln.quantity),
                    "unit_price": _s(ln.unit_price),
                    "price_status": ln.price_status,
                    "gross": _s(ln.gross),
                    "discount": _s(ln.discount),
                    "net": _s(ln.net),
                    "applicable": ln.applicable,
                    "recommendation": {
                        "status": ln.recommendation.status,
                        "quantity": ln.recommendation.quantity,
                        "basis_unit_price": _s(ln.recommendation.basis_unit_price),
                        "minimum_order_value": _s(ln.recommendation.minimum_order_value),
                        "carton_qty": ln.recommendation.carton_qty,
                        "explanation": ln.recommendation.explanation,
                        "label": ln.recommendation.label,
                    },
                    "product_moq": _s(ln.product_moq),
                    "advisories": list(ln.advisories),
                }
                for ln in self.lines
            ],
            "line_count": self.line_count,
            "priced_line_count": self.priced_line_count,
            "totals_complete": self.totals_complete,
            "gross_subtotal": _s(self.gross_subtotal),
            "discount_total": _s(self.discount_total),
            "net_subtotal": _s(self.net_subtotal),
            "applicable_subtotal": _s(self.applicable_subtotal),
            "adjustments": [
                {"kind": a.kind, "line_key": a.line_key, "label": a.label, "amount": _s(a.amount)} for a in self.adjustments
            ],
            "minimum": {
                "status": self.minimum.status,
                "minimum_order_value": _s(self.minimum.minimum_order_value),
                "shortfall": _s(self.minimum.shortfall),
                "reason_code": self.minimum.reason_code,
            },
            "surcharge": {
                "applied": self.surcharge.applied,
                "amount": _s(self.surcharge.amount),
                "reason_code": self.surcharge.reason_code,
                "label": self.surcharge.label,
            },
            "tax": _s(self.tax),
            "tax_status": self.tax_status,
            "tax_label": self.tax_label,
            "grand_total": _s(self.grand_total),
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "input_hash": self.input_hash,
            "inputs": self.inputs,
        }


# =====================================================================================================
# calculation
# =====================================================================================================
def recommended_quantity(minimum: Decimal, unit_price: Decimal, carton_qty: int | None) -> int:
    """``ceil(minimum / unit_price)`` rounded up to a carton multiple (exact rational arithmetic)."""
    _decimal(minimum, "minimum")
    _decimal(unit_price, "unit_price")
    if unit_price <= 0:
        raise ValueError("unit_price must be positive")
    units = math.ceil(Fraction(minimum) / Fraction(unit_price))
    if carton_qty is not None and carton_qty > 0:
        units = math.ceil(Fraction(units, carton_qty)) * carton_qty
    return int(units)


def _recommendation(line: LineInput, currency: str, threshold: Threshold | None) -> Recommendation:
    if line.line_type not in RECOMMENDATION_LINE_TYPES:
        return Recommendation("NOT_APPLICABLE", None, None, None, line.carton_qty,
                              "Manual lines have no order-value recommendation.")
    if threshold is None:
        return Recommendation(
            "NOT_EVALUATED", None, None, None, line.carton_qty,
            f"No minimum order value is configured for {currency}; no foreign-currency equivalent is assumed.",
        )
    price = line.unit_price
    if price is None or price <= 0:
        return Recommendation(
            "UNAVAILABLE", None, None, threshold.minimum_order_value, line.carton_qty,
            f"No positive {currency} unit price; the recommendation cannot be calculated.",
        )
    units = recommended_quantity(threshold.minimum_order_value, price, line.carton_qty)
    carton_note = f", rounded up to a multiple of the carton quantity {line.carton_qty}" if line.carton_qty else ""
    return Recommendation(
        "AVAILABLE", units, price, threshold.minimum_order_value, line.carton_qty,
        f"{units} units reach the {currency} {format(threshold.minimum_order_value, 'f')} minimum order value at "
        f"{currency} {format(price, 'f')} per unit{carton_note}.",
    )


def _canonical_inputs(inputs: CalculationInput, rules: RuleSet) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "rule_set": {
            "code": rules.code,
            "version_no": rules.version_no,
            "thresholds": {
                c: {"minimum_order_value": _s(t.minimum_order_value), "surcharge_amount": _s(t.surcharge_amount)}
                for c, t in sorted(rules.thresholds.items())
            },
            "applicable_line_types": sorted(rules.applicable_line_types),
        },
        "currency": inputs.currency,
        "surcharge_requested": inputs.surcharge_requested,
        "lines": [
            {
                "line_key": ln.line_key,
                "line_type": ln.line_type,
                "quantity": _s(ln.quantity),
                "unit_price": _s(ln.unit_price),
                "discount_pct": _s(ln.discount_pct),
                "discount_amount": _s(ln.discount_amount),
                "carton_qty": ln.carton_qty,
                "product_moq": _s(ln.product_moq),
            }
            for ln in inputs.lines
        ],
    }


def calculate(inputs: CalculationInput, rules: RuleSet) -> CalculationResult:
    if not isinstance(inputs, CalculationInput) or not isinstance(rules, RuleSet):
        raise TypeError("calculate(CalculationInput, RuleSet)")
    currency = inputs.currency
    threshold = rules.thresholds.get(currency)
    zero = _q(Decimal(0), currency)
    line_results: list[LineResult] = []
    adjustments: list[Adjustment] = []
    warnings: list[str] = []
    for line in inputs.lines:
        advisories: list[str] = []
        price = line.unit_price
        if price is None:
            status: Literal["priced", "missing", "zero"] = "missing"
        elif price == 0:
            status = "zero"
        else:
            status = "priced"
        gross = discount = net = None
        if status == "priced":
            assert price is not None
            gross = _q(line.quantity * price, currency)
            if line.discount_pct is not None:
                discount = _q(gross * line.discount_pct / Decimal(100), currency)
            elif line.discount_amount is not None:
                discount = _q(line.discount_amount, currency)
                if discount > gross:
                    raise ValueError(f"line {line.line_key}: discount exceeds the line amount")
            else:
                discount = zero
            net = gross - discount
            if discount > 0:
                adjustments.append(Adjustment("line_discount", line.line_key, "Line discount", -discount))
        else:
            advisories.append(PRICE_MISSING if status == "missing" else PRICE_ZERO)
        recommendation = _recommendation(line, currency, threshold)
        if recommendation.status == "AVAILABLE" and recommendation.quantity is not None and line.quantity < recommendation.quantity:
            advisories.append(BELOW_ORDER_VALUE_RECOMMENDATION)
        if line.product_moq is not None and line.quantity < line.product_moq:
            advisories.append(BELOW_PRODUCT_MOQ)
        if line.carton_qty and line.quantity % line.carton_qty != 0:
            advisories.append(NOT_CARTON_MULTIPLE)
        warnings.extend(f"line:{line.line_key}:{code}" for code in advisories)
        line_results.append(
            LineResult(
                line_key=line.line_key,
                line_type=line.line_type,
                quantity=line.quantity,
                unit_price=price,
                price_status=status,
                gross=gross,
                discount=discount,
                net=net,
                applicable=line.line_type in rules.applicable_line_types,
                recommendation=recommendation,
                product_moq=line.product_moq,
                advisories=tuple(advisories),
            )
        )
    priced = [ln for ln in line_results if ln.price_status == "priced"]
    complete = len(priced) == len(line_results)
    gross_subtotal = sum((ln.gross for ln in priced if ln.gross is not None), zero)
    discount_total = sum((ln.discount for ln in priced if ln.discount is not None), zero)
    net_subtotal = sum((ln.net for ln in priced if ln.net is not None), zero)
    applicable = sum((ln.net for ln in priced if ln.applicable and ln.net is not None), zero)

    if threshold is None:
        minimum = MinimumResult("NOT_EVALUATED", None, None, CURRENCY_NOT_EVALUATED)
    elif not complete:
        minimum = MinimumResult("NOT_EVALUATED", threshold.minimum_order_value, None, TOTALS_INCOMPLETE)
    elif applicable >= threshold.minimum_order_value:
        minimum = MinimumResult("MEETS", threshold.minimum_order_value, None, None)
    else:
        minimum = MinimumResult(
            "BELOW", threshold.minimum_order_value, _q(threshold.minimum_order_value - applicable, currency), None
        )

    if threshold is None:
        reason = CURRENCY_NOT_EVALUATED
    elif not complete:
        reason = TOTALS_INCOMPLETE
    elif applicable <= 0:
        reason = ZERO_SUBTOTAL
    elif applicable >= threshold.minimum_order_value:
        reason = AT_OR_ABOVE_MINIMUM
    elif not inputs.surcharge_requested:
        reason = TOGGLE_OFF
    else:
        reason = APPLIED
    surcharge_amount = _q(threshold.surcharge_amount, currency) if reason == APPLIED and threshold else zero
    surcharge = SurchargeResult(reason == APPLIED, surcharge_amount, reason, rules.surcharge_label)
    if surcharge.applied:
        adjustments.append(Adjustment("surcharge", None, rules.surcharge_label, surcharge_amount))

    grand_total = net_subtotal + surcharge_amount if complete else None
    reason_codes = [f"MINIMUM_{minimum.status}", f"SURCHARGE_{reason}", TAX_NOT_CALCULATED]
    if not complete:
        reason_codes.append(TOTALS_INCOMPLETE)
    canonical = _canonical_inputs(inputs, rules)
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CalculationResult(
        engine_version=ENGINE_VERSION,
        rule_set_code=rules.code,
        rule_set_id=rules.rule_set_id,
        rule_set_version=rules.version_no,
        currency=currency,
        surcharge_requested=inputs.surcharge_requested,
        lines=tuple(line_results),
        line_count=len(line_results),
        priced_line_count=len(priced),
        totals_complete=complete,
        gross_subtotal=gross_subtotal,
        discount_total=discount_total,
        net_subtotal=net_subtotal,
        applicable_subtotal=applicable,
        adjustments=tuple(adjustments),
        minimum=minimum,
        surcharge=surcharge,
        tax=None,
        tax_status="not_calculated",
        tax_label=TAX_LABEL,
        grand_total=grand_total,
        reason_codes=tuple(reason_codes),
        warnings=tuple(warnings),
        input_hash=digest,
        inputs=canonical,
    )


def rules_from_params(
    *, code: str, version_no: int, params: Mapping[str, Any], rule_set_id: uuid.UUID | None = None
) -> RuleSet:
    """Build engine rules from validated rule-set params (decimal strings, never floats)."""
    def dec(value: Any) -> Decimal:
        if isinstance(value, (float, bool)):
            raise TypeError("rule-set amounts are decimal strings, never floats")
        return value if isinstance(value, Decimal) else Decimal(str(value))

    thresholds: dict[str, Threshold] = {}
    for currency, values in params["thresholds"].items():
        thresholds[currency] = Threshold(
            minimum_order_value=dec(values["minimum_order_value"]),
            surcharge_amount=dec(values["surcharge_amount"]),
        )
    return RuleSet(
        code=code,
        version_no=version_no,
        thresholds=thresholds,
        applicable_line_types=frozenset(params["applicable_line_types"]),
        rule_set_id=rule_set_id,
        surcharge_label=str(params.get("surcharge_label") or "Shipping surcharge"),
    )
