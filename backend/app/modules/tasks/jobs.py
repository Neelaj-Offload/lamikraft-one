"""Tasks jobs: the overdue sweep (the only time-driven fact), reminder dispatch and the visibility
consistency job that re-derives eligibility and scope attributes after access changes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.platform.authz.context import ActorContext
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork


def for_each_company(ctx: JobContext, reason: str, fn: Callable[[UnitOfWork], int]) -> dict[str, Any]:
    """Run ``fn`` per active company, each in its own system unit of work (like approvals.expire_due)."""
    from app.platform.org.models import Company

    if ctx.uow.actor.company_id is not None:
        return {"count": fn(ctx.uow)}
    company_ids = list(ctx.uow.session.scalars(select(Company.id).where(Company.status == "active").order_by(Company.id)))
    total = 0
    for company_id in company_ids:
        with UnitOfWork(ActorContext.system(company_id, reason=reason)) as uow:
            total += fn(uow)
    return {"count": total, "companies": len(company_ids)}


def overdue_sweep(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks import service

    return for_each_company(ctx, "tasks.overdue_sweep", service.sweep_overdue)


def reminder_dispatch(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks import service

    return for_each_company(ctx, "tasks.reminder_dispatch", service.dispatch_reminders)


def visibility_consistency(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks.rules.consumer import rederive_open

    if ctx.uow.actor.company_id is None:
        return {"count": 0}
    count = rederive_open(ctx.uow)
    cause = payload.get("cause_event_id")
    return {"count": count, "cause_event_id": str(uuid.UUID(cause)) if cause else None}


JOBS = [
    JobDef("tasks.overdue_sweep", overdue_sweep, queue="default", max_attempts=3),
    JobDef("tasks.reminder_dispatch", reminder_dispatch, queue="default", max_attempts=3),
    JobDef("tasks.visibility_consistency", visibility_consistency, queue="default", max_attempts=5),
]
SCHEDULES = [
    ScheduleDef("tasks.overdue_sweep", "tasks.overdue_sweep", "interval", interval_seconds=60),
    ScheduleDef("tasks.reminder_dispatch", "tasks.reminder_dispatch", "interval", interval_seconds=60),
]
