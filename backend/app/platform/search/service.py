"""Global search: runs the registered providers the actor may read, groups and caps their hits, and keeps
each user's recent searches.

Queries are tokenised (``app.core.text.tokens``) and every provider matches tokens with escaped ILIKE
(``escape_like``): ``%``, ``_``, ``\\`` and regular-expression metacharacters in the input are literal text.
Providers run inside a savepoint each, so one failing provider is reported as unavailable instead of
breaking the whole search. Group visibility, hit rows and group totals are permission-filtered on the server;
``offset`` pages through a single group for the "See all results" page (frontend_verification §12).
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import ColumnElement, and_, delete, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import ValidationFailed
from app.core.text import LIKE_ESCAPE, contains_pattern, normalize_search_text, tokens
from app.platform.search.defs import SearchHit, SearchProvider
from app.platform.search.models import QUERY_MAX_CHARS, RECENT_KEEP, SearchRecent
from app.platform.search.schemas import RecentSearchRead, SearchGroupRead, SearchHitRead, SearchResults
from app.platform.service import command, query
from app.platform.sources import SourceFacts

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

log = structlog.get_logger(__name__)

MIN_QUERY_CHARS = 2
DEFAULT_PER_GROUP = 5
MAX_PER_GROUP = 20
#: deepest offset the "See all results" page may request within one group
MAX_OFFSET = 200


MAX_TERMS = 8


def search_terms(q: str) -> list[str]:
    """The literal terms of a query: whitespace-separated, case- and diacritic-folded, at most 8.

    Terms are plain text. They are only ever used inside escaped ILIKE patterns (``contains_pattern``), so
    ``%``, ``_``, the backslash and regular-expression metacharacters such as ``.*[](){}|^$+?`` match themselves.
    """
    return tokens(q[:QUERY_MAX_CHARS], max_tokens=MAX_TERMS)


def term_forms(q: str) -> list[set[str]]:
    """Per term: the folded form plus the case-folded original (stored text is not diacritic-folded)."""
    raw = [unicodedata.normalize("NFC", t).casefold() for t in q[:QUERY_MAX_CHARS].split()][:MAX_TERMS]
    folded = search_terms(q)
    forms: list[set[str]] = []
    for i, term in enumerate(folded):
        options = {term}
        if i < len(raw) and raw[i]:
            options.add(raw[i])
        forms.append(options)
    return forms


def match_all_terms(columns: Sequence[ColumnElement[Any]], q: str) -> ColumnElement[bool]:
    """Every term must occur (escaped ILIKE, literal text) in at least one of ``columns``.

    The helper search providers use to build their WHERE clause; an empty query matches nothing.
    """
    forms = term_forms(q)
    if not forms or not columns:
        return false()
    return and_(
        *[
            or_(*[col.ilike(contains_pattern(form), escape=LIKE_ESCAPE) for col in columns for form in sorted(options)])
            for options in forms
        ]
    )


def providers() -> list[SearchProvider]:
    from app.registry import get_registry

    return [p for p in get_registry().search_providers if isinstance(p, SearchProvider)]


def _hits(provider: SearchProvider, uow: UnitOfWork, q: str, limit: int) -> list[SearchHit]:
    hits = provider.search(uow, q, limit)
    for hit in hits:
        if hit.resource_type != provider.resource_type:
            raise ValueError(f"provider {provider.resource_type} returned a {hit.resource_type} hit")
    # Providers order hits in SQL (rank, then title) before their LIMIT. A stable sort on rank alone keeps
    # their tie order, so a page cut from a longer prefix lines up with the previous page (no repeats or gaps).
    return sorted(hits, key=lambda h: -h.rank)


@query("search.global.use")
def search(
    uow: UnitOfWork,
    q: str,
    *,
    limit: int = DEFAULT_PER_GROUP,
    types: Sequence[str] | None = None,
    offset: int = 0,
) -> SearchResults:
    """Grouped hits from every provider the actor may read (optionally only ``types``), ``limit`` per group.

    ``offset`` pages through one group (the "See all results" page) and therefore needs exactly one type.
    Each group reports ``total`` when its provider can count (the same permission-filtered query).
    """
    q = q[:QUERY_MAX_CHARS]
    terms = search_terms(q)
    per_group = max(1, min(limit, MAX_PER_GROUP))
    wanted = set(types) if types else None
    if offset < 0 or offset > MAX_OFFSET:
        raise ValidationFailed(
            errors=[{"loc": ["query", "offset"], "msg": f"between 0 and {MAX_OFFSET}", "code": "out_of_range"}]
        )
    if offset and (wanted is None or len(wanted) != 1):
        raise ValidationFailed(
            "Page through one group at a time.",
            errors=[{"loc": ["query", "offset"], "msg": "offset needs exactly one type", "code": "offset_needs_one_type"}],
        )
    results = SearchResults(query=q, terms=terms, groups=[])
    if len(normalize_search_text(q)) < MIN_QUERY_CHARS or not terms:
        return results
    for provider in providers():
        if wanted is not None and provider.resource_type not in wanted:
            continue
        if not uow.actor.can(provider.permission):
            continue
        savepoint = uow.session.begin_nested()
        try:
            hits = _hits(provider, uow, q, offset + per_group + 1)
            total = provider.count(uow, q) if provider.count is not None else None
            savepoint.commit()
        except Exception as exc:  # isolate providers: report the group as unavailable
            savepoint.rollback()
            log.warning("search.provider_failed", provider=provider.resource_type, error=type(exc).__name__)
            results.unavailable_groups.append(provider.group)
            continue
        page = hits[offset : offset + per_group]
        if not page and offset == 0:
            continue
        results.groups.append(
            SearchGroupRead(
                resource_type=provider.resource_type,
                group=provider.group,
                hits=[
                    SearchHitRead(
                        resource_type=h.resource_type,
                        resource_id=h.resource_id,
                        title=h.title,
                        subtitle=h.subtitle,
                        path=h.path,
                    )
                    for h in page
                ],
                has_more=len(hits) > offset + per_group,
                offset=offset,
                total=total,
            )
        )
    return results


# ---- recent searches --------------------------------------------------------------------------------------
def _recent_rows(uow: UnitOfWork) -> list[SearchRecent]:
    return list(
        uow.session.scalars(
            select(SearchRecent)
            .where(SearchRecent.company_id == uow.actor.company_id, SearchRecent.user_id == uow.actor.user_id)
            .order_by(SearchRecent.searched_at.desc(), SearchRecent.id.desc())
            .limit(RECENT_KEEP)
        )
    )


def _require_user(uow: UnitOfWork) -> None:
    from app.core.errors import Forbidden

    if uow.actor.user_id is None or uow.actor.company_id is None:
        raise Forbidden(code="permission_denied", permission="search.global.use")


@query("search.global.use")
def list_recent(uow: UnitOfWork) -> list[RecentSearchRead]:
    _require_user(uow)
    return [RecentSearchRead(id=r.id, query=r.query, searched_at=r.searched_at) for r in _recent_rows(uow)]


@command("search.global.use")
def record_recent(uow: UnitOfWork, q: str) -> RecentSearchRead:
    """Remember a submitted or selected search (repeats move to the top); keeps the newest 10 per user."""
    _require_user(uow)
    display = " ".join(q.split())[:QUERY_MAX_CHARS]
    normalized = normalize_search_text(display)[:QUERY_MAX_CHARS]
    if not normalized:
        raise ValidationFailed(errors=[{"loc": ["body", "query"], "msg": "empty search", "code": "empty"}])
    actor = uow.actor
    now = uow.now()
    stmt = pg_insert(SearchRecent).values(
        id=uuid.uuid7(),
        company_id=actor.company_id,
        user_id=actor.user_id,
        query=display,
        normalized_query=normalized,
        searched_at=now,
    )
    row_id = uow.session.execute(
        stmt.on_conflict_do_update(
            index_elements=["company_id", "user_id", "normalized_query"],
            set_={"query": stmt.excluded.query, "searched_at": stmt.excluded.searched_at},
        ).returning(SearchRecent.id)
    ).scalar_one()
    keep = (
        select(SearchRecent.id)
        .where(SearchRecent.company_id == actor.company_id, SearchRecent.user_id == actor.user_id)
        .order_by(SearchRecent.searched_at.desc(), SearchRecent.id.desc())
        .limit(RECENT_KEEP)
    )
    uow.session.execute(
        delete(SearchRecent).where(
            SearchRecent.company_id == actor.company_id,
            SearchRecent.user_id == actor.user_id,
            SearchRecent.id.not_in(keep.scalar_subquery()),
        )
    )
    return RecentSearchRead(id=row_id, query=display, searched_at=now)


@command("search.global.use")
def clear_recent(uow: UnitOfWork) -> int:
    _require_user(uow)
    result = uow.session.execute(
        delete(SearchRecent).where(
            SearchRecent.company_id == uow.actor.company_id, SearchRecent.user_id == uow.actor.user_id
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def has_recent_search(uow: UnitOfWork, user_id: uuid.UUID) -> bool:
    """For onboarding completion checks ("use global search"): has this user searched at all?"""
    count = uow.session.scalar(
        select(func.count())
        .select_from(SearchRecent)
        .where(SearchRecent.company_id == uow.actor.company_id, SearchRecent.user_id == user_id)
    )
    return bool(count)


def read_recent_search_facts(uow: UnitOfWork, user_id: uuid.UUID) -> SourceFacts | None:
    """``search.recent`` SourceReader (source id = user id): how many recent searches the user has (onboarding
    step "Use global search"). Personal: only the system and the user themself get facts."""
    actor = uow.actor
    if not (actor.is_system or actor.user_id == user_id) or actor.company_id is None:
        return None
    count, last = uow.session.execute(
        select(func.count(), func.max(SearchRecent.searched_at)).where(
            SearchRecent.company_id == actor.company_id, SearchRecent.user_id == user_id
        )
    ).one()
    return SourceFacts(
        source_type="search.recent",
        source_id=user_id,
        version=None,
        label="Recent searches",
        status="active",
        owner_user_id=user_id,
        branch_id=None,
        required_permission="search.global.use",
        canonical_path="/search",
        updated_at=last,
        facts={"count": int(count or 0)},
    )
