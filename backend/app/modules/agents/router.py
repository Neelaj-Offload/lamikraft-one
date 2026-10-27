"""Agents API (api-conventions.md section 12): create/get conversations, post turns (202 + run id), poll runs, cancel.

operationIds: ``agents_create_conversation``, ``agents_get_conversation``, ``agents_create_turn``, ``agents_get_run``,
``agents_cancel_run``; every route requires ``agents.assistant.use``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.agents import service
from app.modules.agents.policies import ASSISTANT_USE
from app.modules.agents.schemas import (
    ConversationCreate,
    ConversationOut,
    RunDetail,
    RunSummary,
    TurnAccepted,
    TurnCreate,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/conversations", status_code=201, openapi_extra=requires(ASSISTANT_USE))
def create_conversation(actor: Actor, body: ConversationCreate) -> ConversationOut:
    with UnitOfWork(actor) as uow:
        conversation = service.create_conversation(uow, body)
        return service.get_conversation(uow, conversation.id)


@router.get("/conversations/{conversation_id}", openapi_extra=requires(ASSISTANT_USE))
def get_conversation(actor: Actor, conversation_id: uuid.UUID) -> ConversationOut:
    with UnitOfWork(actor) as uow:
        return service.get_conversation(uow, conversation_id)


@router.post("/conversations/{conversation_id}/turns", status_code=202, openapi_extra=requires(ASSISTANT_USE))
def create_turn(actor: Actor, conversation_id: uuid.UUID, body: TurnCreate, response: Response) -> TurnAccepted:
    with UnitOfWork(actor) as uow:
        accepted = service.create_turn(uow, conversation_id, body)
    response.headers["Location"] = f"/api/v1/agents/runs/{accepted.run_id}"
    return accepted


@router.get("/runs/{run_id}", openapi_extra=requires(ASSISTANT_USE))
def get_run(actor: Actor, run_id: uuid.UUID, after_seq: int = Query(default=0, ge=0)) -> RunDetail:
    with UnitOfWork(actor) as uow:
        return service.get_run(uow, run_id, after_seq=after_seq)


@router.post("/runs/{run_id}/cancel", openapi_extra=requires(ASSISTANT_USE))
def cancel_run(actor: Actor, run_id: uuid.UUID) -> RunSummary:
    with UnitOfWork(actor) as uow:
        run = service.cancel_run(uow, run_id)
        return service.run_summary(run)
