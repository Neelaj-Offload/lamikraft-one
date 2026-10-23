"""Global search provider for parties (scoped, escaped ILIKE; never regex)."""

from __future__ import annotations

from app.modules.parties import service
from app.modules.parties.schemas import PartyFilters
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.uow import UnitOfWork


def search_parties(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    term = (q or "").strip()[:200]
    if len(term) < 2 or not uow.actor.can(service.READ):
        return []
    page = service.list_parties(uow, PartyFilters(q=term), limit=max(1, min(limit, 50)))
    needle = term.casefold()
    hits: list[SearchHit] = []
    for party in page.items:
        if party.party_number.casefold() == needle:
            rank = 100
        elif party.display_name.casefold() == needle or party.legal_name.casefold() == needle:
            rank = 90
        elif party.display_name.casefold().startswith(needle):
            rank = 50
        else:
            rank = 10
        roles = ", ".join(r.value.replace("_", " ") for r in party.roles)
        hits.append(
            SearchHit(
                resource_type="parties.party",
                resource_id=party.id,
                title=party.display_name,
                subtitle=f"{party.party_number} · {party.country_code} · {roles}",
                path=party.path,
                rank=rank,
            )
        )
    return sorted(hits, key=lambda h: (-h.rank, h.title))


PARTY_SEARCH = SearchProvider(
    resource_type="parties.party",
    group="Parties",
    permission=service.READ,
    search=search_parties,
)
