"""Finance module manifest: models, policies, the invoice / credit-note / draft / receipt / export sequences
(financial year from April), the ``finance_policy`` and ``finance_account_mapping`` settings, the API, the
``finance.invoice_suggestion`` and ``finance.margin_check`` consumers, the overdue and unallocated sweeps, the source
readers, the briefing completion checks and the fixture seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events`` manifests).
"""

from __future__ import annotations

from typing import Any

from app.modules.finance.events import (
    MARGIN_HANDLER,
    MARGIN_TRIGGERS,
    SEQUENCES,
    SETTINGS,
    SUGGESTION_HANDLER,
    SUGGESTION_TRIGGERS,
)
from app.modules.finance.jobs import JOBS, SCHEDULES
from app.modules.finance.policies import POLICIES
from app.platform.events.defs import Subscription
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef


def _router() -> Any:
    from app.modules.finance.router import router

    return router


def _suggest(uow: Any, event: Any) -> None:
    from app.modules.finance.suggestions import on_challan_issued

    on_challan_issued(uow, event)


def _margin(uow: Any, event: Any) -> None:
    from app.modules.finance.margin import check_quote

    check_quote(uow, event)


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.finance import seed_finance

    seed_finance(ctx)


def _on_load() -> None:
    from app.modules.finance.rules import register_checks

    from app.modules.finance.readers import READERS
    from app.platform.sources import register_reader

    for source_type, reader in READERS.items():
        register_reader(source_type, reader)
    register_checks()


MANIFEST = ModuleManifest(
    name="finance",
    models=("app.modules.finance.models",),
    policies=list(POLICIES),
    sequences=list(SEQUENCES),
    settings=list(SETTINGS),
    routers=[_router],
    subscriptions=[
        *(Subscription(event=name, handler_key=SUGGESTION_HANDLER, handler=_suggest) for name in SUGGESTION_TRIGGERS),
        *(Subscription(event=name, handler_key=MARGIN_HANDLER, handler=_margin) for name in MARGIN_TRIGGERS),
    ],
    jobs=list(JOBS),
    schedules=list(SCHEDULES),
    # after the inventory world (60): tax profile draft, invoices from the issued challans, a receipt and allocation
    seeds=[SeedDef(name="finance.world", order=70, run=_seed, slice_no=5)],
    on_load=_on_load,
)
