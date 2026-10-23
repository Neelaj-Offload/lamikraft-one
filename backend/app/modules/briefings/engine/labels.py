"""Due labels in the viewer's zone, relative to the briefing's work date (deterministic)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def due_label(
    due_at: datetime | None, *, zone: str, work_date: date, kind: str | None = None, overdue: bool = False
) -> str | None:
    if due_at is None:
        return None
    local = due_at.astimezone(ZoneInfo(zone))
    clock = local.strftime("%H:%M")
    if overdue:
        when = "today" if local.date() == work_date else local.strftime("%a %d %b")
        return f"Overdue since {clock}" if local.date() == work_date else f"Overdue since {when} {clock}"
    if kind == "quote_expiry":
        # validity ends at the end of a calendar date: describe the date, not the midnight instant
        last_valid_day = (local - timedelta(seconds=1)).date()
        if last_valid_day == work_date:
            return "Expires today"
        if last_valid_day == work_date + timedelta(days=1):
            return "Expires tomorrow"
        return f"Expires {last_valid_day.strftime('%a %d %b')}"
    if local.date() == work_date:
        return f"Today {clock}"
    if local.date() == work_date + timedelta(days=1):
        return f"Tomorrow {clock}"
    if work_date < local.date() <= work_date + timedelta(days=6):
        return f"{local.strftime('%a')} {clock}"
    return f"{local.strftime('%a %d %b')} {clock}"


def local_iso(value: datetime | None, zone: str) -> str | None:
    return value.astimezone(ZoneInfo(zone)).isoformat() if value is not None else None
