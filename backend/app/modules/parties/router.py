"""Parties API (``/api/v1/parties``): list/search, read, create, update. Scope is enforced by the service."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.parties import service
from app.modules.parties.schemas import (
    CustomerType,
    PartyCreate,
    PartyDetail,
    PartyFilters,
    PartyRole,
    PartyStatus,
    PartySummary,
    PartyUpdate,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/parties", tags=["parties"])
REPLAYED = "Idempotent-Replayed"


def _filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against number, names and contacts")] = None,
    role: PartyRole | None = None,
    country_code: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")] = None,
    customer_type: CustomerType | None = None,
    status: Annotated[list[PartyStatus] | None, Query()] = None,
    owner_user_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> PartyFilters:
    return PartyFilters(
        q=q,
        role=role,
        country_code=country_code,
        customer_type=customer_type,
        status=status,
        owner_user_id=owner_user_id,
        include_archived=include_archived,
    )


@router.get("/parties", openapi_extra=requires("parties.party.read"))
def list_parties(
    actor: Actor,
    filters: Annotated[PartyFilters, Depends(_filters)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PartySummary]:
    """Parties within the actor's scope (own, team, branch or company); filters apply before pagination."""
    return service.list_parties(actor, filters, limit=limit, offset=offset)


@router.post("/parties", status_code=201, openapi_extra=requires("parties.party.create"))
def create_party(
    actor: Actor, body: PartyCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PartyDetail:
    """Create a party; the number ``P-NNNNN`` is allocated atomically and never reused."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.create_party_command(uow, body)
    if replayed:
        response.headers[REPLAYED] = "true"
    return detail


@router.get("/parties/lookup", openapi_extra=requires("parties.party.read"))
def get_party_by_number(
    actor: Actor, party_number: Annotated[str, Query(pattern=r"^[Pp]-[0-9]{5,}$")]
) -> PartyDetail:
    return service.get_party_by_number(actor, party_number)


@router.get("/parties/{party_id}", openapi_extra=requires("parties.party.read"))
def get_party(actor: Actor, party_id: uuid.UUID) -> PartyDetail:
    return service.get_party(actor, party_id)


@router.patch("/parties/{party_id}", openapi_extra=requires("parties.party.update"))
def update_party(
    actor: Actor,
    party_id: uuid.UUID,
    body: PartyUpdate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PartyDetail:
    """Dirty fields plus ``expected_version`` (409 ``version_conflict`` when stale)."""
    with UnitOfWork(actor) as uow:
        detail, replayed = service.update_party_command(uow, party_id, body)
    if replayed:
        response.headers[REPLAYED] = "true"
    return detail
