"""Commercial module manifest: rule sets, read API, calculate_quote tool, rule-set v1 seed."""

from __future__ import annotations

from typing import Any

from app.modules.commercial.policies import POLICIES
from app.modules.commercial.tools import TOOLS
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.commercial.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.commercial import seed_commercial

    seed_commercial(ctx)


MANIFEST = ModuleManifest(
    name="commercial",
    models=("app.modules.commercial.models",),
    policies=list(POLICIES),
    routers=[_router],
    tools=list(TOOLS),
    seeds=[SeedDef(name="commercial.world", order=40, run=_seed, slice_no=1)],
)
