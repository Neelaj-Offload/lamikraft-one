"""Catalogue module manifest: models, policies, read API, product search provider, source reader, seed.

Permissions and events are registered centrally from the frozen catalogues (``authz``/``events`` manifests).
"""

from __future__ import annotations

from typing import Any

from app.modules.catalogue.policies import POLICIES
from app.modules.catalogue.search import PRODUCT_SEARCH
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.catalogue.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.catalogue import seed_catalogue

    seed_catalogue(ctx)


def _on_load() -> None:
    from app.modules.catalogue.service import read_product_facts
    from app.platform.sources import register_reader

    register_reader("catalogue.product", read_product_facts)


MANIFEST = ModuleManifest(
    name="catalogue",
    models=("app.modules.catalogue.models",),
    policies=list(POLICIES),
    routers=[_router],
    search_providers=[PRODUCT_SEARCH],
    seeds=[SeedDef(name="catalogue.world", order=30, run=_seed, slice_no=1)],
    on_load=_on_load,
)
