"""Global search provider for delivery challans (LM-96; scoped, escaped ILIKE on the normalised search text; never
regex, SEC-06). Matches the number, the destination, the shipping name and the reference; deleted drafts are not
found. The read scope is the list's scope, so a challan the actor cannot open is never a hit."""

from __future__ import annotations

from app.modules.challans import service
from app.modules.challans.schemas import STATUS_LABELS, TYPE_LABELS, ChallanFilters
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.uow import UnitOfWork


def _filters(q: str) -> ChallanFilters:
    return ChallanFilters(q=q)


def search_challans(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = (q or "").strip()[:200]
    if len(term) < 2 or not uow.actor.can(service.READ):
        return []
    page = service.list_challans(uow, _filters(term), limit=max(1, min(limit, 50)))
    needle = term.casefold()
    hits: list[SearchHit] = []
    for c in page.items:
        if c.challan_number.casefold() == needle:
            rank = 100
        elif (c.reference_no or "").casefold() == needle:
            rank = 80
        elif c.destination_party.casefold().startswith(needle):
            rank = 50
        else:
            rank = 10
        subtitle = " · ".join(
            part
            for part in (TYPE_LABELS[c.challan_type], STATUS_LABELS[c.status], c.challan_date.isoformat(), c.reference_no)
            if part
        )
        hits.append(
            SearchHit(
                resource_type="challans.challan",
                resource_id=c.id,
                title=f"{c.challan_number} · {c.destination_party}",
                subtitle=subtitle,
                path=c.path,
                rank=rank,
            )
        )
    return sorted(hits, key=lambda h: (-h.rank, h.title))


def count_challans(uow: UnitOfWork, q: str) -> int:
    term = (q or "").strip()[:200]
    if len(term) < 2 or not uow.actor.can(service.READ):
        return 0
    return service.list_challans(uow, _filters(term), limit=1).total


CHALLAN_SEARCH = SearchProvider(
    resource_type="challans.challan",
    group="Challans",
    permission=service.READ,
    search=search_challans,
    count=count_challans,
)
