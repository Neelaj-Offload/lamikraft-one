"""Typed payloads for the catalogue events (names and fields frozen in docs/architecture/events.md §3.4).

Payloads carry ids, business keys and changed-field names only; consumers re-read through the service.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

PRODUCT_CREATED = "catalogue.product.created"
PRODUCT_UPDATED = "catalogue.product.updated"
CATEGORY_CREATED = "catalogue.category.created"
SUBCATEGORY_CREATED = "catalogue.subcategory.created"

#: changed_groups vocabulary (events.md §3.4)
GROUP_MASTER = "master"
GROUP_SPECIFICATION = "specification"
GROUP_PACKAGING = "packaging"
GROUP_DIMENSIONS = "dimensions"
GROUP_TAXONOMY = "taxonomy"
GROUP_STOCK_ATTRIBUTES = "stock_attributes"


class ProductCreatedPayload(BaseModel):
    product_id: uuid.UUID
    product_key: str
    origin: str | None = None


class ProductUpdatedPayload(BaseModel):
    product_id: uuid.UUID
    product_key: str
    changed_groups: list[str]
    changed_fields: list[str]
    origin: str | None = None


class CategoryCreatedPayload(BaseModel):
    category_id: uuid.UUID
    changed_fields: list[str]
    origin: str | None = None


class SubcategoryCreatedPayload(BaseModel):
    subcategory_id: uuid.UUID
    category_id: uuid.UUID
    changed_fields: list[str]
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    """JSON payload without unset optional fields (``origin`` defaults to the actor's origin when omitted)."""
    return model.model_dump(mode="json", exclude_none=True)
