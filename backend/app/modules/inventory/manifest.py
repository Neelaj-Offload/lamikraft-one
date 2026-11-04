"""Inventory module manifest: models, the warehouse policy, document sequences, the ``inventory_policy`` setting,
the API, the ``inventory.shortage_refresh`` subscriptions, the nightly projection check and the fixture seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events`` manifests).
"""

from __future__ import annotations

from typing import Any

from app.modules.inventory.events import INVENTORY_POLICY, SEQUENCES, SHORTAGE_REFRESH, SHORTAGE_TRIGGERS
from app.modules.inventory.integrity import JOBS, SCHEDULES
from app.modules.inventory.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.inventory.router import router

    return router


def _test_support_router() -> Any:
    """Mounted only in the test environment (an empty router elsewhere, so the path is 404)."""
    from fastapi import APIRouter

    from app.core.config import get_settings

    if not get_settings().is_test:
        return APIRouter()
    from app.modules.inventory.testsupport import router

    return router


def _refresh(uow: Any, event: Any) -> None:
    from app.modules.inventory.shortages import handle_refresh

    handle_refresh(uow, event)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.inventory import seed_inventory

    seed_inventory(ctx)


def _on_load() -> None:
    from app.modules.inventory.readers import READERS
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    from app.modules.inventory.rules import register_checks

    register_checks()


MANIFEST = ModuleManifest(
    name="inventory",
    models=("app.modules.inventory.models",),
    policies=list(POLICIES),
    sequences=list(SEQUENCES),
    settings=[INVENTORY_POLICY],
    routers=[_router, _test_support_router],
    subscriptions=[
        Subscription(event=name, handler_key=f"{SHORTAGE_REFRESH}:{name}", handler=_refresh)
        for name in SHORTAGE_TRIGGERS
    ],
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    # after the challan world (52) and the D-1 party changes (55): WH-MAIN, bin A-12, the approved opening batch
    seeds=[SeedDef(name="inventory.world", order=60, run=_seed, slice_no=4)],
    on_load=_on_load,
)
