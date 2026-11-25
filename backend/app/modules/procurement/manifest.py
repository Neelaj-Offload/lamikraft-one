"""Procurement module manifest: models, policies, the ``PR``/``PO``/``GRN`` sequences, the ``procurement_policy``
setting, the API, the overdue sweep, the source readers, the ``ops.receipts`` completion checks, the quality callback
for inspected receipt lines and the inventory hooks (late supply in ``caused_by``; procurement events refresh the
shortage state). Permissions and events come from the frozen catalogues."""

from __future__ import annotations

from typing import Any

from app.modules.procurement.events import PROCUREMENT_POLICY, SEQUENCES, SHORTAGE_EVENTS
from app.modules.procurement.jobs import JOBS, SCHEDULES
from app.modules.procurement.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.procurement.router import router

    return router


def _refresh(uow: Any, event: Any) -> None:
    """``inventory.shortage_refresh`` for procurement events (supply changed): handled by the inventory module."""
    from app.modules.inventory.shortages import handle_refresh

    handle_refresh(uow, event)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.procurement import seed_procurement

    seed_procurement(ctx)


def _on_load() -> None:
    from app.modules.inventory import service as inventory
    from app.modules.procurement import receiving, service
    from app.modules.procurement.readers import READERS
    from app.modules.procurement.rules import register_checks
    from app.modules.production import service as production
    from app.modules.quality import service as quality
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    register_checks()
    inventory.register_cause_provider("procurement.late_supply", service.late_supply_causes)
    inventory.register_pair_resolver("procurement.", service.pairs_for_event)
    from app.modules.inventory.categories import register_on_order_provider
    from app.modules.procurement.factory import on_order

    register_on_order_provider(on_order)  # factory work in progress on the stock-by-category view (module 4)
    production.register_supply_provider(service.PO_LINE, service.po_line_supply)
    quality.register_subject_handler(receiving.SUBJECT, receiving.on_inspection_decided)


MANIFEST = ModuleManifest(
    name="procurement",
    models=("app.modules.procurement.models",),
    policies=list(POLICIES),
    sequences=list(SEQUENCES),
    settings=[PROCUREMENT_POLICY],
    routers=[_router],
    subscriptions=[
        Subscription(event=name, handler_key=f"inventory.shortage_refresh:{name}", handler=_refresh)
        for name in SHORTAGE_EVENTS
    ],
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    # after the inventory world (60): Kaveri's vendor item and PO-2026-0001 (late line 1, LK-WB-1800)
    seeds=[SeedDef(name="procurement.world", order=62, run=_seed, slice_no=4)],
    on_load=_on_load,
)
