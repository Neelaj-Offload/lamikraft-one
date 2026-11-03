"""Pricing module manifest: models, policies, read API, resolve_price tool, cost log redaction, seed."""

from __future__ import annotations

from typing import Any

from app.modules.pricing.policies import POLICIES
from app.modules.pricing.tools import TOOLS
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.pricing.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.pricing import seed_pricing

    seed_pricing(ctx)


def _on_load() -> None:
    from app.core.logging import register_restricted_log_fields
    from app.modules.approvals.service import register_handler
    from app.modules.pricing.fx import FX_RATE_HANDLER
    from app.modules.pricing.schemas import COST_FIELD_NAMES

    register_restricted_log_fields(COST_FIELD_NAMES)
    register_handler(FX_RATE_HANDLER)


MANIFEST = ModuleManifest(
    name="pricing",
    models=("app.modules.pricing.models",),
    policies=list(POLICIES),
    routers=[_router],
    tools=list(TOOLS),
    seeds=[SeedDef(name="pricing.world", order=40, run=_seed, slice_no=1)],
    on_load=_on_load,
)
