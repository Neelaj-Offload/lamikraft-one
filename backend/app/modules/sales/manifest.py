"""Sales module manifest: models, policies, sequences, API, tools, the document-render job, source readers, the
``sales.quote.review`` approval handler and the fixture seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events``
manifests); this module only names them.
"""

from __future__ import annotations

from typing import Any

from app.modules.sales.events import ENQUIRY_SEQUENCE, QUOTE_ISSUED, QUOTE_SEQUENCE
from app.modules.sales.policies import POLICIES
from app.modules.sales.tools import TOOLS
from app.platform.events.defs import Subscription
from app.platform.jobs.defs import JobDef
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef

DOCUMENT_RENDER_JOB = "sales.document_render"


def _router() -> Any:
    from app.modules.sales.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.sales import seed_sales

    seed_sales(ctx)


def _render_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.sales.documents import render_job

    return render_job(ctx, payload)


def _on_issued(uow: Any, event: Any) -> None:
    from app.modules.sales.documents import enqueue_render

    enqueue_render(uow, event)


def _on_load() -> None:
    from app.modules.approvals.service import register_handler
    from app.modules.sales.approvals import QUOTE_REVIEW_HANDLER
    from app.modules.sales.readers import READERS
    from app.platform.sources import register_reader

    register_handler(QUOTE_REVIEW_HANDLER)
    for source_type, reader in READERS.items():
        register_reader(source_type, reader)


MANIFEST = ModuleManifest(
    name="sales",
    models=("app.modules.sales.models",),
    policies=list(POLICIES),
    sequences=[QUOTE_SEQUENCE, ENQUIRY_SEQUENCE],
    routers=[_router],
    tools=list(TOOLS),
    jobs=[JobDef(kind=DOCUMENT_RENDER_JOB, handler=_render_job, queue="documents", max_attempts=5)],
    subscriptions=[
        Subscription(event=QUOTE_ISSUED, handler_key=DOCUMENT_RENDER_JOB, handler=_on_issued, queue="documents")
    ],
    seeds=[SeedDef(name="sales.world", order=50, run=_seed, slice_no=1)],
    on_load=_on_load,
)
