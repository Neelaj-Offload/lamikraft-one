"""Work calendars: workweek, shifts, holidays, assignments and the day-rollover rule.

``work_date(t) = (local(t) - rollover).date()`` — with a 04:00 rollover, 00:10 on Tuesday still
belongs to Monday's work date. Briefings, SLAs, overdue sweeps and production capacity all use
these functions; there is no second calendar implementation (docs/architecture/conventions.md).
Defaults (configurable): Asia/Kolkata, Monday–Saturday, 09:30–18:30, rollover 04:00.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, Time, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin

MON_TO_SAT_MASK = 0b0111111  # Mon=1, Tue=2, ... Sat=32, Sun=64
DEFAULT_TZ = "Asia/Kolkata"
DEFAULT_START = time(9, 30)
DEFAULT_END = time(18, 30)
DEFAULT_ROLLOVER = time(4, 0)


class WorkCalendar(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "work_calendar"

    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TZ)
    workweek_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=MON_TO_SAT_MASK)
    day_rollover_local: Mapped[time] = mapped_column(Time, nullable=False, default=DEFAULT_ROLLOVER)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("uq_work_calendar_code", "company_id", "code", unique=True),
        CheckConstraint("workweek_mask > 0 AND workweek_mask < 128", name="workweek_mask_range"),
    )


class WorkShift(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "work_shift"

    calendar_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("work_calendar.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_local: Mapped[time] = mapped_column(Time, nullable=False)
    end_local: Mapped[time] = mapped_column(Time, nullable=False)
    rollover_local: Mapped[time | None] = mapped_column(Time, nullable=True)
    precompute_offset_min: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    weekday_mask: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("uq_work_shift_code", "calendar_id", "code", unique=True),
        CheckConstraint("precompute_offset_min BETWEEN 0 AND 240", name="precompute_offset_range"),
    )


class WorkHoliday(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "work_holiday"

    calendar_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("work_calendar.id"), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="full")

    __table_args__ = (
        Index("uq_work_holiday_date", "calendar_id", "holiday_date", unique=True),
        CheckConstraint("kind IN ('full','half_am','half_pm')", name="kind_values"),
    )


class WorkAssignment(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "work_assignment"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("work_calendar.id"), nullable=False)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("work_shift.id"), nullable=True)
    time_zone_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (Index("ix_work_assignment_user", "company_id", "user_id", "effective_from"),)


# ---- resolved view (pure) ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CalendarView:
    time_zone: str = DEFAULT_TZ
    workweek_mask: int = MON_TO_SAT_MASK
    rollover: time = DEFAULT_ROLLOVER
    shift_start: time = DEFAULT_START
    shift_end: time = DEFAULT_END
    precompute_offset_min: int = 30
    holidays: frozenset[date] = field(default_factory=frozenset)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.time_zone)

    def work_date(self, at: datetime) -> date:
        local = at.astimezone(self.tz)
        shifted = local - timedelta(hours=self.rollover.hour, minutes=self.rollover.minute)
        return shifted.date()

    def window(self, d: date) -> tuple[datetime, datetime]:
        """[rollover instant of d, rollover instant of d+1) in UTC."""
        start = datetime.combine(d, self.rollover, tzinfo=self.tz)
        end = datetime.combine(d + timedelta(days=1), self.rollover, tzinfo=self.tz)
        return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))

    def is_workweek_day(self, d: date) -> bool:
        return bool(self.workweek_mask & (1 << (d.isoweekday() - 1)))

    def day_type(self, d: date) -> str:
        if d in self.holidays:
            return "holiday"
        if not self.is_workweek_day(d):
            return "non_working"
        return "working"

    def next_working_day(self, d: date, n: int = 1) -> date:
        current = d
        found = 0
        for _ in range(400):
            current += timedelta(days=1)
            if self.day_type(current) == "working":
                found += 1
                if found >= n:
                    return current
        raise ValueError("no working day within 400 days; check the calendar")

    def shift_bounds(self, d: date) -> tuple[datetime, datetime]:
        start = datetime.combine(d, self.shift_start, tzinfo=self.tz)
        end_day = d + timedelta(days=1) if self.shift_end <= self.shift_start else d
        end = datetime.combine(end_day, self.shift_end, tzinfo=self.tz)
        return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))

    def precompute_at(self, d: date) -> datetime:
        start, _ = self.shift_bounds(d)
        return start - timedelta(minutes=self.precompute_offset_min)

    def end_of_day_due(self, d: date) -> datetime:
        """The default operational deadline for 'today': end of the shift on work date d."""
        return self.shift_bounds(d)[1]


def resolve_view(uow, user_id: uuid.UUID | None, on: date | None = None) -> CalendarView:  # type: ignore[no-untyped-def]
    """The calendar a user works to: assignment -> company default calendar -> built-in default."""
    session = uow.session
    company_id = uow.actor.company_id
    calendar: WorkCalendar | None = None
    shift: WorkShift | None = None
    tz_override: str | None = None
    if user_id is not None:
        q = select(WorkAssignment).where(WorkAssignment.company_id == company_id, WorkAssignment.user_id == user_id)
        if on is not None:
            q = q.where(WorkAssignment.effective_from <= on).where(
                (WorkAssignment.effective_to.is_(None)) | (WorkAssignment.effective_to >= on)
            )
        assignment = session.scalars(q.order_by(WorkAssignment.effective_from.desc())).first()
        if assignment is not None:
            calendar = session.get(WorkCalendar, assignment.calendar_id)
            shift = session.get(WorkShift, assignment.shift_id) if assignment.shift_id else None
            tz_override = assignment.time_zone_override
    if calendar is None:
        calendar = session.scalars(
            select(WorkCalendar).where(WorkCalendar.company_id == company_id, WorkCalendar.is_default.is_(True))
        ).first()
    if calendar is None:
        return CalendarView()
    if shift is None:
        shift = session.scalars(
            select(WorkShift).where(WorkShift.calendar_id == calendar.id, WorkShift.active.is_(True)).order_by(WorkShift.code)
        ).first()
    holidays = frozenset(
        session.scalars(
            select(WorkHoliday.holiday_date).where(WorkHoliday.calendar_id == calendar.id, WorkHoliday.kind == "full")
        )
    )
    return CalendarView(
        time_zone=tz_override or calendar.time_zone,
        workweek_mask=calendar.workweek_mask,
        rollover=(shift.rollover_local if shift and shift.rollover_local else calendar.day_rollover_local),
        shift_start=shift.start_local if shift else DEFAULT_START,
        shift_end=shift.end_local if shift else DEFAULT_END,
        precompute_offset_min=shift.precompute_offset_min if shift else 30,
        holidays=holidays,
    )


def ensure_default_calendar(uow) -> WorkCalendar:  # type: ignore[no-untyped-def]
    existing = uow.session.scalars(
        select(WorkCalendar).where(WorkCalendar.company_id == uow.actor.company_id, WorkCalendar.is_default.is_(True))
    ).first()
    if existing is not None:
        return existing
    cal = WorkCalendar(code="office", name="Office (Mon–Sat)", is_default=True)
    uow.add(cal)
    uow.flush()
    uow.add(WorkShift(calendar_id=cal.id, code="day", name="Day shift", start_local=DEFAULT_START, end_local=DEFAULT_END))
    uow.flush()
    return cal
