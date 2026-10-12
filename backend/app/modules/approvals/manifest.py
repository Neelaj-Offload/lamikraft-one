from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.platform.authz.permissions import ALL_SCOPES, PermissionDef, Scope
from app.platform.events.defs import EventDef
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest


class ProposalEventPayload(BaseModel):
    kind: str | None = None
    reason: str | None = None
    targets: list[dict[str, Any]] | None = None


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


_EVENTS = [
    EventDef(f"approvals.proposal.{verb}", "approvals.proposal", f"An approval request was {verb}", ProposalEventPayload)
    for verb in ("submitted", "approved", "rejected", "expired", "invalidated", "superseded", "withdrawn")
]

MANIFEST = ModuleManifest(
    name="approvals",
    models=("app.modules.approvals.models",),
    permissions=[
        PermissionDef("approvals.proposal.read", "See approval requests you made or may decide", scopes=ALL_SCOPES),
    ],
    template_grants={
        "employee": {"approvals.proposal.read": Scope.OWN},
        "admin": {"approvals.proposal.read": Scope.COMPANY},
        "management": {"approvals.proposal.read": Scope.COMPANY},
    },
    events=_EVENTS,
    jobs=[JobDef("approvals.expire_due", _expire_job, queue="default", max_attempts=3)],
    schedules=[ScheduleDef("approvals.expire_due", "approvals.expire_due", "interval", interval_seconds=300)],
    routers=[_router],
)
