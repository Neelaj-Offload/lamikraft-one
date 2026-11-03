from __future__ import annotations

from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest


def _router():  # type: ignore[no-untyped-def]
    from app.modules.approvals.router import router

    return router


def _expire_job(ctx, payload):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.modules.approvals import service
    from app.platform.authz.context import ActorContext
    from app.platform.org.models import Company
    from app.platform.uow import UnitOfWork

    company_ids = list(ctx.uow.session.scalars(select(Company.id).where(Company.status == "active")))
    expired = 0
    for company_id in company_ids:
        with UnitOfWork(ActorContext.system(company_id, reason="approvals.expire")) as uow:
            expired += service.expire_due(uow)
    return {"expired": expired}



MANIFEST = ModuleManifest(
    name="approvals",
    models=("app.modules.approvals.models",),
    jobs=[JobDef("approvals.expire_due", _expire_job, queue="default", max_attempts=3)],
    # Not run automatically outside production: fixture times are absolute (D0 = 2026-10-12), so the real-time sweep
    # would expire every seeded review on the first run and empty the demo and e2e Inboxes (Slice-2 merge, ADR-057).
    schedules=[
        ScheduleDef("approvals.expire_due", "approvals.expire_due", "interval", interval_seconds=300, enabled_in_dev=False)
    ],
    routers=[_router],
)
