"""Capacity: daily minutes per work centre from the work calendar (platform ``org.workcal``: workweek, shifts,
holidays) x machines x efficiency, overridden by per-day exceptions; load from the pending operations of released and
in-progress work orders on their planned day; overload state per (work centre, day) with
``production.capacity.overloaded`` emitted once per transition to overloaded (replays and recomputations of an
unchanged state emit nothing). ``schedule_forward`` places routing minutes first-fit into the capacity left after the
existing load (feasibility; no finite-capacity scheduler beyond first-fit, operations.md §13).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.modules.production import events as ev
from app.modules.production.common import ZERO, work_center_refs
from app.modules.production.enums import OperationStatus, OverloadStatus, WorkOrderStatus
from app.modules.production.models import (
    CapacityException,
    CapacityOverload,
    WoOperation,
    WorkCenter,
    WorkOrder,
)
from app.modules.production.schemas import (
    CalendarRef,
    CapacityDay,
    CapacityRead,
    CapacityRow,
    ShiftMinutes,
)
from app.platform.org.workcal import (
    DEFAULT_END,
    DEFAULT_START,
    CalendarView,
    WorkCalendar,
    WorkHoliday,
    WorkShift,
    resolve_calendar,
)
from app.platform.uow import UnitOfWork

LOADING = (WorkOrderStatus.RELEASED.value, WorkOrderStatus.IN_PROGRESS.value)
MAX_RANGE_DAYS = 62
HORIZON_DAYS = 370
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Shift:
    code: str
    name: str
    start: str
    end: str
    minutes: int
    weekday_mask: int | None

    def works_on(self, d: date) -> bool:
        return self.weekday_mask is None or bool(self.weekday_mask & (1 << (d.isoweekday() - 1)))


@dataclass
class CenterCalendar:
    center: WorkCenter
    view: CalendarView
    shifts: list[Shift]
    ref: CalendarRef
    exceptions: dict[date, CapacityException] = field(default_factory=dict)
    #: what-if overrides (never stored)
    machine_count: int | None = None
    extra_minutes_per_day: int = 0

    def day(self, d: date) -> tuple[Decimal, str, str | None]:
        """(minutes, day type, exception reason) for ``d``."""
        kind = self.view.day_type(d)
        exc = self.exceptions.get(d)
        if exc is not None:
            return Decimal(exc.available_minutes), kind, exc.reason
        if kind != "working":
            return ZERO, kind, None
        base = sum((s.minutes for s in self.shifts if s.works_on(d)), 0)
        machines = self.machine_count if self.machine_count is not None else self.center.machine_count
        minutes = Decimal(base) * machines * Decimal(self.center.efficiency_pct) / HUNDRED + self.extra_minutes_per_day
        return max(minutes, ZERO).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), kind, None

    def standard_day(self) -> Decimal:
        base = sum((s.minutes for s in self.shifts if s.weekday_mask is None), 0) or sum((s.minutes for s in self.shifts), 0)
        return (Decimal(base) * self.center.machine_count * Decimal(self.center.efficiency_pct) / HUNDRED).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )


def _minutes_between(start: object, end: object) -> int:
    s = start.hour * 60 + start.minute  # type: ignore[attr-defined]
    e = end.hour * 60 + end.minute  # type: ignore[attr-defined]
    return e - s if e > s else e + 24 * 60 - s


def _shift(row: WorkShift) -> Shift:
    return Shift(
        code=row.code,
        name=row.name,
        start=row.start_local.strftime("%H:%M"),
        end=row.end_local.strftime("%H:%M"),
        minutes=_minutes_between(row.start_local, row.end_local),
        weekday_mask=row.weekday_mask,
    )


def center_calendar(uow: UnitOfWork, wc: WorkCenter, *, exceptions_from: date | None = None,
                    exceptions_to: date | None = None) -> CenterCalendar:
    """The calendar a work centre works to: its own calendar (all active shifts), else the company default calendar
    (all its active shifts), else the built-in office day (Mon–Sat 09:30–18:30)."""
    cal: WorkCalendar | None = None
    source = "work_centre"
    if wc.calendar_id is not None:
        cal = uow.session.get(WorkCalendar, wc.calendar_id)
    if cal is None:
        resolved = resolve_calendar(uow, None)
        cal = resolved.calendar
        source = "company_default" if cal is not None else "built_in"
    if cal is None:
        view = CalendarView()
        shifts = [Shift("day", "Day shift", DEFAULT_START.strftime("%H:%M"), DEFAULT_END.strftime("%H:%M"),
                        _minutes_between(DEFAULT_START, DEFAULT_END), None)]
        ref = CalendarRef(id=None, code="built_in", name="Built-in office day (Mon–Sat 09:30–18:30)", source="built_in")
    else:
        rows = list(uow.session.scalars(
            select(WorkShift).where(WorkShift.calendar_id == cal.id, WorkShift.active.is_(True)).order_by(WorkShift.code)
        ))
        holidays = frozenset(uow.session.scalars(
            select(WorkHoliday.holiday_date).where(WorkHoliday.calendar_id == cal.id, WorkHoliday.kind == "full")
        ))
        view = CalendarView(time_zone=cal.time_zone, workweek_mask=cal.workweek_mask, rollover=cal.day_rollover_local,
                            holidays=holidays)
        shifts = [_shift(r) for r in rows] or [
            Shift("day", "Day shift", DEFAULT_START.strftime("%H:%M"), DEFAULT_END.strftime("%H:%M"),
                  _minutes_between(DEFAULT_START, DEFAULT_END), None)
        ]
        ref = CalendarRef(id=cal.id, code=cal.code, name=cal.name, source=source)  # type: ignore[arg-type]
    stmt = select(CapacityException).where(
        CapacityException.company_id == uow.actor.company_id, CapacityException.work_center_id == wc.id
    )
    if exceptions_from is not None:
        stmt = stmt.where(CapacityException.exception_date >= exceptions_from)
    if exceptions_to is not None:
        stmt = stmt.where(CapacityException.exception_date <= exceptions_to)
    exceptions = {e.exception_date: e for e in uow.session.scalars(stmt)}
    return CenterCalendar(center=wc, view=view, shifts=shifts, ref=ref, exceptions=exceptions)


def shift_reads(cc: CenterCalendar) -> list[ShiftMinutes]:
    return [ShiftMinutes(code=s.code, name=s.name, start=s.start, end=s.end, minutes=s.minutes) for s in cc.shifts]


# ---- load -------------------------------------------------------------------------------------------------------------
def load_by_day(
    uow: UnitOfWork, center_ids: Iterable[uuid.UUID], date_from: date, date_to: date
) -> dict[tuple[uuid.UUID, date], tuple[Decimal, list[str]]]:
    """Pending planned minutes of released / in-progress work orders per (work centre, planned day)."""
    ids = list(center_ids)
    out: dict[tuple[uuid.UUID, date], tuple[Decimal, list[str]]] = {}
    if not ids:
        return out
    rows = uow.session.execute(
        select(WoOperation.work_center_id, WoOperation.planned_date, WoOperation.planned_minutes, WorkOrder.wo_number)
        .join(WorkOrder, WorkOrder.id == WoOperation.work_order_id)
        .where(
            WoOperation.company_id == uow.actor.company_id,
            WoOperation.work_center_id.in_(ids),
            WoOperation.status == OperationStatus.PENDING.value,
            WoOperation.planned_date >= date_from,
            WoOperation.planned_date <= date_to,
            WorkOrder.status.in_(LOADING),
        )
        .order_by(WorkOrder.wo_number, WoOperation.seq)
    ).all()
    for wc_id, day, minutes, number in rows:
        total, numbers = out.get((wc_id, day), (ZERO, []))
        if number not in numbers:
            numbers = [*numbers, number]
        out[(wc_id, day)] = (total + Decimal(minutes), numbers)
    return out


def unscheduled_minutes(uow: UnitOfWork, center_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    ids = list(center_ids)
    if not ids:
        return {}
    rows = uow.session.execute(
        select(WoOperation.work_center_id, WoOperation.planned_minutes)
        .join(WorkOrder, WorkOrder.id == WoOperation.work_order_id)
        .where(
            WoOperation.company_id == uow.actor.company_id,
            WoOperation.work_center_id.in_(ids),
            WoOperation.status == OperationStatus.PENDING.value,
            WoOperation.planned_date.is_(None),
            WorkOrder.status.in_(LOADING),
        )
    ).all()
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for wc_id, minutes in rows:
        out[wc_id] += Decimal(minutes)
    return dict(out)


def _pct(load: Decimal, cap: Decimal) -> Decimal | None:
    if cap <= 0:
        return None
    return (load * HUNDRED / cap).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def capacity_view(uow: UnitOfWork, date_from: date, date_to: date, work_center_id: uuid.UUID | None = None) -> CapacityRead:
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        date_to = date_from + timedelta(days=MAX_RANGE_DAYS)
    stmt = select(WorkCenter).where(WorkCenter.company_id == uow.actor.company_id, WorkCenter.is_active.is_(True))
    if work_center_id is not None:
        stmt = stmt.where(WorkCenter.id == work_center_id)
    centers = list(uow.session.scalars(stmt.order_by(WorkCenter.code)))
    loads = load_by_day(uow, [c.id for c in centers], date_from, date_to)
    unscheduled = unscheduled_minutes(uow, [c.id for c in centers])
    refs = work_center_refs(uow, [c.id for c in centers])
    rows: list[CapacityRow] = []
    overloaded_days = 0
    for c in centers:
        cc = center_calendar(uow, c, exceptions_from=date_from, exceptions_to=date_to)
        days: list[CapacityDay] = []
        tot_cap, tot_load = ZERO, ZERO
        d = date_from
        while d <= date_to:
            cap, kind, reason = cc.day(d)
            load, numbers = loads.get((c.id, d), (ZERO, []))
            over = load > cap
            overloaded_days += int(over)
            days.append(CapacityDay(day=d, day_type=kind, capacity_minutes=cap, load_minutes=load,  # type: ignore[arg-type]
                                    utilisation_pct=_pct(load, cap), overloaded=over, exception_reason=reason,
                                    work_orders=numbers))
            tot_cap += cap
            tot_load += load
            d += timedelta(days=1)
        rows.append(CapacityRow(work_center=refs[c.id], days=days, total_capacity_minutes=tot_cap,
                                total_load_minutes=tot_load, unscheduled_minutes=unscheduled.get(c.id, ZERO)))
    return CapacityRead(date_from=date_from, date_to=date_to, rows=rows, overloaded_days=overloaded_days)


# ---- overload state -------------------------------------------------------------------------------------------------
def refresh_overloads(uow: UnitOfWork, pairs: Iterable[tuple[uuid.UUID, date]]) -> list[CapacityOverload]:
    """Recompute the overload state of each (work centre, day); emit ``production.capacity.overloaded`` when a day
    becomes overloaded. Locks the state row (advisory lock per pair first, so concurrent releases converge)."""
    emitted: list[CapacityOverload] = []
    for wc_id, day in sorted(set(pairs)):
        uow.advisory_xact_lock("production.capacity", f"{wc_id}:{day.isoformat()}")
        wc = uow.session.get(WorkCenter, wc_id)
        if wc is None:
            continue
        cc = center_calendar(uow, wc, exceptions_from=day, exceptions_to=day)
        cap, _kind, _reason = cc.day(day)
        load = load_by_day(uow, [wc_id], day, day).get((wc_id, day), (ZERO, []))[0]
        over = load > cap
        row = uow.session.scalars(
            select(CapacityOverload)
            .where(CapacityOverload.company_id == uow.actor.company_id, CapacityOverload.work_center_id == wc_id,
                   CapacityOverload.load_date == day)
            .with_for_update()
        ).first()
        if row is None:
            if not over:
                continue
            row = CapacityOverload(id=uuid.uuid7(), company_id=uow.actor.company_id, work_center_id=wc_id,
                                   load_date=day, status=OverloadStatus.OPEN.value, load_minutes=load,
                                   capacity_minutes=cap)
            uow.add(row)
            uow.flush()
            emitted.append(row)
        else:
            became = over and row.status != OverloadStatus.OPEN.value
            row.load_minutes, row.capacity_minutes = load, cap
            row.status = OverloadStatus.OPEN.value if over else OverloadStatus.RESOLVED.value
            uow.flush()
            if became:
                emitted.append(row)
    for row in emitted:
        uow.emit(ev.CAPACITY_OVERLOADED, aggregate_id=row.id, aggregate_version=row.version,
                 payload={"work_center_id": str(row.work_center_id), "date": row.load_date.isoformat()})
    return emitted


def pairs_for_work_order(uow: UnitOfWork, work_order_id: uuid.UUID) -> set[tuple[uuid.UUID, date]]:
    rows = uow.session.execute(
        select(WoOperation.work_center_id, WoOperation.planned_date).where(
            WoOperation.company_id == uow.actor.company_id, WoOperation.work_order_id == work_order_id,
            WoOperation.planned_date.is_not(None),
        )
    ).all()
    return {(r[0], r[1]) for r in rows}


# ---- forward scheduling (feasibility) ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ScheduleResult:
    finish: date | None
    #: (work centre id, minutes) that did not fit within the horizon
    unplaced: tuple[tuple[uuid.UUID, Decimal], ...]


def schedule_forward(
    uow: UnitOfWork,
    operations: list[tuple[uuid.UUID, Decimal]],
    start: date,
    *,
    calendars: Mapping[uuid.UUID, CenterCalendar] | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> ScheduleResult:
    """First-fit: each operation in sequence fills the free minutes (capacity - existing load) of its work centre day
    by day, starting on the day the previous operation finished. Deterministic; reads only."""
    cals: dict[uuid.UUID, CenterCalendar] = dict(calendars or {})
    end = start + timedelta(days=horizon_days)
    loads = load_by_day(uow, {wc for wc, _m in operations}, start, end)
    used: dict[tuple[uuid.UUID, date], Decimal] = defaultdict(lambda: ZERO)
    day = start
    finish: date | None = start
    unplaced: list[tuple[uuid.UUID, Decimal]] = []
    for wc_id, minutes in operations:
        if wc_id not in cals:
            wc = uow.session.get(WorkCenter, wc_id)
            if wc is None:
                unplaced.append((wc_id, minutes))
                continue
            cals[wc_id] = center_calendar(uow, wc, exceptions_from=start, exceptions_to=end)
        cc = cals[wc_id]
        left = minutes
        while left > 0:
            if day > end:
                unplaced.append((wc_id, left))
                finish = None
                break
            cap, _k, _r = cc.day(day)
            free = cap - loads.get((wc_id, day), (ZERO, []))[0] - used[(wc_id, day)]
            if free > 0:
                take = min(free, left)
                used[(wc_id, day)] += take
                left -= take
                if left <= 0:
                    break
            day += timedelta(days=1)
        if finish is None:
            break
        finish = day
    return ScheduleResult(finish=finish if not unplaced else None, unplaced=tuple(unplaced))


def as_date(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value
