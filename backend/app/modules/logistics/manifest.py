"""Logistics module manifest: models, policies, the ``PK``/``SH`` sequences, the API, the source readers, the
``ops.dispatch_cutoffs`` completion checks and the two consumers (``logistics.shipment_status`` on challan issue,
``logistics.packing_list_staleness`` on packaging and order changes). Permissions and events come from the frozen
catalogues."""

from __future__ import annotations

from typing import Any

from app.modules.logistics.events import SEQUENCES, SHIPMENT_STATUS, STALENESS, STALENESS_TRIGGERS
from app.modules.logistics.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.logistics.router import router

    return router


def _shipment_status(uow: Any, event: Any) -> None:
    from app.modules.logistics.shipments import handle_challan_issued

    handle_challan_issued(uow, event)


def _staleness(uow: Any, event: Any) -> None:
    from app.modules.logistics.packing_lists import handle_staleness

    handle_staleness(uow, event)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.logistics import seed_logistics

    seed_logistics(ctx)


def _on_load() -> None:
    from app.modules.logistics.readers import READERS
    from app.modules.logistics.rules import register_checks
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    register_checks()


MANIFEST = ModuleManifest(
    name="logistics",
    models=("app.modules.logistics.models",),
    policies=list(POLICIES),
    sequences=list(SEQUENCES),
    routers=[_router],
    subscriptions=[
        Subscription(event="challans.challan.issued", handler_key=SHIPMENT_STATUS, handler=_shipment_status),
        *(
            Subscription(event=name, handler_key=f"{STALENESS}:{name}", handler=_staleness)
            for name in STALENESS_TRIGGERS
        ),
    ],
    # after procurement (62): the 20 ft container profile and a planned shipment with a cutoff
    seeds=[SeedDef(name="logistics.world", order=64, run=_seed, slice_no=4)],
    on_load=_on_load,
)
