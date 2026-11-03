"""Cutting module manifest: models, policies, the plan-number sequence, the API, the calculation job and the seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events`` manifests);
this module only names them.
"""

from __future__ import annotations

from typing import Any

from app.modules.cutting.events import PLAN_SEQUENCE
from app.modules.cutting.policies import POLICIES
from app.platform.jobs.defs import JobDef
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef

CALC_JOB = "cutting.calculate"


def _router() -> Any:
    from app.modules.cutting.router import router

    return router


def _calc_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.cutting.plans import calculation_job

    return calculation_job(ctx, payload)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.cutting import seed_cutting

    seed_cutting(ctx)


MANIFEST = ModuleManifest(
    name="cutting",
    models=("app.modules.cutting.models",),
    policies=list(POLICIES),
    sequences=[PLAN_SEQUENCE],
    routers=[_router],
    jobs=[JobDef(kind=CALC_JOB, handler=_calc_job, queue="default", max_attempts=3, lease_seconds=600)],
    # D0 08:15 (fixtures.md §8): after the D0 sales seed and before tasks (80) drain earlier events
    seeds=[SeedDef(name="cutting.world", order=78, run=_seed, slice_no=2)],
)
