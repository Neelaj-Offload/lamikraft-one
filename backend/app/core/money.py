"""Money and quantity types.

Rules: Decimal end to end, never floats. Money always travels with its ISO currency. JSON carries
amounts as decimal strings (``{"amount": "5760.00", "currency": "EUR"}``). The API schema
declares these as strings so generated TypeScript types never expose ``number`` for money.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, WithJsonSchema

#: Enabled transaction currencies and their minor-unit exponent.
CURRENCY_EXPONENT: dict[str, int] = {"INR": 2, "EUR": 2, "USD": 2, "GBP": 2}
CurrencyCode = Literal["INR", "EUR", "USD", "GBP"]
CURRENCY_SYMBOL: dict[str, str] = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}

#: Storage precision for money columns (NUMERIC(18,4)) and unit prices.
MONEY_STORAGE_PLACES = Decimal("0.0001")
#: Quantities are NUMERIC(18,6) on disk; entry is bounded per UOM (integers or <= 4 dp).
QUANTITY_STORAGE_PLACES = Decimal("0.000001")

_DECIMAL_PATTERN = r"^-?\d{1,14}(\.\d{1,6})?$"


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("booleans are not decimals")
    if isinstance(value, float):
        raise ValueError("floats are not accepted for money or quantities; send a decimal string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty decimal")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal: {value!r}") from exc
    else:
        raise ValueError(f"unsupported decimal input type {type(value).__name__}")
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def _decimal_to_str(value: Decimal) -> str:
    # Plain notation, never scientific; keep the stored scale.
    return format(value, "f")


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(_decimal_to_str, return_type=str, when_used="always"),
    WithJsonSchema({"type": "string", "pattern": _DECIMAL_PATTERN, "examples": ["5760.00"]}),
]


def quantize_money(amount: Decimal, currency: str, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round to the currency's minor unit (HALF_UP, the commercial convention)."""
    exponent = CURRENCY_EXPONENT[currency]
    return amount.quantize(Decimal(1).scaleb(-exponent), rounding=rounding)


def quantize_unit_price(amount: Decimal) -> Decimal:
    return amount.quantize(MONEY_STORAGE_PLACES, rounding=ROUND_HALF_UP)


def quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_STORAGE_PLACES, rounding=ROUND_HALF_UP)


class Money(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: DecimalStr
    currency: CurrencyCode

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def times(self, factor: Decimal) -> Money:
        if isinstance(factor, float):
            raise TypeError("floats are not accepted")
        return Money(amount=self.amount * factor, currency=self.currency)

    def rounded(self) -> Money:
        return Money(amount=quantize_money(self.amount, self.currency), currency=self.currency)

    def _same(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(amount=Decimal(0), currency=currency)  # type: ignore[arg-type]

    def display(self) -> str:
        return f"{self.currency} {quantize_money(self.amount, self.currency):,}"


class Quantity(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: DecimalStr
    uom: str
