"""Production module manifest: models, policies, the ``WO`` sequence, the API, the source readers, the inventory demand
provider and pair resolver (work-order materials), the ``production.material_retry`` subscriptions (blocked work
orders retry when stock arrives), the completion checks and the fixture seed. Permissions and events come from the
frozen catalogues (registered centrally)."""

from __future__ import annotations

from typing import Any

from app.modules.production.events import MATERIAL_RETRY, MATERIAL_RETRY_TRIGGERS, WO_SEQUENCE
from app.modules.production.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.production.router import router

    return router


def _retry(uow: Any, event: Any) -> None:
    from app.modules.production.work_orders import handle_material_retry

    handle_material_retry(uow, event)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.production import seed_production

    seed_production(ctx)


def _on_load() -> None:
    from app.modules.inventory import service as inventory
    from app.modules.production import work_orders
    from app.modules.production.readers import READERS
    from app.modules.production.rules import register_checks
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    inventory.register_demand_provider("production.wo_material", work_orders.open_demand)
    inventory.register_pair_resolver("production.work_order.", work_orders.pairs_for_event)
    register_checks()


MANIFEST = ModuleManifest(
    name="production",
    models=("app.modules.production.models",),
    policies=list(POLICIES),
    sequences=[WO_SEQUENCE],
    routers=[_router],
    subscriptions=[
        Subscription(event=name, handler_key=f"{MATERIAL_RETRY}:{name}", handler=_retry) for name in MATERIAL_RETRY_TRIGGERS
    ],
    # after the inventory world (60): work centres, the approved walnut panel BOM and routing, WO-2026-0001 (blocked)
    seeds=[SeedDef(name="production.world", order=65, run=_seed, slice_no=4)],
    on_load=_on_load,
)
