"""Org request/response models (settings, reference data, calendar). Decimals travel as DecimalStr."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    TypeAdapter,
    ValidationError,
    WithJsonSchema,
)

from app.core.money import DecimalStr

#: money.py's own decimal parser (floats, booleans, blanks and non-finite values rejected), used through the
#: public ``DecimalStr`` type rather than a private helper
_DECIMAL = TypeAdapter(DecimalStr)
_RATIO_PATTERN = r"^\d{1,10}(\.\d{1,10})?$"


def _to_ratio(value: Any) -> Decimal:
    try:
        result: Decimal = _DECIMAL.validate_python(value)
    except ValidationError as exc:
        raise ValueError(exc.errors(include_url=False)[0]["msg"]) from None
    if result <= 0:
        raise ValueError("ratios (conversion factors) must be positive")
    exponent = result.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -10:
        raise ValueError("ratios carry at most 10 decimal places")
    return result


def _ratio_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


#: A conversion factor (``uom_conversion.factor`` is NUMERIC(20,10)): a positive plain decimal string with up
#: to 10 decimal places and no trailing zeros, e.g. "0.09290304" (sqft -> sqm) or "1000". ``DecimalStr`` stops at
#: 6 decimal places, which cannot carry exact unit factors. Same rules and wire format as
#: ``app.core.money.RatioStr`` on main (c518507); this lane branch predates it, and the integrator swaps this
#: alias for the kernel type at merge (docs/lanes/platform.md, contract questions).
RatioStr = Annotated[
    Decimal,
    BeforeValidator(_to_ratio),
    PlainSerializer(_ratio_to_str, return_type=str, when_used="always"),
    WithJsonSchema({"type": "string", "pattern": _RATIO_PATTERN, "examples": ["1000", "0.09290304"]}),
]


class Capability(BaseModel):
    allowed: bool
    reason_code: str | None = None


# ---- settings ---------------------------------------------------------------------------------------------
class SettingRead(BaseModel):
    key: str
    description: str
    scope: Literal["company", "branch"]
    branch_id: uuid.UUID | None
    #: the typed value (validated by the setting's definition); restricted sub-fields are null when redacted
    value: dict[str, Any]
    #: 0 while the setting still uses its default (never written)
    version: int
    configured: bool
    #: dotted paths of values that are absent ("Not configured — set in Settings")
    not_configured_fields: list[str]
    redacted_fields: list[str] = Field(default_factory=list)
    updated_at: datetime | None
    updated_by: uuid.UUID | None
    capabilities: dict[str, Capability]


class SettingUpdate(BaseModel):
    value: dict[str, Any]
    #: the version the client edited (0 when the setting was never written)
    expected_version: int = Field(ge=0)
    branch_id: uuid.UUID | None = None
    change_reason: str | None = Field(default=None, max_length=500)


class SettingRevisionRead(BaseModel):
    version: int
    value: dict[str, Any]
    redacted_fields: list[str] = Field(default_factory=list)
    changed_at: datetime
    changed_by: uuid.UUID | None
    change_reason: str | None


# ---- reference data ---------------------------------------------------------------------------------------
class CurrencyRead(BaseModel):
    code: str
    name: str
    symbol: str
    exponent: int


class UomConversionRead(BaseModel):
    from_code: str
    to_code: str
    #: 1 ``from_code`` = factor ``to_code``
    factor: RatioStr
    provenance: str


class UomRead(BaseModel):
    code: str
    name: str
    dimension: str
    is_integer: bool
    #: entry precision: integers only for integer units, otherwise at most 4 decimal places
    max_decimal_places: int
    aliases: list[str]
    #: generic (not product-specific) conversions from this unit
    conversions: list[UomConversionRead]


# ---- calendar ---------------------------------------------------------------------------------------------
class ShiftWindow(BaseModel):
    code: str | None
    name: str | None
    start_local: time
    end_local: time
    starts_at: datetime
    ends_at: datetime


class HolidayRead(BaseModel):
    date: date
    name: str
    kind: str


class MyCalendar(BaseModel):
    source: Literal["assignment", "company_default", "built_in"]
    calendar_code: str | None
    calendar_name: str | None
    time_zone: str
    server_now: datetime
    #: the actor's work date now: (local(now) - rollover).date()
    work_date: date
    day_type: Literal["working", "non_working", "holiday"]
    is_working_day: bool
    rollover_local: time
    workweek: list[int]
    shift: ShiftWindow
    precompute_at: datetime
    next_working_day: date
    upcoming_holidays: list[HolidayRead]
