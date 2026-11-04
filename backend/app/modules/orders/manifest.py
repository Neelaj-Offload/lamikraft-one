"""Orders module manifest: models, policies, the ``SO`` sequence, the API, the source reader, the shortage demand
provider and the order-event pair resolver (permissions and events come from the frozen catalogues)."""

from __future__ import annotations

from typing import Any

from app.modules.orders.events import ORDER_SEQUENCE
from app.modules.orders.policies import POLICIES
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.orders.router import router

    return router


def _on_load() -> None:
    from app.modules.inventory import service as inventory
    from app.modules.orders import service
    from app.modules.orders.readers import READERS
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    inventory.register_demand_provider("orders.sales_order_line", service.open_demand)
    inventory.register_pair_resolver("orders.", service.pairs_for_order_event)


MANIFEST = ModuleManifest(
    name="orders",
    models=("app.modules.orders.models",),
    policies=list(POLICIES),
    sequences=[ORDER_SEQUENCE],
    routers=[_router],
    on_load=_on_load,
)
