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
    FxDecision,
    FxPolicyRead,
    FxPolicyUpdate,
    FxRateCreate,
    FxRateRead,
    FxRateStatus,
    PriceHistoryRead,
    PriceListCommand,
    PriceListCreate,
    PriceListDetail,
    PriceListDuplicate,
    PriceListItemCreate,
    PriceListItemRead,
    PriceListItemUpdate,
    PriceListStatus,
    PriceListSummary,
    PriceListUpdate,
    PriceResolution,
    PriceScope,
    PriceType,
    ProductCostCreate,
    ProductCostRead,
    ProductPrices,
    RetireItem,
    SupersedeItemCommand,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/pricing", tags=["pricing"])
READ = requires("pricing.price.read")
MANAGE = requires("pricing.price_list.manage")
FX_READ = requires("pricing.fx_rate.read")


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
def list_product_costs(
    actor: Actor,
    product_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProductCostRead]:
    """Protected cost history (``pricing.cost.read``), newest first; every read returning rows is audited."""
    return service.list_product_costs(actor, product_id, limit=limit, offset=offset)


@router.get("/prices/resolve", openapi_extra=READ)
def resolve_price(
    actor: Actor,
    currency: CurrencyCode,
    uom: UomCode,
    product_id: uuid.UUID | None = None,
    product_key: Annotated[str | None, Query(max_length=120)] = None,
    party_id: uuid.UUID | None = None,
    on_date: date | None = None,
    price_type: PriceType | None = None,
    allow_fx: bool = False,
) -> PriceResolution:
    """Customer agreement -> customer-type list -> standard list, then currency, unit and effective date. With
    ``allow_fx`` a missing price in the currency is converted from the FX policy's source currency at an approved,
    dated rate (provenance in ``fx``); otherwise prices are only ever in their list currency."""
    return service.resolve_price(
        actor, currency=currency, uom=uom, product_id=product_id, product_key=product_key, party_id=party_id,
        on_date=on_date, price_type=price_type, allow_fx=allow_fx,
    )


# =====================================================================================================
# Slice 2: price-list maintenance
# =====================================================================================================
@router.post("/price-lists", status_code=201, openapi_extra=MANAGE)
def create_price_list(actor: Actor, body: PriceListCreate) -> PriceListDetail:
    """A new draft list (standard, customer-type or customer agreement); items are added before activation."""
    with UnitOfWork(actor) as uow:
        pl = service.create_price_list(uow, body)
        return service.get_price_list(uow, pl.id)


@router.patch("/price-lists/{price_list_id}", openapi_extra=MANAGE)
def update_price_list(actor: Actor, price_list_id: uuid.UUID, body: PriceListUpdate) -> PriceListDetail:
    """Draft lists: every field; active lists: name, notes and a shorter ``valid_to``; 409 when stale."""
    with UnitOfWork(actor) as uow:
        service.update_price_list(uow, price_list_id, body)
        return service.get_price_list(uow, price_list_id)


@router.post("/price-lists/{price_list_id}/activate", openapi_extra=MANAGE)
def activate_price_list(actor: Actor, price_list_id: uuid.UUID, body: PriceListCommand) -> PriceListDetail:
    """Draft -> active; 409 ``price_list_overlap`` with a conflict report when another active list overlaps."""
    with UnitOfWork(actor) as uow:
        service.activate_price_list_command(uow, price_list_id, body)
        return service.get_price_list(uow, price_list_id)


@router.post("/price-lists/{price_list_id}/retire", openapi_extra=MANAGE)
def retire_price_list(actor: Actor, price_list_id: uuid.UUID, body: PriceListCommand) -> PriceListDetail:
    """Retire a list (reason required); its prices stop resolving and stay as history."""
    with UnitOfWork(actor) as uow:
        service.retire_price_list(uow, price_list_id, body)
        return service.get_price_list(uow, price_list_id)


@router.post("/price-lists/{price_list_id}/duplicate", status_code=201, openapi_extra=MANAGE)
def duplicate_price_list(actor: Actor, price_list_id: uuid.UUID, body: PriceListDuplicate) -> PriceListDetail:
    """A new draft list with a copy of the source's current prices (e.g. next year's list)."""
    with UnitOfWork(actor) as uow:
        pl = service.duplicate_price_list(uow, price_list_id, body)
        return service.get_price_list(uow, pl.id)


@router.post("/price-lists/{price_list_id}/items", status_code=201, openapi_extra=MANAGE)
def create_price_list_item(actor: Actor, price_list_id: uuid.UUID, body: PriceListItemCreate) -> PriceListItemRead:
    """Add a price to a draft list (409 ``price_item_overlap`` when the product already has one for the period)."""
    with UnitOfWork(actor) as uow:
        item = service.add_item(uow, price_list_id, body)
        return service.get_item(uow, item.id)


