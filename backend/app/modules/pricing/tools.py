"""Agent tools for pricing: the same resolution service the UI and quotes use (prices are never model inputs)."""

from __future__ import annotations

from pydantic import BaseModel

from app.modules.pricing import service
from app.modules.pricing.schemas import PriceResolution, ResolvePriceInput
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork


def _resolve_price(uow: UnitOfWork, data: BaseModel) -> PriceResolution:
    assert isinstance(data, ResolvePriceInput)
    return service.resolve_price(
        uow,
        currency=data.currency,
        uom=data.uom,
        product_id=data.product_id,
        product_key=data.product_key,
        party_id=data.party_id,
        on_date=data.on_date,
        price_type=data.price_type,
    )


RESOLVE_PRICE = ToolDef(
    name="resolve_price",
    group="Sales",
    description=(
        "Look up the selling price of a product for a party, currency and unit on a date: customer agreement, then "
        "customer-type list, then standard list. Returns found (with list code and item id), ambiguous (ask the "
        "user), unavailable or not_found. Never converts or relabels currencies."
    ),
    input_model=ResolvePriceInput,
    output_model=PriceResolution,
    handler=_resolve_price,
    effect="read",
    permission="pricing.price.read",
)

TOOLS = [RESOLVE_PRICE]
