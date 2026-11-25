"""Marketplaces module manifest: models, API and the production sync schedule (live channels only)."""

from __future__ import annotations

from typing import Any

from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest

SYNC_JOB = "marketplaces.sync_live_channels"


def _router() -> Any:
    from app.modules.marketplaces.router import router

    return router


def _sync_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Every 15 minutes in production: sync each active live channel of each active company."""
    from sqlalchemy import select

    from app.modules.marketplaces import service
    from app.modules.marketplaces.models import MarketplaceChannel
    from app.platform.authz.context import ActorContext
    from app.platform.org.models import Company
    from app.platform.uow import UnitOfWork

    synced = 0
    for company_id in list(ctx.uow.session.scalars(select(Company.id).where(Company.status == "active"))):
        with UnitOfWork(ActorContext.system(company_id, reason=SYNC_JOB)) as uow:
            ids = list(uow.session.scalars(select(MarketplaceChannel.id).where(
                MarketplaceChannel.company_id == company_id, MarketplaceChannel.mode == "live",
                MarketplaceChannel.is_active.is_(True))))
        for channel_id in ids:
            with UnitOfWork(ActorContext.system(company_id, reason=SYNC_JOB)) as uow:
                service.sync_channel(uow, channel_id)
                synced += 1
    return {"channels": synced}


MANIFEST = ModuleManifest(
    name="marketplaces",
    models=("app.modules.marketplaces.models",),
    routers=[_router],
    jobs=[JobDef(SYNC_JOB, _sync_job, queue="default", max_attempts=3)],
    schedules=[ScheduleDef(SYNC_JOB, SYNC_JOB, "interval", interval_seconds=900, enabled_in_dev=False)],
)
