"""Pricing read API (``/api/v1/pricing``): price lists and items, product prices, price resolution, costs."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import CurrencyCode
from app.modules.catalogue.schemas import UomCode
from app.modules.pricing import service
from app.modules.pricing.schemas import (
    PriceListDetail,
    PriceListItemRead,
    PriceListStatus,
    PriceListSummary,
    PriceResolution,
    PriceScope,
    PriceType,
    ProductCostRead,
    ProductPrices,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])
READ = requires("pricing.price.read")


@router.get("/price-lists", openapi_extra=READ)
def list_price_lists(
    actor: Actor,
    status: Annotated[list[PriceListStatus] | None, Query()] = None,
    scope_kind: PriceScope | None = None,
    price_type: PriceType | None = None,
    currency: CurrencyCode | None = None,
    party_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    on_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PriceListSummary]:
    """Price lists the actor may see (customer agreements only for parties within the actor's scope)."""
    return service.list_price_lists(
        actor, status=status, scope_kind=scope_kind, price_type=price_type, currency=currency, party_id=party_id,
        q=q, on_date=on_date, limit=limit, offset=offset,
    )


@router.get("/price-lists/{price_list_id}", openapi_extra=READ)
def get_price_list(actor: Actor, price_list_id: uuid.UUID) -> PriceListDetail:
    return service.get_price_list(actor, price_list_id)


@router.get("/price-lists/{price_list_id}/items", openapi_extra=READ)
def list_price_list_items(
    actor: Actor,
    price_list_id: uuid.UUID,
    product_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    on_date: date | None = None,
    include_history: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PriceListItemRead]:
    """Items of one list; the base/add-on breakdown and provenance need ``pricing.price_list.read``."""
    return service.list_price_list_items(
        actor, price_list_id, product_id=product_id, q=q, on_date=on_date, include_history=include_history,
        limit=limit, offset=offset,
    )


@router.get("/products/{product_id}/prices", openapi_extra=READ)
def list_product_prices(actor: Actor, product_id: uuid.UUID, on_date: date | None = None) -> ProductPrices:
    return service.product_prices(actor, product_id, on_date=on_date)


@router.get("/products/{product_id}/costs", openapi_extra=requires("pricing.cost.read"))
def list_product_costs(actor: Actor, product_id: uuid.UUID) -> list[ProductCostRead]:
    """Protected cost history (``pricing.cost.read``)."""
    return service.list_product_costs(actor, product_id)


@router.get("/resolve", openapi_extra=READ)
def resolve_price(
    actor: Actor,
    currency: CurrencyCode,
    uom: UomCode,
    product_id: uuid.UUID | None = None,
    product_key: Annotated[str | None, Query(max_length=120)] = None,
    party_id: uuid.UUID | None = None,
    on_date: date | None = None,
    price_type: PriceType | None = None,
) -> PriceResolution:
    """Customer agreement -> customer-type list -> standard list, then currency, unit and effective date."""
    return service.resolve_price(
        actor, currency=currency, uom=uom, product_id=product_id, product_key=product_key, party_id=party_id,
        on_date=on_date, price_type=price_type,
    )
