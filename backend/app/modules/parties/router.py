"""Parties API (``/api/v1/parties``): list/search, read, create, update. Scope is enforced by the service."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.parties import activities, customer_types, lead_sources, leads, service
from app.modules.parties.schemas import (
    ActivityCreate,
    ActivityRead,
    CustomerType,
    CustomerTypeCreate,
    CustomerTypeRead,
    CustomerTypeUpdate,
    Interest,
    LeadSourceCreate,
    LeadSourceRead,
    LeadSourceUpdate,
    LeadStage,
    LeadStageChange,
    LeadSummary,
    PartyActivityPage,
    PartyCreate,
    PartyDetail,
    PartyFilters,
    PartyRole,
    PartyStatus,
    PartySummary,
    PartyUpdate,
    Priority,
    Temperature,
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
    lead_stage: Annotated[list[LeadStage] | None, Query()] = None,
    lead_source: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,19}$")] = None,
    interest: Interest | None = None,
    priority: Priority | None = None,
    temperature: Temperature | None = None,
    follow_up: Annotated[Literal["overdue", "today", "week"] | None, Query()] = None,
    sort: Annotated[Literal["name", "follow_up", "recent"], Query()] = "name",
) -> PartyFilters:
    return PartyFilters(
        q=q,
        role=role,
        country_code=country_code,
        customer_type=customer_type,
        status=status,
        owner_user_id=owner_user_id,
        include_archived=include_archived,
        lead_stage=lead_stage,
        lead_source=lead_source,
        interest=interest,
        priority=priority,
        temperature=temperature,
        follow_up=follow_up,
        sort=sort,
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


@router.get("/parties/lead-summary", openapi_extra=requires("parties.party.read"))
def get_lead_summary(actor: Actor) -> LeadSummary:
    """Pipeline numbers (by stage, source, owner; follow-ups due) over the leads the caller may read."""
    return leads.lead_summary(actor)


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


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


@router.post("/parties/{party_id}/archive", openapi_extra=requires("parties.party.archive"))
def archive_party(actor: Actor, party_id: uuid.UUID, body: ArchiveRequest) -> PartyDetail:
    """Archive a party (hidden from pickers and lists by default; quotes keep their snapshot)."""
    with UnitOfWork(actor) as uow:
        return service.set_party_archived(uow, party_id, archived=True, expected_version=body.expected_version)


@router.post("/parties/{party_id}/restore", openapi_extra=requires("parties.party.archive"))
def restore_party(actor: Actor, party_id: uuid.UUID, body: ArchiveRequest) -> PartyDetail:
    with UnitOfWork(actor) as uow:
        return service.set_party_archived(uow, party_id, archived=False, expected_version=body.expected_version)


@router.get("/customer-types", openapi_extra=requires("parties.party.read"))
def list_customer_types(actor: Actor, include_inactive: bool = True) -> list[CustomerTypeRead]:
    """The company's customer types (built-in standard, dealer, distributor plus any added)."""
    return customer_types.list_customer_types(actor, include_inactive=include_inactive)


@router.post("/customer-types", status_code=201, openapi_extra=requires("parties.customer_type.manage"))
def create_customer_type(actor: Actor, body: CustomerTypeCreate) -> CustomerTypeRead:
    with UnitOfWork(actor) as uow:
        return customer_types.create_customer_type(uow, body)


@router.patch("/customer-types/{customer_type_id}", openapi_extra=requires("parties.customer_type.manage"))
def update_customer_type(actor: Actor, customer_type_id: uuid.UUID, body: CustomerTypeUpdate) -> CustomerTypeRead:
    """Relabel, reorder or (de)activate; codes are immutable and built-in types are never removed."""
    with UnitOfWork(actor) as uow:
        return customer_types.update_customer_type(uow, customer_type_id, body)


@router.post("/parties/{party_id}/lead-stage", openapi_extra=requires("parties.party.update"))
def change_lead_stage(actor: Actor, party_id: uuid.UUID, body: LeadStageChange) -> PartyDetail:
    """Move a lead through the pipeline; ``lost`` needs ``lost_reason``; ``won`` makes it a customer (final)."""
    with UnitOfWork(actor) as uow:
        return leads.change_lead_stage(uow, party_id, body)


@router.get("/parties/{party_id}/activities", openapi_extra=requires("parties.party.read"))
def list_activities(
    actor: Actor,
    party_id: uuid.UUID,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> PartyActivityPage:
    """The activity log, newest first."""
    return activities.list_activities(actor, party_id, cursor=cursor, limit=limit)


@router.post("/parties/{party_id}/activities", status_code=201, openapi_extra=requires("parties.activity.create"))
def log_activity(actor: Actor, party_id: uuid.UUID, body: ActivityCreate) -> ActivityRead:
    """Log a call, email, WhatsApp, meeting, visit or note; ``next_follow_up_on`` sets the owner's next task."""
    with UnitOfWork(actor) as uow:
        return activities.log_activity(uow, party_id, body)


@router.get("/lead-sources", openapi_extra=requires("parties.party.read"))
def list_lead_sources(actor: Actor, include_inactive: bool = True) -> list[LeadSourceRead]:
    """Where leads come from (website, trade shows, visiting cards), with live lead counts."""
    return lead_sources.list_lead_sources(actor, include_inactive=include_inactive)


@router.post("/lead-sources", status_code=201, openapi_extra=requires("parties.lead_source.manage"))
def create_lead_source(actor: Actor, body: LeadSourceCreate) -> LeadSourceRead:
    with UnitOfWork(actor) as uow:
        return lead_sources.create_lead_source(uow, body)


@router.patch("/lead-sources/{lead_source_id}", openapi_extra=requires("parties.lead_source.manage"))
def update_lead_source(actor: Actor, lead_source_id: uuid.UUID, body: LeadSourceUpdate) -> LeadSourceRead:
    with UnitOfWork(actor) as uow:
        return lead_sources.update_lead_source(uow, lead_source_id, body)
