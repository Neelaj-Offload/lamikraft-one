"""The quote configurator (LM-43, API-34, UI-60, LP-06.1): search-first product finder for a quote.

Catalogue filters (text incl. numeric thickness, category, subcategory, family, size, thickness, decor, finish) apply
in SQL before paging; facets are narrowed over the whole filtered set; ``exact_match`` names the product when exactly
one matches. Each row of the page carries the price the quote would get (customer agreement -> customer type ->
standard, then currency/unit/date, with an approved FX conversion when no list exists in the currency) and the
engine's order-value recommendation for that price (never labelled MOQ; the product MOQ is separate).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.errors import AppError, NotConfigured
from app.core.money import CurrencyCode, Money, Quantity
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import (
    OrderValueRecommendationRead,
    ProductFacets,
    ProductFilters,
    ProductStatus,
    ProductSummary,
)
from app.modules.commercial import engine
from app.modules.commercial import service as commercial
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import PriceType
from app.modules.sales.common import business_date, party_ref
from app.platform.service import query
from app.platform.uow import UnitOfWork

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class ConfiguratorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_id: uuid.UUID | None = None
    currency: CurrencyCode = "EUR"
    price_type: PriceType = PriceType.EXPORT
    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    family: Text | None = None
    size: Text | None = None
    thickness: Text | None = None
    decor: Text | None = None
    finish: Text | None = None
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class ConfiguratorPrice(BaseModel):
    status: str
    unit_price: Money | None
    unit_code: str | None
    price_list_code: str | None
    tier: str | None
    reason_code: str | None
    explanation: str
    product_moq: Quantity | None
    converted_with_fx: bool


class ConfiguratorRow(BaseModel):
    product: ProductSummary
    price: ConfiguratorPrice | None
    recommendation: OrderValueRecommendationRead | None


class ConfiguratorResult(BaseModel):
    items: list[ConfiguratorRow]
    total: int
    limit: int
    offset: int
    facets: ProductFacets
    exact_match: uuid.UUID | None
    currency: str


def _recommendation(rules: engine.RuleSet | None, currency: str, unit_price: Money | None, carton: int | None, uom: str) -> OrderValueRecommendationRead:
    if rules is None:
        rec = engine.Recommendation("NOT_EVALUATED", None, uom, None, None, None, "No active rule set; no recommendation is calculated.")
    else:
        rec = engine.order_value_recommendation(
            rules, currency=currency, unit_price=unit_price.amount if unit_price is not None else None, carton_qty=carton, uom=uom
        )
    return OrderValueRecommendationRead(
        status=rec.status,
        quantity=Quantity(value=rec.quantity, uom=rec.uom) if rec.quantity is not None else None,
        minimum_order_value=Money(amount=rec.minimum_order_value, currency=currency) if rec.minimum_order_value is not None else None,  # type: ignore[arg-type]
        carton_qty=rec.carton_qty,
        explanation=rec.explanation,
        label=rec.label,
    )


@query("sales.quote.read")
def configurator_resolve(uow: UnitOfWork, data: ConfiguratorRequest) -> ConfiguratorResult:
    """Filtered, paged, priced product search for a quote line (``catalogue.product.read`` + ``pricing.price.read``)."""
    uow.actor.require("catalogue.product.read")
    party = party_ref(uow, data.party_id) if data.party_id is not None else None
    filters = ProductFilters(
        q=data.q, category_id=data.category_id, subcategory_id=data.subcategory_id, family=data.family, size=data.size,
        thickness=data.thickness, decor=data.decor, finish=data.finish, status=[ProductStatus.ACTIVE],
    )
    page = catalogue.list_products(
        uow, filters, sort="relevance" if (data.q or "").strip() else "product_key", limit=data.limit, offset=data.offset,
        price_currency=data.currency, price_type=data.price_type.value,
    )
    facets = catalogue.product_facets(uow, filters)
    can_price = uow.actor.can("pricing.price.read")
    try:
        rules: engine.RuleSet | None = commercial.active_rules(uow)
    except NotConfigured:
        rules = None
    day = business_date(uow)
    rows: list[ConfiguratorRow] = []
    for product in page.items:
        uom = product.unit_of_sale or "pcs"
        price: ConfiguratorPrice | None = None
        recommendation: OrderValueRecommendationRead | None = None
        if can_price:
            try:
                resolution = pricing.resolve_price(
                    uow, currency=data.currency, uom=uom, product_id=product.id, party_id=party.id if party else None,
                    on_date=day, price_type=data.price_type, allow_fx=True,
                )
            except AppError:
                resolution = None
            if resolution is not None:
                price = ConfiguratorPrice(
                    status=resolution.status, unit_price=resolution.unit_price, unit_code=resolution.unit_code,
                    price_list_code=resolution.price_list_code, tier=resolution.tier, reason_code=resolution.reason_code,
                    explanation=resolution.explanation, product_moq=resolution.product_moq,
                    converted_with_fx=resolution.fx is not None,
                )
                recommendation = _recommendation(rules, data.currency, resolution.unit_price, product.carton_qty, uom)
        rows.append(ConfiguratorRow(product=product, price=price, recommendation=recommendation))
    return ConfiguratorResult(
        items=rows, total=page.total, limit=page.limit, offset=page.offset, facets=facets,
        exact_match=page.items[0].id if page.total == 1 and page.items else None, currency=data.currency,
    )
