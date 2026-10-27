"""Parties module manifest: models, policies, the P-NNNNN sequence, API, search, resolve_party tool, seed."""

from __future__ import annotations

from typing import Any

from app.modules.parties.events import PARTY_SEQUENCE
from app.modules.parties.policies import POLICIES
from app.modules.parties.search import PARTY_SEARCH
from app.modules.parties.tools import TOOLS
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.parties.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.parties import seed_parties

    seed_parties(ctx)


def _seed_changes(ctx: SeedContext) -> None:
    from app.seed.world.parties import seed_party_changes

    seed_party_changes(ctx)


def _on_load() -> None:
    from app.modules.parties.service import read_party_facts
    from app.platform.sources import register_reader

    register_reader("parties.party", read_party_facts)


MANIFEST = ModuleManifest(
    name="parties",
    models=("app.modules.parties.models",),
    policies=list(POLICIES),
    sequences=[PARTY_SEQUENCE],
    routers=[_router],
    tools=list(TOOLS),
    search_providers=[PARTY_SEARCH],
    seeds=[
        SeedDef(name="parties.world", order=20, run=_seed, slice_no=1),
        # dated changes near D0 run after the catalogue, pricing and sales history so the clock only moves forward
        SeedDef(name="parties.world.changes", order=55, run=_seed_changes, slice_no=1),
    ],
    on_load=_on_load,
)
