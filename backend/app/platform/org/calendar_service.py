"""Work calendar service: the actor's calendar for today, and calendar maintenance used by seeds.

All date arithmetic lives in ``app/platform/org/workcal.py`` (the single calendar implementation). The
maintenance commands (``org.calendar.manage``) are seed/CLI-only in Slice 1; the editor UI is Slice 2.
"""

from __future__ import annotations

import uuid
from datetime import date, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.platform.org.schemas import HolidayRead, MyCalendar, ShiftWindow
from app.platform.org.workcal import (
    DEFAULT_ROLLOVER,
    MON_TO_SAT_MASK,
    WorkCalendar,
    WorkHoliday,
    WorkShift,
    resolve_calendar,
)
from app.platform.service import command, query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

UPCOMING_HOLIDAY_DAYS = 60


def _weekdays(mask: int) -> list[int]:
    return [d for d in range(1, 8) if mask & (1 << (d - 1))]


@query("org.calendar.read")
def my_calendar(uow: UnitOfWork) -> MyCalendar:
    now = uow.now()
    provisional = resolve_calendar(uow, uow.actor.user_id)
    today = provisional.view.work_date(now)
    resolved = resolve_calendar(uow, uow.actor.user_id, on=today)  # assignments are effective-dated
    view = resolved.view
    work_date = view.work_date(now)
    starts_at, ends_at = view.shift_bounds(work_date)
    upcoming: list[HolidayRead] = []
    if resolved.calendar is not None:
        rows = uow.session.scalars(
            select(WorkHoliday)
            .where(
                WorkHoliday.calendar_id == resolved.calendar.id,
                WorkHoliday.holiday_date >= work_date,
                WorkHoliday.holiday_date <= work_date + timedelta(days=UPCOMING_HOLIDAY_DAYS),
            )
            .order_by(WorkHoliday.holiday_date)
        )
        upcoming = [HolidayRead(date=h.holiday_date, name=h.name, kind=h.kind) for h in rows]
    day_type = view.day_type(work_date)
    return MyCalendar(
        source=resolved.source,  # type: ignore[arg-type]
        calendar_code=resolved.calendar.code if resolved.calendar else None,
        calendar_name=resolved.calendar.name if resolved.calendar else None,
        time_zone=view.time_zone,
        server_now=now,
        work_date=work_date,
        day_type=day_type,  # type: ignore[arg-type]
        is_working_day=day_type == "working",
        rollover_local=view.rollover,
        workweek=_weekdays(view.workweek_mask),
        shift=ShiftWindow(
            code=resolved.shift.code if resolved.shift else None,
            name=resolved.shift.name if resolved.shift else None,
            start_local=view.shift_start,
            end_local=view.shift_end,
            starts_at=starts_at,
            ends_at=ends_at,
        ),
        precompute_at=view.precompute_at(work_date),
        next_working_day=view.next_working_day(work_date),
        upcoming_holidays=upcoming,
    )


def _check_zone(time_zone: str) -> None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed(
            errors=[{"loc": ["time_zone"], "msg": "unknown IANA time zone", "code": "invalid_time_zone"}]
        ) from None


@command("org.calendar.manage")
def upsert_calendar(
    uow: UnitOfWork,
    *,
    code: str,
    name: str,
    time_zone: str = "Asia/Kolkata",
    workweek_mask: int = MON_TO_SAT_MASK,
    rollover: time = DEFAULT_ROLLOVER,
    branch_id: uuid.UUID | None = None,
    is_default: bool = False,
) -> uuid.UUID:
    """Create or update a calendar by code; ``is_default`` makes it the company's only default."""
    _check_zone(time_zone)
    if not 0 < workweek_mask < 128:
        raise ValidationFailed(errors=[{"loc": ["workweek_mask"], "msg": "1..127", "code": "out_of_range"}])
    company_id = uow.actor.company_id
    calendar = uow.session.scalars(
        select(WorkCalendar).where(WorkCalendar.company_id == company_id, WorkCalendar.code == code)
    ).first()
    if is_default:
        for other in uow.session.scalars(
            select(WorkCalendar).where(
                WorkCalendar.company_id == company_id, WorkCalendar.code != code, WorkCalendar.is_default.is_(True)
            )
        ):
            other.is_default = False
        uow.flush()
    if calendar is None:
        calendar = uow.add(
            WorkCalendar(
                company_id=company_id,
                code=code,
                name=name,
                time_zone=time_zone,
                workweek_mask=workweek_mask,
                day_rollover_local=rollover,
                branch_id=branch_id,
                is_default=is_default,
            )
        )
    else:
        calendar.name = name
        calendar.time_zone = time_zone
        calendar.workweek_mask = workweek_mask
        calendar.day_rollover_local = rollover
        calendar.branch_id = branch_id
        calendar.is_default = is_default
    uow.flush()
    return calendar.id


@command("org.calendar.manage")
def upsert_shift(
    uow: UnitOfWork,
    calendar_id: uuid.UUID,
    *,
    code: str,
    name: str,
    start_local: time,
    end_local: time,
    rollover_local: time | None = None,
    precompute_offset_min: int = 30,
) -> uuid.UUID:
    if not 0 <= precompute_offset_min <= 240:
        raise ValidationFailed(errors=[{"loc": ["precompute_offset_min"], "msg": "0..240", "code": "out_of_range"}])
    shift = uow.session.scalars(
        select(WorkShift).where(
            WorkShift.company_id == uow.actor.company_id, WorkShift.calendar_id == calendar_id, WorkShift.code == code
        )
    ).first()
    if shift is None:
        shift = uow.add(
            WorkShift(
                company_id=uow.actor.company_id,
                calendar_id=calendar_id,
                code=code,
                name=name,
                start_local=start_local,
                end_local=end_local,
                rollover_local=rollover_local,
                precompute_offset_min=precompute_offset_min,
            )
        )
    else:
        shift.name = name
        shift.start_local = start_local
        shift.end_local = end_local
        shift.rollover_local = rollover_local
        shift.precompute_offset_min = precompute_offset_min
        shift.active = True
    uow.flush()
    return shift.id


@command("org.calendar.manage")
def set_holiday(
    uow: UnitOfWork, calendar_id: uuid.UUID, *, holiday_date: date, name: str, kind: str = "full"
) -> uuid.UUID:
    if kind not in {"full", "half_am", "half_pm"}:
        raise ValidationFailed(errors=[{"loc": ["kind"], "msg": "full, half_am or half_pm", "code": "invalid_choice"}])
    holiday = uow.session.scalars(
        select(WorkHoliday).where(
            WorkHoliday.company_id == uow.actor.company_id,
            WorkHoliday.calendar_id == calendar_id,
            WorkHoliday.holiday_date == holiday_date,
        )
    ).first()
    if holiday is None:
        holiday = uow.add(
            WorkHoliday(
                company_id=uow.actor.company_id, calendar_id=calendar_id, holiday_date=holiday_date, name=name, kind=kind
            )
        )
    else:
        holiday.name = name
        holiday.kind = kind
    uow.flush()
    return holiday.id
