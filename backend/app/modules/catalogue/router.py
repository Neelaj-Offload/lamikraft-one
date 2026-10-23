"""Catalogue read API (``/api/v1/catalogue``). Routers never import models; services enforce access."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.catalogue import service
from app.modules.catalogue.schemas import (
    CategoryRead,
    CompletenessRule,
    CompletenessSummary,
    ProductDetail,
    ProductFacets,
    ProductFilters,
    ProductSort,
    ProductStats,
    ProductStatus,
    ProductSummary,
)

router = APIRouter(prefix="/catalogue", tags=["catalogue"])
READ = requires("catalogue.product.read")


def _filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against key, SKU, name, decor, finish, family and taxonomy")] = None,
    category_id: uuid.UUID | None = None,
    subcategory_id: uuid.UUID | None = None,
    family: Annotated[str | None, Query(max_length=200, description="variant group")] = None,
    size: Annotated[str | None, Query(max_length=60, description="length x width, e.g. 450x300 (mm)")] = None,
    thickness: Annotated[str | None, Query(max_length=20, description="millimetres; 0.8 equals 0.80")] = None,
    decor: Annotated[str | None, Query(max_length=40, description="decor number as text; 0120 differs from 120")] = None,
    finish: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[list[ProductStatus] | None, Query()] = None,
    brand: Annotated[str | None, Query(max_length=40)] = None,
    issue: CompletenessRule | None = None,
    include_archived: bool = False,
) -> ProductFilters:
    return ProductFilters(
        q=q,
        category_id=category_id,
        subcategory_id=subcategory_id,
        family=family,
        size=size,
        thickness=thickness,
        decor=decor,
        finish=finish,
        status=status,
        brand=brand,
        issue=issue,
        include_archived=include_archived,
    )


Filters = Annotated[ProductFilters, Depends(_filters)]


@router.get("/products", openapi_extra=READ)
def list_products(
    actor: Actor,
    filters: Filters,
    sort: ProductSort = "product_key",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProductSummary]:
    """Products with every filter applied before pagination; ``total`` counts the same filtered set."""
    return service.list_products(actor, filters, sort=sort, limit=limit, offset=offset)


@router.get("/products/facets", openapi_extra=READ)
def get_product_facets(actor: Actor, filters: Filters) -> ProductFacets:
    """Facet counts; each dimension is counted with every other active filter applied (exclude-self)."""
    return service.product_facets(actor, filters)


@router.get("/products/stats", openapi_extra=READ)
def get_product_stats(actor: Actor) -> ProductStats:
    return service.product_stats(actor)


@router.get("/products/completeness", openapi_extra=READ)
def get_product_completeness(actor: Actor) -> CompletenessSummary:
    return service.completeness_summary(actor)


@router.get("/products/lookup", openapi_extra=READ)
def get_product_by_key(actor: Actor, product_key: Annotated[str, Query(min_length=1, max_length=120)]) -> ProductDetail:
    """Resolve a business key (``/go/product/<key>`` links); keys may contain characters unsafe in a path."""
    return service.get_product_by_key(actor, product_key)


@router.get("/products/{product_id}", openapi_extra=READ)
def get_product(actor: Actor, product_id: uuid.UUID) -> ProductDetail:
    return service.get_product(actor, product_id)


@router.get("/categories", openapi_extra=READ)
def list_categories(actor: Actor, include_inactive: bool = False) -> list[CategoryRead]:
    return service.list_categories(actor, include_inactive=include_inactive)
