"""Global search providers for sales: custom products by ``product_name`` (BUG-08, SCN-G5), code and decor; quotes
by number and customer; samples by number. Every provider runs the scoped list query (escaped ILIKE, never regex)."""

from __future__ import annotations

from app.modules.sales import custom_products, quotes, samples
from app.modules.sales.schemas import CustomProductFilters, QuoteFilters, SampleFilters
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.uow import UnitOfWork


def _term(q: str) -> str | None:
    term = (q or "").strip()[:200]
    return term if len(term) >= 2 else None


def search_custom_products(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = _term(q)
    if term is None or not uow.actor.can(custom_products.READ):
        return []
    page = custom_products.list_custom_products(uow, CustomProductFilters(q=term), limit=max(1, min(limit, 50)))
    needle = term.casefold()
    hits = []
    for item in page.items:
        rank = 100 if item.custom_code.casefold() == needle else 50 if item.product_name.casefold().startswith(needle) else 10
        hits.append(SearchHit(
            resource_type="sales.custom_product", resource_id=item.id, title=f"{item.custom_code} · {item.product_name}",
            subtitle=" · ".join(p for p in (item.status.value.replace("_", " "), item.party.display_name if item.party else item.legacy_customer_name) if p),
            path=item.path, rank=rank,
        ))
    return sorted(hits, key=lambda h: (-h.rank, h.title))


def search_quotes(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = _term(q)
    if term is None or not uow.actor.can(quotes.READ):
        return []
    page = quotes.list_quotes(uow, QuoteFilters(q=term), limit=max(1, min(limit, 50)))
    needle = term.casefold()
    return [
        SearchHit(
            resource_type="sales.quote", resource_id=item.id, title=f"{item.quote_number} · {item.party.display_name}",
            subtitle=f"{item.status.value.replace('_', ' ')} · {item.currency}", path=item.path,
            rank=100 if item.quote_number.casefold() == needle else 20,
        )
        for item in page.items
    ]


def search_samples(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = _term(q)
    if term is None or not uow.actor.can(samples.READ):
        return []
    page = samples.list_samples(uow, SampleFilters(q=term), limit=max(1, min(limit, 50)))
    return [
        SearchHit(resource_type="sales.sample", resource_id=item.id, title=f"{item.sample_number} · {item.description}",
                  subtitle=f"{item.status.value.replace('_', ' ')} · {item.party.display_name}", path=item.path, rank=20)
        for item in page.items
    ]


CUSTOM_PRODUCT_SEARCH = SearchProvider(resource_type="sales.custom_product", group="Custom products",
                                       permission=custom_products.READ, search=search_custom_products)
QUOTE_SEARCH = SearchProvider(resource_type="sales.quote", group="Quotes", permission=quotes.READ, search=search_quotes)
SAMPLE_SEARCH = SearchProvider(resource_type="sales.sample", group="Samples", permission=samples.READ, search=search_samples)

SEARCH_PROVIDERS = [QUOTE_SEARCH, CUSTOM_PRODUCT_SEARCH, SAMPLE_SEARCH]
