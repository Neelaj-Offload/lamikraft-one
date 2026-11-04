"""Pure capacity and feasibility arithmetic: calendar day minutes (shifts x machines x efficiency, exceptions,
non-working days, what-if overrides) and supply cover."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.production.capacity import CenterCalendar, Shift, _minutes_between
from app.modules.production.feasibility import Supply, _cover
from app.modules.production.schemas import CalendarRef
from app.platform.org.workcal import CalendarView

MON = date(2026, 10, 12)
SUN = date(2026, 10, 18)


def _cc(machines: int = 2, eff: str = "75", shifts: list[Shift] | None = None) -> CenterCalendar:
    center = SimpleNamespace(machine_count=machines, efficiency_pct=Decimal(eff))
    return CenterCalendar(center=center, view=CalendarView(), shifts=shifts or [Shift("d", "Day", "09:30", "18:30", 540, None)],  # type: ignore[arg-type]
                          ref=CalendarRef(id=None, code="t", name="t", source="built_in"))


def test_shift_minutes_wrap_midnight() -> None:
    from datetime import time

    assert _minutes_between(time(9, 30), time(18, 30)) == 540
    assert _minutes_between(time(22, 0), time(6, 0)) == 480


def test_day_capacity_shifts_machines_efficiency() -> None:
    cc = _cc()
    assert cc.day(MON) == (Decimal("810.0000"), "working", None)  # 540 x 2 x 75 %
    assert cc.day(SUN)[0] == 0 and cc.day(SUN)[1] == "non_working"
    two = _cc(1, "100", [Shift("d", "Day", "09:30", "18:30", 540, None), Shift("n", "Night", "22:00", "06:00", 480, 0b0000001)])
    assert two.day(MON)[0] == Decimal(1020) and two.day(date(2026, 10, 13))[0] == Decimal(540)  # night shift Mondays only


def test_exceptions_and_what_if_overrides() -> None:
    cc = _cc()
    cc.exceptions[MON] = SimpleNamespace(available_minutes=100, reason="maintenance")  # type: ignore[assignment]
    assert cc.day(MON) == (Decimal(100), "working", "maintenance")
    sim = _cc()
    sim.machine_count, sim.extra_minutes_per_day = 4, 60
    assert sim.day(MON)[0] == Decimal("1680.0000")  # 540 x 4 x 75 % + 60


def test_supply_cover_stops_when_covered_and_reports_lead_time_sources() -> None:
    a = Supply("po", uuid.uuid7(), "PO 1", Decimal(5), date(2026, 10, 13), "vendor_item")
    b = Supply("po", uuid.uuid7(), "PO 2", Decimal(10), date(2026, 10, 15), None)
    assert _cover([a, b], Decimal(4)) == (Decimal(4), date(2026, 10, 13), True)
    assert _cover([a, b], Decimal(12)) == (Decimal(12), date(2026, 10, 15), False)
    assert _cover([a], Decimal(12)) == (Decimal(5), date(2026, 10, 13), True)
