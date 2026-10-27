"""Briefings API: Today (generated on first open), acknowledgements, item actions, the delta view and
voice/chat pins. Every resource is the caller's own; other users' ids return 404."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.briefings import service
from app.modules.briefings.schemas import (
    AcknowledgeRequest,
    AckView,
    BriefingView,
    DeltaView,
    ItemActionRequest,
    ItemActionResult,
    PinCreate,
    PinResolution,
    PinResolveRequest,
    PinUpdate,
    PinView,
)
from app.modules.tasks.txn import retry_transient
from app.platform.authz.context import ActorContext
from app.platform.idempotency.service import run_idempotent
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/briefings", tags=["briefings"])
READ = requires("briefings.briefing.read")


def _command(actor: ActorContext, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], BaseModel]) -> dict[str, Any]:
    """One unit of work (idempotent with an ``Idempotency-Key``); item actions lock issue and task rows,
    so a deadlock or serialisation failure re-runs the command (conventions 8)."""

    def attempt() -> tuple[dict[str, Any], bool]:
        with UnitOfWork(actor) as uow:
            return run_idempotent(  # type: ignore[no-any-return]
                uow, key=actor.idempotency_key, operation=operation, body=body, fn=lambda: fn(uow).model_dump(mode="json")
            )

    result, replayed = retry_transient(attempt)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get("/today", openapi_extra=READ)
def get_today(actor: Actor, version: Annotated[int | None, Query(ge=1)] = None) -> BriefingView:
    """Today's briefing. ``version`` keeps the list the client is showing (no re-sorting); the response
    reports ``updates_available`` so the client can offer "N updates"."""
    with UnitOfWork(actor) as uow:
        return service.get_today(uow, version=version)


@router.post("/{briefing_id}/acknowledge", openapi_extra=READ)
def create_acknowledgement(actor: Actor, briefing_id: uuid.UUID, body: AcknowledgeRequest, response: Response) -> AckView:
    return _command(
        actor, response, "briefings.acknowledge", {"briefing_id": str(briefing_id), **body.model_dump(mode="json")},
        lambda uow: service.acknowledge(uow, briefing_id, version=body.version, method=body.method,
                                        channel_message_id=body.channel_message_id),
    )  # type: ignore[return-value]


@router.post("/items/{issue_id}/actions", openapi_extra=READ)
def run_item_action(actor: Actor, issue_id: uuid.UUID, body: ItemActionRequest, response: Response) -> ItemActionResult:
    return _command(
        actor, response, "briefings.item_action", {"issue_id": str(issue_id), **body.model_dump(mode="json")},
        lambda uow: service.run_item_action(uow, issue_id, body),
    )  # type: ignore[return-value]


@router.get("/delta", openapi_extra=READ)
def get_delta(
    actor: Actor,
    since: Annotated[str, Query(max_length=40)] = "yesterday",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> DeltaView:
    """Source-linked "what changed": ``since`` is last_ack, yesterday, last_workday or an ISO instant
    (clamped to the seven-day change window); keyset pages of change rows."""
    with UnitOfWork(actor) as uow:
        return service.get_delta(uow, since=since, limit=limit, cursor=cursor)


@router.post("/{briefing_id}/pins", status_code=201, openapi_extra=READ)
def create_pin(actor: Actor, briefing_id: uuid.UUID, body: PinCreate, response: Response) -> PinView:
    return _command(
        actor, response, "briefings.create_pin", {"briefing_id": str(briefing_id), **body.model_dump(mode="json")},
        lambda uow: service.create_pin(uow, briefing_id, body),
    )  # type: ignore[return-value]


@router.patch("/pins/{pin_id}", openapi_extra=READ)
def update_pin(actor: Actor, pin_id: uuid.UUID, body: PinUpdate) -> PinView:
    with UnitOfWork(actor) as uow:
        return service.update_pin(uow, pin_id, body)


@router.post("/pins/{pin_id}/resolve", openapi_extra=READ)
def resolve_pin_reference(actor: Actor, pin_id: uuid.UUID, body: PinResolveRequest) -> PinResolution:
    with UnitOfWork(actor) as uow:
        return service.resolve_pin(uow, pin_id, body.ordinal)
