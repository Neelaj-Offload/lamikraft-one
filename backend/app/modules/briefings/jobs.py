"""Briefing jobs: per-member refresh after task facts change, and precompute ahead of shift start."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.platform.authz.context import ActorContext
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork

PRECOMPUTE_INTERVAL_SECONDS = 300


def refresh_user(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.briefings import service

    user_id = uuid.UUID(payload["user_id"])
    cause = str(payload.get("cause") or "event_update")
    events = [str(payload["cause_event_id"])] if payload.get("cause_event_id") else []
    version = service.refresh_member(ctx.uow, user_id, cause=cause, cause_event_ids=events)
    return {"user_id": str(user_id), "version": version.version if version is not None else None}


def precompute_company(uow: UnitOfWork) -> int:
    """Members whose shift precompute instant has passed and whose shift has not started yet."""
    from app.modules.briefings import service
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import view_as

    now = uow.now()
    created = 0
    for user_id in responsibility.active_member_ids(uow):
        actor = responsibility.member_actor(uow, user_id)
        if actor is None or not actor.can("briefings.briefing.read"):
            continue
        member = view_as(uow, actor)
        cal = responsibility.user_calendar(member, user_id)
        work_date = cal.work_date(now)
        if cal.day_type(work_date) != "working":
            continue  # no precompute or push on non-working days
        shift_start, _ = cal.shift_bounds(work_date)
        if cal.precompute_at(work_date) <= now < shift_start and service.precompute_for(member, user_id, cal, work_date):
            created += 1
    return created


def precompute_due_shifts(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.platform.org.models import Company

    if ctx.uow.actor.company_id is not None:
        return {"created": precompute_company(ctx.uow)}
    total = 0
    companies = list(ctx.uow.session.scalars(select(Company.id).where(Company.status == "active").order_by(Company.id)))
    for company_id in companies:
        with UnitOfWork(ActorContext.system(company_id, reason="briefings.precompute")) as uow:
            total += precompute_company(uow)
    return {"created": total}


JOBS = [
    JobDef("briefings.refresh_user", refresh_user, queue="briefings", max_attempts=5),
    JobDef("briefings.precompute_due_shifts", precompute_due_shifts, queue="briefings", max_attempts=3),
]
SCHEDULES = [
    ScheduleDef("briefings.precompute_due_shifts", "briefings.precompute_due_shifts", "interval",
                interval_seconds=PRECOMPUTE_INTERVAL_SECONDS),
]
