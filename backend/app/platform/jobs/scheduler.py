"""Interval/daily schedules: enqueue due slots with dedupe keys, coalescing missed slots."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.platform.jobs.defs import ScheduleDef
from app.platform.jobs.models import Job, JobSchedule


def next_run(schedule: JobSchedule | ScheduleDef, after: datetime) -> datetime:
    if schedule.schedule_type == "interval":
        assert schedule.interval_seconds
        return after + timedelta(seconds=schedule.interval_seconds)
    tz = ZoneInfo(schedule.time_zone)
    local = after.astimezone(tz)
    assert schedule.daily_time is not None
    candidate = local.replace(
        hour=schedule.daily_time.hour, minute=schedule.daily_time.minute, second=0, microsecond=0
    )
    weekdays = set(schedule.weekdays or (1, 2, 3, 4, 5, 6, 7))
    while candidate <= local or candidate.isoweekday() not in weekdays:
        candidate = (candidate + timedelta(days=1)).replace(
            hour=schedule.daily_time.hour, minute=schedule.daily_time.minute
        )
    return candidate.astimezone(ZoneInfo("UTC"))


def sync_schedules(session: Session, defs: list[ScheduleDef], *, dev: bool) -> None:
    """Create rows for code-declared platform schedules (company-independent)."""
    now = get_clock().now()
    for d in defs:
        exists = session.scalar(select(JobSchedule.id).where(JobSchedule.schedule_key == d.schedule_key))
        if exists:
            continue
        session.add(
            JobSchedule(
                id=uuid.uuid7(),
                schedule_key=d.schedule_key,
                kind=d.kind,
                payload=d.payload or {},
                schedule_type=d.schedule_type,
                interval_seconds=d.interval_seconds,
                daily_time=d.daily_time,
                time_zone=d.time_zone,
                weekdays=list(d.weekdays) if d.weekdays else None,
                enabled=(d.enabled_in_dev or not dev),
                next_run_at=next_run(d, now),
            )
        )


def enqueue_due(session: Session, limit: int = 50) -> int:
    now = get_clock().now()
    due = list(
        session.scalars(
            select(JobSchedule)
            .where(JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now)
            .order_by(JobSchedule.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for sched in due:
        slot = sched.next_run_at.strftime("%Y%m%dT%H%M")
        session.execute(
            pg_insert(Job)
            .values(
                id=uuid.uuid7(),
                company_id=sched.company_id,
                kind=sched.kind,
                payload=sched.payload,
                dedupe_key=f"sched:{sched.id}:{slot}",
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        sched.last_enqueued_at = now
        nxt = next_run(sched, sched.next_run_at)
        while nxt <= now:  # coalesce missed slots
            nxt = next_run(sched, nxt)
        sched.next_run_at = nxt
    return len(due)
