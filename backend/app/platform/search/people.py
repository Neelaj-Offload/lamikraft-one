"""The people search provider: the company directory (``org.directory.read``).

Only directory facts are searched and returned — name and job title (permissions.md: "name, title, team; no
contact details"): never email, phone or anything from the identity tables beyond the display name. Only
active members of the actor's company are found, through a ``ScopedRepository`` over ``membership`` with the
directory policy below. Every query token must match the name or the title (escaped ILIKE; the token is
literal text). Hits are ranked in SQL (exact name, name prefix, word prefix) before the LIMIT, so an exact
match is never cut off by partial matches that sort earlier alphabetically.

There is no person page in the route plan (frontend_verification §6), so a hit opens the planned S1 search
page filtered to the People group (``/search?q=<name>&types=org.person``), which shows the same directory
card; when the web lane adds a person route, only ``person_path`` changes.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from sqlalchemy import ColumnElement, case, func, or_, select

from app.core.text import LIKE_ESCAPE, escape_like, normalize_search_text
from app.platform.authz.policy import ResourcePolicy
from app.platform.authz.repository import ScopedRepository
from app.platform.identity.models import AppUser, Membership
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.search.service import match_all_terms, search_terms, term_forms

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

RESOURCE_TYPE = "org.person"
#: the planned S1 search page (frontend_verification §6: ``/search?q=``)
SEARCH_ROUTE = "/search"

#: Directory visibility as a resource policy: ``org.directory.read`` (company scope for every employee; an own
#: scope would show only oneself). Deliberately not registered globally: the identity lane owns ``membership``
#: and its policy, and registering this one would also make "org.person" a parent type for notes.
DIRECTORY_POLICY = ResourcePolicy(
    resource_type=RESOURCE_TYPE,
    model=Membership,
    permission_prefix="org.directory",
    owner_columns=("user_id",),
    archived_column=None,
)


def person_path(display_name: str) -> str:
    return f"{SEARCH_ROUTE}?{urlencode({'q': display_name, 'types': RESOURCE_TYPE})}"


def _whole_forms(q: str) -> list[str]:
    """The whole query, folded and as typed (stored names are not diacritic-folded)."""
    typed = " ".join(unicodedata.normalize("NFC", q).casefold().split())
    return sorted({normalize_search_text(q), typed} - {""})


def _rank(q: str) -> ColumnElement[Any]:
    name = AppUser.display_name
    whole = _whole_forms(q)
    first = sorted(term_forms(q)[0])
    exact = or_(*[name.ilike(escape_like(f), escape=LIKE_ESCAPE) for f in whole])
    prefix = or_(*[name.ilike(f"{escape_like(f)}%", escape=LIKE_ESCAPE) for f in whole])
    word = or_(
        *[name.ilike(f"{escape_like(f)}%", escape=LIKE_ESCAPE) for f in first],
        *[name.ilike(f"% {escape_like(f)}%", escape=LIKE_ESCAPE) for f in first],
    )
    return case((exact, 3), (prefix, 2), (word, 1), else_=0)


def _filters(uow: UnitOfWork, q: str) -> list[ColumnElement[bool]]:
    directory = ScopedRepository[Membership](uow, DIRECTORY_POLICY)
    return [
        directory.clause("read"),
        Membership.status == "active",
        AppUser.status == "active",
        match_all_terms((AppUser.display_name, AppUser.full_name, Membership.job_title), q),
    ]


def search_people(uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    if not search_terms(q):
        return []
    rank = _rank(q).label("rank")
    rows = uow.session.execute(
        select(Membership.user_id, AppUser.display_name, Membership.job_title, Membership.department, rank)
        .select_from(Membership)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(*_filters(uow, q))
        .order_by(rank.desc(), func.lower(AppUser.display_name).collate("C"), Membership.user_id)
        .limit(limit)
    ).all()
    return [
        SearchHit(
            resource_type=RESOURCE_TYPE,
            resource_id=user_id,
            title=display_name,
            subtitle=" · ".join(p for p in (job_title, department) if p) or None,
            path=person_path(display_name),
            rank=int(hit_rank),
        )
        for user_id, display_name, job_title, department, hit_rank in rows
    ]


def count_people(uow: UnitOfWork, q: str) -> int:
    if not search_terms(q):
        return 0
    return int(
        uow.session.scalar(
            select(func.count())
            .select_from(Membership)
            .join(AppUser, AppUser.id == Membership.user_id)
            .where(*_filters(uow, q))
        )
        or 0
    )


PEOPLE_PROVIDER = SearchProvider(
    resource_type=RESOURCE_TYPE,
    group="People",
    permission="org.directory.read",
    search=search_people,
    count=count_people,
)
