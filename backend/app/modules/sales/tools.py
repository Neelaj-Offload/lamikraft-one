"""Agent tools of the sales module (thin descriptors over the same services the UI uses).

``resolve_party`` (parties), ``resolve_product`` (catalogue), ``resolve_price`` (pricing) and ``calculate_quote``
(commercial) already exist and are reused, not duplicated. Inputs never carry identity: the actor comes from the
server-built context, prices come from price lists, and a draft is all a tool can create.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.sales import quotes
from app.modules.sales.common import idempotent
from app.modules.sales.schemas import (
    DraftQuoteInput,
    FindUsualOrderInput,
    QuoteCreate,
    QuoteDetail,
    QuoteLineCreate,
    UsualOrderOutput,
)
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def _find_usual_order(uow: UnitOfWork, data: BaseModel) -> UsualOrderOutput:
    assert isinstance(data, FindUsualOrderInput)
    return quotes.find_repeat_quote_basis(uow, data.party_id)


def draft_quote(
    uow: UnitOfWork, data: DraftQuoteInput, *, origin: str | None = None, origin_ref: str | None = None
) -> QuoteDetail:
    """Create a draft owned by the actor from catalog lines priced through ``resolve_price`` (no overrides)."""
    quote = quotes.create_quote(
        uow,
        QuoteCreate(
            party_id=data.party_id,
            enquiry_id=data.enquiry_id,
            origin_message_id=data.origin_message_id,
            currency=data.currency,
            price_type=data.price_type,
            customer_reference=data.customer_reference,
            remarks=data.remarks,
            apply_minimum_surcharge=data.apply_minimum_surcharge,
        ),
        origin=origin,
        origin_ref=origin_ref,
    )
    for line in data.lines:
        quotes.add_line(
            uow,
            quote.id,
            QuoteLineCreate(
                expected_version=quote.version,
                line_type="catalog",
                product_id=line.product_id,
                product_key=line.product_key,
                quantity=line.quantity,
                unit_code=line.unit_code,
            ),
            origin=origin,
        )
    return quotes.detail(uow, quote)


def _draft_quote(uow: UnitOfWork, data: BaseModel) -> QuoteDetail:
    """The tool runtime passes a per-step ``Idempotency-Key``: a retried step replays the first draft instead of
    creating a second one (``requires_idempotency=True``)."""
    assert isinstance(data, DraftQuoteInput)
    detail, _replayed = idempotent(uow, "sales.draft_quote", data, lambda: draft_quote(uow, data), QuoteDetail, status=201)
    return detail


FIND_USUAL_ORDER = ToolDef(
    name="find_usual_order",
    group="Sales",
    description=(
        "The most recent won quotation of a party the user may see, with its lines (product, quantity, unit, price) "
        "as the basis for a repeat quote. Returns status none when the party has no won quotation."
    ),
    input_model=FindUsualOrderInput,
    output_model=UsualOrderOutput,
    handler=_find_usual_order,
    effect="read",
    permission="sales.quote.read",
)

DRAFT_QUOTE = ToolDef(
    name="draft_quote",
    group="Sales",
    description=(
        "Create a draft quotation for a party from catalog lines. Each line is priced from the price lists "
        "(resolve_price); totals, the EUR minimum check and the surcharge are computed and persisted by the "
        "commercial engine. The draft is owned by the user, is not sent, and shows in their quote list for review."
    ),
    input_model=DraftQuoteInput,
    output_model=QuoteDetail,
    handler=_draft_quote,
    effect="draft",
    permission="sales.quote.create",
    requires_idempotency=True,
)

TOOLS = [FIND_USUAL_ORDER, DRAFT_QUOTE]
