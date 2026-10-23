"""Identity manifest: models, routers (test support only when LK_ENV=test), hooks, maintenance job, seed."""

from __future__ import annotations

from typing import Any

from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.platform.identity.router import router

    return router


def _test_support_router() -> Any:
    """Mounted only in the test environment; elsewhere an empty router adds no paths (so they are 404)."""
    from fastapi import APIRouter

    from app.core.config import get_settings

    if not get_settings().is_test:
        return APIRouter()
    from app.platform.identity.testsupport import router

    return router


def _on_load() -> None:
    from app.core.http.deps import register_actor_resolver
    from app.core.http.middleware import register_csrf_verifier
    from app.platform.authz.actors import register_member_actor_builder
    from app.platform.identity.actors import actor_for, actor_for_job
    from app.platform.identity.http import resolve_actor, verify_csrf
    from app.platform.jobs.runtime import register_actor_builder

    register_actor_resolver(resolve_actor)
    register_csrf_verifier(verify_csrf)
    register_member_actor_builder(actor_for)
    register_actor_builder(actor_for_job)


def _purge_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from app.platform.identity.service import purge_auth_state

    return purge_auth_state(ctx.uow)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.identity import seed_identity

    seed_identity(ctx)


MANIFEST = ModuleManifest(
    name="identity",
    models=("app.platform.identity.models", "app.platform.identity.auth_models"),
    routers=[_router, _test_support_router],
    jobs=[JobDef(kind="identity.purge_auth_state", handler=_purge_job, queue="default", max_attempts=3)],
    schedules=[
        ScheduleDef(
            schedule_key="identity.purge_auth_state",
            kind="identity.purge_auth_state",
            schedule_type="interval",
            interval_seconds=3600,
        )
    ],
    seeds=[SeedDef(name="identity", order=10, run=_seed, slice_no=1)],
    on_load=_on_load,
)
