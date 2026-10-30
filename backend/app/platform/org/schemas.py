"""Org request/response models (settings, reference data, calendar). Decimals travel as DecimalStr."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.money import RatioStr


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
