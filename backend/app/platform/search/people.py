"""The people search provider: the company directory (``org.directory.read``).

Only directory facts are searched and returned — name and job title (permissions.md: "name, title, team; no
contact details"): never email, phone or anything from the identity tables beyond the display name. Only
active members of the actor's company are found. Every query token must match the name or the title
(escaped ILIKE; the token is literal text).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.text import normalize_search_text
from app.platform.identity.models import AppUser, Membership
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.search.service import match_all_terms, search_terms

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


def search_people(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    terms = search_terms(q)
    if not terms:
        return []
    match = match_all_terms((AppUser.display_name, AppUser.full_name, Membership.job_title), q)
    rows = uow.session.execute(
        select(Membership.user_id, AppUser.display_name, Membership.job_title, Membership.department)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(
            Membership.company_id == uow.actor.company_id,
            Membership.status == "active",
            AppUser.status == "active",
            match,
        )
        .order_by(AppUser.display_name, Membership.user_id)
        .limit(limit)
    ).all()
    whole = normalize_search_text(q)
    hits: list[SearchHit] = []
    for user_id, display_name, job_title, department in rows:
        name = normalize_search_text(display_name)
        rank = 3 if name == whole else 2 if name.startswith(whole) else 1 if any(
            part.startswith(terms[0]) for part in name.split(" ")
        ) else 0
        subtitle = " · ".join(p for p in (job_title, department) if p) or None
        hits.append(
            SearchHit(
                resource_type="org.person",
                resource_id=user_id,
                title=display_name,
                subtitle=subtitle,
                path=f"/people/{user_id}",
                rank=rank,
            )
        )
    return hits


PEOPLE_PROVIDER = SearchProvider(
    resource_type="org.person",
    group="People",
    permission="org.directory.read",
    search=search_people,
)
