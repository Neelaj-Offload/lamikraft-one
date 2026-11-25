"""Orders module manifest: models, policies, the ``SO`` sequence, the API, the source reader, the shortage demand
provider and the order-event pair resolver (permissions and events come from the frozen catalogues)."""

from __future__ import annotations

from typing import Any

from app.modules.orders.events import ORDER_SEQUENCE
from app.modules.orders.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest

PROMOTE_ON_ORDER = "orders.promote_on_order"


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


def _on_order_confirmed(uow: Any, event: Any) -> None:
    """A lead with a confirmed sales order becomes a customer (spec 2026-11-25-customers-samples-design.md)."""
    import uuid

    from app.modules.orders.models import SalesOrder
    from app.modules.parties.leads import promote_to_customer

    order_id = (event.payload or {}).get("order_id") or event.aggregate_id
    order = uow.session.get(SalesOrder, uuid.UUID(str(order_id))) if order_id else None
    if order is not None:
        promote_to_customer(uow, order.party_id, reason="order_confirmed")


MANIFEST = ModuleManifest(
    name="orders",
    models=("app.modules.orders.models",),
    policies=list(POLICIES),
    sequences=[ORDER_SEQUENCE],
    routers=[_router],
    subscriptions=[Subscription(event="orders.sales_order.confirmed", handler_key=PROMOTE_ON_ORDER, handler=_on_order_confirmed)],
    on_load=_on_load,
)
