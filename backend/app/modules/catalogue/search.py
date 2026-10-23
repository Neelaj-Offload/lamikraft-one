"""Global search provider for products (escaped ILIKE over the scoped list query; never regex)."""

from __future__ import annotations

from app.modules.catalogue import service
from app.modules.catalogue.schemas import ProductFilters
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.uow import UnitOfWork


def search_products(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = (q or "").strip()[:200]
    if len(term) < 2 or not uow.actor.can(service.READ):
        return []
    page = service.list_products(uow, ProductFilters(q=term), sort="relevance", limit=max(1, min(limit, 50)))
    needle = term.casefold()
    hits: list[SearchHit] = []
    for item in page.items:
        if item.product_key.casefold() == needle:
            rank = 100
        elif item.display_sku.casefold() == needle:
            rank = 90
        elif item.product_name.casefold().startswith(needle):
            rank = 50
        else:
            rank = 10
        taxonomy = item.category.name + (f" / {item.subcategory.name}" if item.subcategory else "")
        decor = f" · decor {item.decor_no}" + (f" {item.decor_name}" if item.decor_name else "") if item.decor_no else ""
        hits.append(
            SearchHit(
                resource_type="catalogue.product",
                resource_id=item.id,
                title=f"{item.product_key} · {item.product_name}",
                subtitle=f"{taxonomy}{decor}",
                path=item.path,
                rank=rank,
            )
        )
    return sorted(hits, key=lambda h: (-h.rank, h.title))


PRODUCT_SEARCH = SearchProvider(
    resource_type="catalogue.product",
    group="Products",
    permission=service.READ,
    search=search_products,
)
