"""``procurement.po_overdue_sweep``: the scheduled ``procurement.purchase_order.became_overdue`` events.

Every five minutes, per active company, as the system actor: open PO lines whose expected date (company-local) has
passed with goods still outstanding are stamped and announced once per PO; moving the expected date clears the stamp,
so a line that becomes late again is announced again. Idempotent: a rerun finds nothing new.
"""

from __future__ import annotations

from typing import Any

from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext

SWEEP_JOB = "procurement.po_overdue_sweep"


def po_overdue_sweep(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.procurement.purchase_orders import sweep_overdue
    from app.modules.tasks.jobs import for_each_company

    return for_each_company(ctx, SWEEP_JOB, sweep_overdue)


JOBS = [JobDef(SWEEP_JOB, po_overdue_sweep, queue="default", max_attempts=3)]
SCHEDULES = [ScheduleDef(SWEEP_JOB, SWEEP_JOB, "interval", interval_seconds=300)]
