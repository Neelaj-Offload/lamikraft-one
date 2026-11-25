"""Sales module manifest: models, policies, sequences, API, tools, the document-render job, source readers, the
``sales.quote.review`` approval handler and the fixture seed.

Permissions and events come from the frozen catalogues (registered centrally by the ``authz``/``events``
manifests); this module only names them.
"""

from __future__ import annotations

from typing import Any

from app.modules.sales.events import (
    CUSTOM_PRODUCT_SEQUENCE,
    ENQUIRY_SEQUENCE,
    QUOTE_ISSUED,
    QUOTE_SEQUENCE,
    SAMPLE_SEQUENCE,
)
from app.modules.sales.policies import POLICIES
from app.modules.sales.tools import TOOLS
from app.platform.events.defs import Subscription
from app.platform.jobs.defs import JobDef
from app.platform.manifest import ModuleManifest
from app.seed.context import SeedContext, SeedDef

DOCUMENT_RENDER_JOB = "sales.document_render"
CUSTOM_AUTOADVANCE = "sales.custom_product_autoadvance"
SAMPLE_DISPATCH = "sales.sample_dispatch"
PROMOTE_ON_SAMPLE = "sales.promote_on_sample"
PROMOTE_ON_QUOTE_WON = "sales.promote_on_quote_won"
SAMPLE_DISPATCHED = "sales.sample.dispatched"
QUOTE_WON = "sales.quote.won"
CHALLAN_ISSUED = "challans.challan.issued"


def _router() -> Any:
    from app.modules.sales.router import router

    return router


def _seed(ctx: SeedContext) -> None:
    from app.seed.world.sales import seed_sales_history

    seed_sales_history(ctx)


def _seed_messages(ctx: SeedContext) -> None:
    from app.seed.world.sales import seed_sales_messages

    seed_sales_messages(ctx)


def _seed_d0(ctx: SeedContext) -> None:
    from app.seed.world.sales import seed_sales_d0

    seed_sales_d0(ctx)


def _render_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.sales.documents import render_job

    return render_job(ctx, payload)


def _on_issued(uow: Any, event: Any) -> None:
    from app.modules.sales.documents import enqueue_render

    enqueue_render(uow, event)


def _on_issued_custom(uow: Any, event: Any) -> None:
    import uuid

    from app.modules.sales.custom_products import advance_on_issue

    advance_on_issue(uow, uuid.UUID(str(event.payload["quote_id"])))


def _on_challan_issued(uow: Any, event: Any) -> None:
    import uuid

    from app.modules.sales.sample_lineage import dispatch_linked_samples
    from app.modules.sales.samples import dispatch_by_challan

    payload = event.payload or {}
    challan_id = uuid.UUID(str(payload["challan_id"]))
    sample_id = payload.get("sample_id")
    if sample_id:
        dispatch_by_challan(uow, uuid.UUID(str(sample_id)), challan_id)
    # the issued event carries sample_id = null (a challan has no sample column): samples linked to it are dispatched
    dispatch_linked_samples(uow, challan_id)


def _promote(uow: Any, model: Any, record_id: Any, reason: str) -> None:
    """A lead that was sent a sample or won a quotation becomes a customer (spec 2026-11-25-customers-samples)."""
    import uuid

    from app.modules.parties.leads import promote_to_customer

    row = uow.session.get(model, uuid.UUID(str(record_id))) if record_id else None
    if row is not None:
        promote_to_customer(uow, row.party_id, reason=reason)


def _on_sample_dispatched(uow: Any, event: Any) -> None:
    from app.modules.sales.models import Sample

    _promote(uow, Sample, (event.payload or {}).get("sample_id") or event.aggregate_id, "sample_sent")


def _on_quote_won(uow: Any, event: Any) -> None:
    from app.modules.sales.models import Quote

    _promote(uow, Quote, (event.payload or {}).get("quote_id") or event.aggregate_id, "quote_won")


def _proforma_sequence() -> Any:
    from app.modules.sales.proforma import PROFORMA_SEQUENCE

    return PROFORMA_SEQUENCE


def _search_providers() -> list[Any]:
    from app.modules.sales.search import SEARCH_PROVIDERS

    return list(SEARCH_PROVIDERS)


def _on_load() -> None:
    from app.modules.approvals.service import register_handler
    from app.modules.sales.approvals import QUOTE_REVIEW_HANDLER
    from app.modules.sales.custom_products import PROMOTION_HANDLER
    from app.modules.sales.readers import READERS
    from app.platform.sources import register_reader

    register_handler(QUOTE_REVIEW_HANDLER)
    register_handler(PROMOTION_HANDLER)
    for source_type, reader in READERS.items():
        register_reader(source_type, reader)


MANIFEST = ModuleManifest(
    name="sales",
    models=("app.modules.sales.models", "app.modules.sales.proforma_models"),
    policies=list(POLICIES),
    sequences=[QUOTE_SEQUENCE, ENQUIRY_SEQUENCE, CUSTOM_PRODUCT_SEQUENCE, SAMPLE_SEQUENCE, _proforma_sequence()],
    routers=[_router],
    tools=list(TOOLS),
    jobs=[JobDef(kind=DOCUMENT_RENDER_JOB, handler=_render_job, queue="documents", max_attempts=5)],
    subscriptions=[
        Subscription(event=QUOTE_ISSUED, handler_key=DOCUMENT_RENDER_JOB, handler=_on_issued, queue="documents"),
        Subscription(event=QUOTE_ISSUED, handler_key=CUSTOM_AUTOADVANCE, handler=_on_issued_custom),
        Subscription(event=CHALLAN_ISSUED, handler_key=SAMPLE_DISPATCH, handler=_on_challan_issued),
        Subscription(event=SAMPLE_DISPATCHED, handler_key=PROMOTE_ON_SAMPLE, handler=_on_sample_dispatched),
        Subscription(event=QUOTE_WON, handler_key=PROMOTE_ON_QUOTE_WON, handler=_on_quote_won),
    ],
    search_providers=_search_providers(),
    # three seeds so the fixture clock only moves forward (fixtures.md §1 rule 2): history to D-3 after pricing,
    # the D-1 evening messages after the parties change (55), the D0 morning after Arjun's activation (75)
    seeds=[
        SeedDef(name="sales.world", order=50, run=_seed, slice_no=1),
        SeedDef(name="sales.world.messages", order=56, run=_seed_messages, slice_no=1),
        SeedDef(name="sales.world.d0", order=76, run=_seed_d0, slice_no=1),
    ],
    on_load=_on_load,
)
