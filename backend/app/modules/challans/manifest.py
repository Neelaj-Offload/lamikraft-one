"""Challans module manifest: models, policies, the ``DC`` sequence, the ``challan_defaults`` setting, the API, the
``draft_challan`` tool, the returnables sweep job and schedule, the source reader and the fixture seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events``
manifests); this module only names them.
"""

from __future__ import annotations

from typing import Any

from app.modules.challans.events import CHALLAN_DEFAULTS, CHALLAN_SEQUENCE
from app.modules.challans.jobs import JOBS, SCHEDULES
from app.modules.challans.policies import POLICIES
from app.modules.challans.tools import TOOLS
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.challans.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.challans import seed_challans

    seed_challans(ctx)


def _on_load() -> None:
    from app.modules.challans.readers import READERS
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)


MANIFEST = ModuleManifest(
    name="challans",
    models=("app.modules.challans.models",),
    policies=list(POLICIES),
    sequences=[CHALLAN_SEQUENCE],
    settings=[CHALLAN_DEFAULTS],
    routers=[_router],
    tools=list(TOOLS),
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    # after the sales history (50) and before the D-1 party change (55): DC-2026-0001 issued D-7, 0002 D-3
    seeds=[SeedDef(name="challans.world", order=52, run=_seed, slice_no=2)],
    on_load=_on_load,
)
