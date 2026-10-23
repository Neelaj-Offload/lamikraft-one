"""Search API: grouped global search and the actor's recent searches."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.platform.search import service
from app.platform.search.models import QUERY_MAX_CHARS
from app.platform.search.schemas import RecentSearchCreate, RecentSearchRead, SearchResults

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    openapi_extra=requires("search.global.use"),
    operation_id="search_list_results",
    summary="Grouped results across every area the actor may read (at least 2 characters)",
)
def list_results(
    actor: Actor,
    q: str = Query(max_length=QUERY_MAX_CHARS),
    limit: int = Query(default=service.DEFAULT_PER_GROUP, ge=1, le=service.MAX_PER_GROUP),
    types: list[str] | None = Query(default=None, max_length=20),
) -> SearchResults:
    return service.search(actor, q, limit=limit, types=types)


@router.get("/recent", openapi_extra=requires("search.global.use"), operation_id="search_list_recent")
def list_recent(actor: Actor) -> list[RecentSearchRead]:
    return service.list_recent(actor)


@router.post(
    "/recent",
    status_code=201,
    openapi_extra=requires("search.global.use"),
    operation_id="search_create_recent",
    summary="Remember a submitted or selected search (newest 10 kept per user)",
)
def create_recent(body: RecentSearchCreate, actor: Actor) -> RecentSearchRead:
    return service.record_recent(actor, body.query)


@router.delete(
    "/recent", status_code=204, openapi_extra=requires("search.global.use"), operation_id="search_delete_recent"
)
def delete_recent(actor: Actor) -> Response:
    service.clear_recent(actor)
    return Response(status_code=204)
