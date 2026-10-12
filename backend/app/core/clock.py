"""The single source of business time.

Every business timestamp (created_at, occurred_at, due_at, fact_at ...) is taken from a Clock in
Python. Database ``now()`` is reserved for infrastructure (job leases, heartbeats). Tests freeze
the clock globally or per company; per-company overrides only exist when ``LK_ENV=test``.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """A controllable clock for tests and fixtures."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires an aware datetime")
        self._at = at.astimezone(UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._at

    def set(self, at: datetime) -> None:
        with self._lock:
            self._at = at.astimezone(UTC)

    def advance(self, **delta: float) -> datetime:
        with self._lock:
            self._at = self._at + timedelta(**delta)
            return self._at


_system = SystemClock()
_global_override: Clock | None = None
_company_overrides: dict[uuid.UUID, Clock] = {}


def get_clock(company_id: uuid.UUID | None = None) -> Clock:
    if company_id is not None and company_id in _company_overrides:
        return _company_overrides[company_id]
    return _global_override or _system


def set_global_clock(clock: Clock | None) -> None:
    global _global_override
    _global_override = clock


def set_company_clock(company_id: uuid.UUID, clock: Clock | None) -> None:
    from app.core.config import get_settings

    if not get_settings().is_test:
        raise RuntimeError("per-company clocks are only available when LK_ENV=test")
    if clock is None:
        _company_overrides.pop(company_id, None)
    else:
        _company_overrides[company_id] = clock


def local_date(at: datetime, tz: str) -> date:
    return at.astimezone(ZoneInfo(tz)).date()


def utc(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; attach a time zone")
    return at.astimezone(UTC)