@router.patch("/price-list-items/{item_id}", openapi_extra=MANAGE)
def update_price_list_item(actor: Actor, item_id: uuid.UUID, body: PriceListItemUpdate) -> PriceListItemRead:
    """Edit a price of a draft list (an active list's prices change only by an effective-dated supersede)."""
    with UnitOfWork(actor) as uow:
        return service.update_item(uow, item_id, body)


@router.post("/price-list-items/{item_id}/supersede", openapi_extra=MANAGE)
def supersede_price_list_item(actor: Actor, item_id: uuid.UUID, body: SupersedeItemCommand) -> PriceListItemRead:
    """Effective-dated price change on an active list: the current price ends the day before ``valid_from``."""
    with UnitOfWork(actor) as uow:
        return service.supersede_item(uow, item_id, body)


@router.post("/price-list-items/{item_id}/retire", openapi_extra=MANAGE)
def retire_price_list_item(actor: Actor, item_id: uuid.UUID, body: RetireItem) -> PriceListItemRead:
    """Retire the current price of a product (it stops resolving from ``retire_from``); history keeps it."""
    with UnitOfWork(actor) as uow:
        return service.retire_item(uow, item_id, body)


@router.get("/price-list-items/{item_id}/history", openapi_extra=READ)
def list_price_list_item_history(actor: Actor, item_id: uuid.UUID) -> list[PriceHistoryRead]:
    """Append-only history of the product's price in this list (created, edited, superseded, retired)."""
    return service.item_history(actor, item_id)


@router.post("/products/{product_id}/costs", status_code=201, openapi_extra=requires("pricing.cost.update"))
def record_product_cost(actor: Actor, product_id: uuid.UUID, body: ProductCostCreate) -> ProductCostRead:
    """Append a new protected cost version (``pricing.cost.update``; never logged or sent to a model)."""
    with UnitOfWork(actor) as uow:
        return service.record_product_cost(uow, product_id, body)


# =====================================================================================================
# Slice 2: FX snapshots
# =====================================================================================================
@router.get("/fx-rates", openapi_extra=FX_READ)
def list_fx_rates(
    actor: Actor,
    base_currency: CurrencyCode | None = None,
    quote_currency: CurrencyCode | None = None,
    status: Annotated[list[FxRateStatus] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FxRateRead]:
    return service.list_fx_rates(actor, base_currency=base_currency, quote_currency=quote_currency, status=status,
                                 limit=limit, offset=offset)


@router.post("/fx-rates", status_code=201, openapi_extra=requires("pricing.fx_rate.create"))
def propose_fx_rate(actor: Actor, body: FxRateCreate) -> FxRateRead:
    """Propose a dated, sourced rate; it converts prices only after a second person approves it."""
    with UnitOfWork(actor) as uow:
        row = service.propose_fx_rate(uow, body)
        return service.get_fx_rate(uow, row.id)


@router.get("/fx-rates/{fx_rate_id}", openapi_extra=FX_READ)
def get_fx_rate(actor: Actor, fx_rate_id: uuid.UUID) -> FxRateRead:
    return service.get_fx_rate(actor, fx_rate_id)


@router.post("/fx-rates/{fx_rate_id}/decision", openapi_extra=requires("pricing.fx_rate.approve"))
def decide_fx_rate(actor: Actor, fx_rate_id: uuid.UUID, body: FxDecision) -> FxRateRead:
    """Approve or reject a proposed rate (never by its proposer; 409 when it is no longer pending)."""
    with UnitOfWork(actor) as uow:
        service.decide_fx_rate(uow, fx_rate_id, body)
        return service.get_fx_rate(uow, fx_rate_id)


@router.post("/fx-rates/{fx_rate_id}/withdraw", openapi_extra=requires("pricing.fx_rate.create"))
def withdraw_fx_rate(actor: Actor, fx_rate_id: uuid.UUID) -> FxRateRead:
    """The proposer withdraws a pending rate."""
    with UnitOfWork(actor) as uow:
        service.withdraw_fx_rate(uow, fx_rate_id)
        return service.get_fx_rate(uow, fx_rate_id)


@router.get("/fx-policy", openapi_extra=FX_READ)
def get_fx_policy(actor: Actor) -> FxPolicyRead:
    """Whether approved rates convert prices, the source currency converted from, and the maximum rate age."""
    return service.get_fx_policy(actor)


@router.put("/fx-policy", openapi_extra=requires("pricing.fx_policy.manage"))
def update_fx_policy(actor: Actor, body: FxPolicyUpdate) -> FxPolicyRead:
    """Change the FX policy (``pricing.fx_policy.manage`` with a recent sign-in); 409 when stale."""
    with UnitOfWork(actor) as uow:
        return service.update_fx_policy(uow, body)
