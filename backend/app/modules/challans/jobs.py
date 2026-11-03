"""``challans.returnables_sweep``: the scheduled due / overdue events of returnable challans (events.md §3.9).

Every five minutes, per active company, as the system actor: an issued returnable challan whose expected return
date is today (company zone) emits ``challans.returnable.became_due`` once; one whose date has passed emits
``challans.returnable.became_overdue`` once. The ``*_notified_at`` stamps make the sweep idempotent. The
``ops.returnables`` rule family that turns these into tasks lives in the tasks module (work lane).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.challans import events as ev
from app.modules.challans.common import business_date
from app.modules.challans.models import Challan
from app.modules.challans.schemas import ChallanStatus, ReturnType
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork

SWEEP_JOB = "challans.returnables_sweep"


def sweep_returnables(uow: UnitOfWork) -> int:
    """Emit the due and overdue events not yet emitted for this company; returns the number of events."""
    today = business_date(uow)
    rows = list(
        uow.session.scalars(
            select(Challan)
            .where(
                Challan.company_id == uow.actor.company_id,
                Challan.status == ChallanStatus.ISSUED.value,
                Challan.return_type == ReturnType.RETURNABLE.value,
                Challan.deleted_at.is_(None),
                Challan.expected_return_date.is_not(None),
                Challan.expected_return_date <= today,
            )
            .order_by(Challan.expected_return_date, Challan.challan_number)
            .with_for_update(skip_locked=True)
        )
    )
    emitted = 0
    now = uow.now()
    for c in rows:
        assert c.expected_return_date is not None
        payload = ev.payload(
            ev.ReturnableDuePayload(challan_id=c.id, expected_return_date=c.expected_return_date)
        )
        if c.due_notified_at is None:
            uow.emit(ev.RETURNABLE_DUE, aggregate_id=c.id, aggregate_version=c.version, payload=payload)
            c.due_notified_at = now
            emitted += 1
        if c.expected_return_date < today and c.overdue_notified_at is None:
            uow.emit(ev.RETURNABLE_OVERDUE, aggregate_id=c.id, aggregate_version=c.version, payload=payload)
            c.overdue_notified_at = now
            emitted += 1
    return emitted


def returnables_sweep(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks.jobs import for_each_company

    return for_each_company(ctx, SWEEP_JOB, sweep_returnables)


JOBS = [JobDef(SWEEP_JOB, returnables_sweep, queue="default", max_attempts=3)]
SCHEDULES = [ScheduleDef(SWEEP_JOB, SWEEP_JOB, "interval", interval_seconds=300)]
