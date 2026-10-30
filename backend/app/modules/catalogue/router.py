"""Catalogue API (``/api/v1/catalogue``): products, media, taxonomy, completeness and lookups. Routers never import
models; services enforce access."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import CurrencyCode
from app.modules.catalogue import lookups, media, products, service, taxonomy
from app.modules.catalogue.schemas import (
    CategoryCreate,
    CategoryRead,
    CompletenessRule,
    CompletenessSummary,
    ProductCreate,
    ProductDetail,
    ProductFacets,
    ProductFilters,
    ProductSort,
    ProductStats,
    ProductStatus,
    ProductSummary,
    ProductUpdate,
    ProductWriteResult,
)
from app.platform.uow import UnitOfWork

PriceTypeFilter = Literal["domestic", "export", "sample", "distributor"]
router = APIRouter(prefix="/catalogue", tags=["catalogue"])
READ = requires("catalogue.product.read")
MANAGE_TAXONOMY = requires("catalogue.taxonomy.manage")
LOOKUP_READ = requires("catalogue.lookup.read")
MEDIA_MANAGE = requires("catalogue.media.manage")
REPLAYED = "Idempotent-Replayed"
CSV = "text/csv; charset=utf-8"
_CSV_RESPONSE = {200: {"content": {CSV: {"schema": {"type": "string"}}}}}


def _csv(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type=CSV,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


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
    has_image: bool | None = None,
    has_price: Annotated[bool | None, Query(description="needs pricing.price.read")] = None,
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
        has_image=has_image,
        has_price=has_price,
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
    price_currency: Annotated[CurrencyCode, Query(description="currency of the price columns (no conversion)")] = "EUR",
    price_type: Annotated[PriceTypeFilter | None, Query(description="limit the price columns to one list type")] = None,
) -> Page[ProductSummary]:
    """Products with every filter applied before pagination; ``total`` counts the same filtered set. Rows carry the
    standard-list price in ``price_currency`` and the order-value recommendation only for ``pricing.price.read``."""
    return service.list_products(
        actor, filters, sort=sort, limit=limit, offset=offset, price_currency=price_currency, price_type=price_type
    )


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


@router.get("/products/recent", openapi_extra=READ)
def list_recent_products(
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=50)] = 6,
    price_currency: Annotated[CurrencyCode, Query(description="currency of the price column")] = "INR",
) -> list[products.RecentProductRow]:
    """Latest updated products with origin, actor and (with ``pricing.price.read``) the standard-list price."""
    return products.recent_products(actor, limit=limit, price_currency=price_currency)


@router.get(
    "/products/export.csv",
    openapi_extra=requires("catalogue.product.export"),
    response_class=Response,
    responses=_CSV_RESPONSE,
)
def export_products(actor: Actor, filters: Filters) -> Response:
    """Import-compatible CSV of the filtered products (formula-safe cells, UTF-8 BOM)."""
    return _csv(products.export_products_csv(actor, filters), "products.csv")


@router.get("/completeness", openapi_extra=READ)
def get_completeness(actor: Actor) -> CompletenessSummary:
    """Per-rule counts of distinct live products (API-67); each rule links to its ``issue=`` list filter."""
    return service.completeness_summary(actor)


@router.post("/products", status_code=201, openapi_extra=requires("catalogue.product.create"))
def create_product(
    actor: Actor, body: ProductCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ProductWriteResult:
    """Create a product with optional specification and packaging sections (422 errors carry field locations)."""
    with UnitOfWork(actor) as uow:
        result, replayed = products.create_product_command(uow, body)
    if replayed:
        response.headers[REPLAYED] = "true"
    return result


@router.get("/products/lookup", openapi_extra=READ)
def get_product_by_key(
    actor: Actor, key: Annotated[str, Query(min_length=1, max_length=120, description="the immutable product_key")]
) -> ProductDetail:
    """Resolve a business key (``/go/product/<key>`` links, API-13); keys may contain characters unsafe in a path."""
    return service.get_product_by_key(actor, key)


@router.get("/products/{product_id}", openapi_extra=READ)
def get_product(actor: Actor, product_id: uuid.UUID) -> ProductDetail:
    return service.get_product(actor, product_id)


@router.patch("/products/{product_id}", openapi_extra=requires("catalogue.product.update"))
def update_product(
    actor: Actor,
    product_id: uuid.UUID,
    body: ProductUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ProductWriteResult:
    """Dirty master fields plus ``expected_version`` (409 ``version_conflict`` when stale); ``product_key`` is
    immutable and rejected."""
    with UnitOfWork(actor) as uow:
        result, replayed = products.update_product_command(uow, product_id, body)
    if replayed:
        response.headers[REPLAYED] = "true"
    return result


@router.put("/products/{product_id}/specification", openapi_extra=requires("catalogue.product.update"))
def update_product_specification(
    actor: Actor, product_id: uuid.UUID, body: products.SpecificationPut
) -> ProductWriteResult:
    """Replace the specification section; dimension text is parsed into canonical millimetres."""
    with UnitOfWork(actor) as uow:
        return products.put_specification(uow, product_id, body)


@router.put("/products/{product_id}/packaging", openapi_extra=requires("catalogue.product.update"))
def update_product_packaging(actor: Actor, product_id: uuid.UUID, body: products.PackagingPut) -> ProductWriteResult:
    """Replace the packaging section; legacy alias pairs are reconciled (a disagreement is ``alias_conflict``)."""
    with UnitOfWork(actor) as uow:
        return products.put_packaging(uow, product_id, body)


@router.post("/products/{product_id}/archive", openapi_extra=requires("catalogue.product.archive"))
def archive_product(actor: Actor, product_id: uuid.UUID, body: products.ArchiveRequest) -> ProductDetail:
    with UnitOfWork(actor) as uow:
        return products.set_archived(uow, product_id, body, archived=True)


@router.post("/products/{product_id}/restore", openapi_extra=requires("catalogue.product.archive"))
def restore_product(actor: Actor, product_id: uuid.UUID, body: products.ArchiveRequest) -> ProductDetail:
    with UnitOfWork(actor) as uow:
        return products.set_archived(uow, product_id, body, archived=False)


@router.get("/products/{product_id}/history", openapi_extra=READ)
def list_product_history(
    actor: Actor,
    product_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[products.HistoryEntry]:
    return products.product_history(actor, product_id, limit=limit, offset=offset)


# ---- media ----------------------------------------------------------------------------------------------------------
@router.get("/products/{product_id}/media", openapi_extra=READ)
def list_product_media(actor: Actor, product_id: uuid.UUID, include_deleted: bool = False) -> media.MediaGroups:
    """Media grouped by type; download and preview through ``/api/v1/files/{file_id}/content``."""
    return media.list_media(actor, product_id, include_deleted=include_deleted)


@router.post("/products/{product_id}/media", status_code=201, openapi_extra=MEDIA_MANAGE)
def create_product_media(actor: Actor, product_id: uuid.UUID, body: media.MediaAttach) -> media.MediaRead:
    """Attach a file uploaded through ``POST /api/v1/files``; the first image becomes primary."""
    with UnitOfWork(actor) as uow:
        return media.attach_media(uow, product_id, body)


@router.patch("/media/{media_id}", openapi_extra=MEDIA_MANAGE)
def update_media(actor: Actor, media_id: uuid.UUID, body: media.MediaUpdate) -> media.MediaRead:
    with UnitOfWork(actor) as uow:
        return media.update_media(uow, media_id, body)


@router.post("/media/{media_id}/make-primary", openapi_extra=MEDIA_MANAGE)
def update_media_primary(actor: Actor, media_id: uuid.UUID, body: media.MediaVersion) -> media.MediaRead:
    with UnitOfWork(actor) as uow:
        return media.make_primary(uow, media_id, body)


@router.delete("/media/{media_id}", openapi_extra=MEDIA_MANAGE)
def delete_media(
    actor: Actor,
    media_id: uuid.UUID,
    expected_version: Annotated[int, Query(ge=1)],
    reason: Annotated[str, Query(min_length=1, max_length=500)],
) -> media.MediaRead:
    """Soft delete with a reason (the stored file is kept; restore brings the link back)."""
    with UnitOfWork(actor) as uow:
        return media.delete_media(uow, media_id, media.MediaDelete(expected_version=expected_version, reason=reason))


@router.post("/media/{media_id}/restore", openapi_extra=MEDIA_MANAGE)
def restore_media(actor: Actor, media_id: uuid.UUID, body: media.MediaVersion) -> media.MediaRead:
    with UnitOfWork(actor) as uow:
        return media.restore_media(uow, media_id, body)


# ---- taxonomy -------------------------------------------------------------------------------------------------------
@router.get("/categories", openapi_extra=READ)
def list_categories(actor: Actor, include_inactive: bool = False) -> list[CategoryRead]:
    return service.list_categories(actor, include_inactive=include_inactive)


@router.post("/categories", status_code=201, openapi_extra=MANAGE_TAXONOMY)
def create_category(actor: Actor, body: CategoryCreate) -> CategoryRead:
    """New categories are active by default (BUG-07)."""
    with UnitOfWork(actor) as uow:
        return taxonomy.create_category(uow, body)


@router.post("/categories/reorder", openapi_extra=MANAGE_TAXONOMY)
def update_category_order(actor: Actor, body: taxonomy.ReorderRequest) -> list[CategoryRead]:
    with UnitOfWork(actor) as uow:
        return taxonomy.reorder(uow, body)


@router.patch("/categories/{category_id}", openapi_extra=MANAGE_TAXONOMY)
def update_category(actor: Actor, category_id: uuid.UUID, body: taxonomy.TaxonomyUpdate) -> CategoryRead:
    """Rename (the old name becomes an alias; product search text is refreshed), reorder, (de)activate."""
    with UnitOfWork(actor) as uow:
        return taxonomy.update_category(uow, category_id, body)


@router.post("/categories/{category_id}/subcategories", status_code=201, openapi_extra=MANAGE_TAXONOMY)
def create_subcategory(actor: Actor, category_id: uuid.UUID, body: CategoryCreate) -> CategoryRead:
    with UnitOfWork(actor) as uow:
        return taxonomy.create_subcategory(uow, category_id, body)


@router.get("/categories/{category_id}/references", openapi_extra=READ)
def get_category_references(actor: Actor, category_id: uuid.UUID) -> taxonomy.TaxonomyReferences:
    with UnitOfWork(actor) as uow:
        return taxonomy.category_references(uow, category_id)


@router.post("/categories/{category_id}/delete", openapi_extra=MANAGE_TAXONOMY)
def delete_category(
    actor: Actor, category_id: uuid.UUID, body: taxonomy.TaxonomyDelete
) -> taxonomy.TaxonomyDeleteResult:
    """Refused (409 ``taxonomy_referenced``) while referenced, unless reassigned with the confirmed counts."""
    with UnitOfWork(actor) as uow:
        return taxonomy.delete_category(uow, category_id, body)


@router.patch("/subcategories/{subcategory_id}", openapi_extra=MANAGE_TAXONOMY)
def update_subcategory(actor: Actor, subcategory_id: uuid.UUID, body: taxonomy.TaxonomyUpdate) -> CategoryRead:
    with UnitOfWork(actor) as uow:
        return taxonomy.update_subcategory(uow, subcategory_id, body)


@router.get("/subcategories/{subcategory_id}/references", openapi_extra=READ)
def get_subcategory_references(actor: Actor, subcategory_id: uuid.UUID) -> taxonomy.TaxonomyReferences:
    with UnitOfWork(actor) as uow:
        return taxonomy.subcategory_references(uow, subcategory_id)


@router.post("/subcategories/{subcategory_id}/delete", openapi_extra=MANAGE_TAXONOMY)
def delete_subcategory(
    actor: Actor, subcategory_id: uuid.UUID, body: taxonomy.TaxonomyDelete
) -> taxonomy.TaxonomyDeleteResult:
    with UnitOfWork(actor) as uow:
        return taxonomy.delete_subcategory(uow, subcategory_id, body)


@router.get("/taxonomy/validation", openapi_extra=READ)
def get_taxonomy_validation(actor: Actor) -> taxonomy.TaxonomyValidation:
    """Unresolved subcategory text, products in inactive taxonomy, inferred and empty categories (API-22)."""
    return taxonomy.validation_report(actor)


# ---- lookups --------------------------------------------------------------------------------------------------------
@router.get("/lookups", openapi_extra=LOOKUP_READ)
def list_lookups(
    actor: Actor,
    lookup_type: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[lookups.LookupRead]:
    """Reference-only legacy lookup rows (no business rule reads them); filters apply before paging."""
    return lookups.list_lookups(actor, lookup_type=lookup_type, q=q, limit=limit, offset=offset)


@router.get("/lookups/types", openapi_extra=LOOKUP_READ)
def list_lookup_types(actor: Actor) -> list[lookups.LookupType]:
    return lookups.lookup_types(actor)


@router.get("/lookups/export.csv", openapi_extra=LOOKUP_READ, response_class=Response, responses=_CSV_RESPONSE)
def export_lookups(
    actor: Actor,
    lookup_type: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Response:
    """Safe CSV of the filtered lookup rows (import-compatible columns)."""
    return _csv(lookups.export_lookups_csv(actor, lookup_type=lookup_type, q=q), "lookup_reference.csv")
