"""Calendar boundary behaviour (scenario B: midnight, weekend and shift boundaries)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.platform.org.workcal import CalendarView

IST = ZoneInfo("Asia/Kolkata")


def test_rollover_keeps_early_hours_on_previous_work_date() -> None:
    v = CalendarView()
    assert v.work_date(datetime(2026, 10, 13, 0, 10, tzinfo=IST)) == date(2026, 10, 12)
    assert v.work_date(datetime(2026, 10, 13, 4, 0, tzinfo=IST)) == date(2026, 10, 13)


def test_night_shift_rollover_override() -> None:
    v = CalendarView(rollover=time(8, 0), shift_start=time(22, 0), shift_end=time(6, 0))
    assert v.work_date(datetime(2026, 10, 13, 2, 0, tzinfo=IST)) == date(2026, 10, 12)
    start, end = v.shift_bounds(date(2026, 10, 12))
    assert (end - start).total_seconds() == 8 * 3600


def test_sunday_is_non_working_and_next_working_day_skips_it() -> None:
    v = CalendarView()
    sunday = date(2026, 10, 18)
    assert v.day_type(sunday) == "non_working"
    assert v.next_working_day(date(2026, 10, 17)) == date(2026, 10, 19)
    holiday = CalendarView(holidays=frozenset({date(2026, 10, 19)}))
    assert holiday.day_type(date(2026, 10, 19)) == "holiday"
    assert holiday.next_working_day(date(2026, 10, 17)) == date(2026, 10, 20)


def test_window_and_end_of_day_due_in_utc() -> None:
    v = CalendarView()
    start, end = v.window(date(2026, 10, 12))
    assert start == datetime(2026, 10, 11, 22, 30, tzinfo=ZoneInfo("UTC"))
    assert end == datetime(2026, 10, 12, 22, 30, tzinfo=ZoneInfo("UTC"))
    assert v.end_of_day_due(date(2026, 10, 12)) == datetime(2026, 10, 12, 13, 0, tzinfo=ZoneInfo("UTC"))
