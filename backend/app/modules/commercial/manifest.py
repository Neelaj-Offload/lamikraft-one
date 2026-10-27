"""Commercial module manifest: rule sets, read API, calculate_quote tool, catalogue price columns, v1 seed."""

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


def _on_load() -> None:
    # the catalogue's list and overview price columns (UI-35, UI-39) come from pricing + the engine; pricing and
    # commercial depend on the catalogue, so the catalogue receives them as a contribution instead of importing them
    from app.modules.catalogue.service import register_price_columns
    from app.modules.commercial.service import product_price_columns

    register_price_columns(product_price_columns)


MANIFEST = ModuleManifest(
    name="commercial",
    models=("app.modules.commercial.models",),
    policies=list(POLICIES),
    routers=[_router],
    tools=list(TOOLS),
    seeds=[SeedDef(name="commercial.world", order=40, run=_seed, slice_no=1)],
    on_load=_on_load,
)
