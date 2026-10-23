"""Display formatting for printed documents. Decimal in, text out; floats are refused.

Money uses the currency's minor unit with HALF_UP rounding (``core.money.quantize_money``), the
currency symbol as a prefix, and Indian digit grouping (``1,23,456.00``) for INR. Formatting is
locale-independent so a document renders identically on every machine.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.money import CURRENCY_EXPONENT, CURRENCY_SYMBOL, QUANTITY_STORAGE_PLACES, quantize_money

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: Grouping per currency; anything not listed groups in thousands.
_INDIAN_GROUPING = frozenset({"INR"})


def _require_decimal(value: object, what: str) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(f"{what} must be a Decimal, not bool")
    if isinstance(value, float):
        raise TypeError(f"{what} must be a Decimal, not float (floats lose cents)")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{what} must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise TypeError(f"{what} must be a Decimal or int, not {type(value).__name__}")


def group_digits(digits: str, *, indian: bool = False) -> str:
    """Insert thousands separators into a run of ASCII digits (no sign, no decimal point)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    size = 2 if indian else 3
    groups: list[str] = []
    while len(head) > size:
        groups.insert(0, head[-size:])
        head = head[:-size]
    groups.insert(0, head)
    return ",".join(groups) + "," + tail


def _grouped(text: str, *, indian: bool) -> str:
    """Group the integer part of a plain fixed-point string; sign and fraction are kept as given."""
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    whole, dot, fraction = text.partition(".")
    body = group_digits(whole, indian=indian) + (dot + fraction if fraction else "")
    is_zero = all(ch in "0." for ch in text)
    return "-" + body if negative and not is_zero else body


def _with_symbol(text: str, symbol: str) -> str:
    return f"-{symbol}{text[1:]}" if text.startswith("-") else f"{symbol}{text}"


def _currency_places(currency: str) -> int:
    if currency not in CURRENCY_EXPONENT:
        raise ValueError(f"unsupported currency {currency!r}")
    return CURRENCY_EXPONENT[currency]


def format_money(amount: Decimal | int, currency: str) -> str:
    """``€5,760.00``, ``₹1,23,456.00``, ``-$12.50``. Rounds HALF_UP to the minor unit."""
    value = _require_decimal(amount, "amount")
    _currency_places(currency)
    text = format(quantize_money(value, currency), "f")
    return _with_symbol(_grouped(text, indian=currency in _INDIAN_GROUPING), CURRENCY_SYMBOL[currency])


def format_unit_price(amount: Decimal | int, currency: str, *, max_places: int = 4) -> str:
    """A unit price keeps up to ``max_places`` decimals (stored at 4) but never fewer than the
    currency's minor unit: ``€24.00``, ``€0.045``, ``€1.2345``."""
    value = _require_decimal(amount, "unit price")
    minor = _currency_places(currency)
    places = max(minor, max_places)
    text = format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0").ljust(minor, "0")
    text = f"{whole}.{fraction}" if fraction else whole
    return _with_symbol(_grouped(text, indian=currency in _INDIAN_GROUPING), CURRENCY_SYMBOL[currency])


def format_quantity(
    value: Decimal | int, uom: str | None = None, *, max_places: int = 4, indian: bool = False
) -> str:
    """``240 pcs``, ``12.5 sqm``, ``1,200 pcs``: trailing zeros trimmed, at most ``max_places``."""
    number = _require_decimal(value, "quantity")
    if not 0 <= max_places <= 6:
        raise ValueError("max_places must be between 0 and 6")
    step = Decimal(1).scaleb(-max_places)
    rounded = number.quantize(QUANTITY_STORAGE_PLACES, rounding=ROUND_HALF_UP).quantize(
        step, rounding=ROUND_HALF_UP
    )
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    rendered = _grouped(text, indian=indian)
    unit = (uom or "").strip()
    return f"{rendered} {unit}" if unit else rendered


def format_date(value: date | datetime, tz: str | tzinfo | None = None) -> str:
    """``12 Oct 2026``. A datetime must be timezone-aware and needs ``tz`` (the company's zone):
    a UTC instant late in the evening is already the next day in India."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetimes are ambiguous on documents; pass an aware datetime")
        if tz is None:
            raise ValueError("pass the company time zone to print a datetime as a date")
        zone = ZoneInfo(tz) if isinstance(tz, str) else tz
        value = value.astimezone(zone).date()
    elif not isinstance(value, date):
        raise TypeError(f"expected date or datetime, not {type(value).__name__}")
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def format_datetime(value: datetime, tz: str | tzinfo) -> str:
    """``12 Oct 2026, 08:55`` in the given zone (24-hour clock)."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetimes are ambiguous on documents; pass an aware datetime")
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    local = value.astimezone(zone)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}, {local.hour:02d}:{local.minute:02d}"
