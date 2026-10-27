"""Typed payloads for pricing events (docs/architecture/events.md §3.5); no amounts in payloads."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

PRICE_LIST_CREATED = "pricing.price_list.created"
PRICE_LIST_ACTIVATED = "pricing.price_list.activated"
ITEM_SUPERSEDED = "pricing.price_list_item.superseded"
PRODUCT_COST_RECORDED = "pricing.product_cost.recorded"


class PriceListCreatedPayload(BaseModel):
    price_list_id: uuid.UUID
    code: str
    origin: str | None = None


class PriceListActivatedPayload(BaseModel):
    price_list_id: uuid.UUID
    code: str
    scope_kind: str
    price_type: str
    currency: str
    origin: str | None = None


class ItemSupersededPayload(BaseModel):
    item_id: uuid.UUID
    superseded_by_item_id: uuid.UUID
    price_list_id: uuid.UUID
    product_id: uuid.UUID
    origin: str | None = None


class ProductCostRecordedPayload(BaseModel):
    product_id: uuid.UUID
    cost_version: int
    source_kind: str
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=True)
