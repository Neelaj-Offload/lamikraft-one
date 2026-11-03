"""Agents API (api-conventions.md section 12): create/get conversations, post turns (202 + run id), poll runs, cancel.

operationIds: ``agents_create_conversation``, ``agents_get_conversation``, ``agents_create_turn``, ``agents_get_run``,
``agents_cancel_run``; every route requires ``agents.assistant.use``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import StreamingResponse

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.agents import admin, receipts, service, streaming, trace
from app.modules.agents.policies import AI_USAGE_READ, ASSISTANT_USE, INTEGRATION_MANAGE
from app.modules.agents.schemas import (
    AiStatusOut,
    AiUsageOut,
    AiVerifyOut,
    ConversationCreate,
    ConversationOut,
    ReceiptOut,
    RunDetail,
    RunSummary,
    TraceOut,
    TurnAccepted,
    TurnCreate,
    UndoResult,
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


@router.get(
    "/runs/{run_id}/events", openapi_extra=requires(ASSISTANT_USE), response_class=StreamingResponse,
    responses={200: {"content": {streaming.MEDIA_TYPE: {"schema": {"type": "string"}}},
                     "description": "Server-Sent Events: `run` per change, a final `done` with the RunDetail"}},
)
def stream_run_events(
    actor: Actor, run_id: uuid.UUID, after_seq: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """ADR-050: run progress as SSE; the polling endpoint stays the fallback."""
    streaming.check_access(actor, run_id)
    return StreamingResponse(
        streaming.run_events(actor, run_id, after_seq=streaming.resume_seq(after_seq, last_event_id)),
        media_type=streaming.MEDIA_TYPE, headers=streaming.SSE_HEADERS,
    )


# ---- receipts (design section 9 "Undo") ---------------------------------------------------------------------------
receipts_router = APIRouter(prefix="/receipts", tags=["agents"])


@receipts_router.get("/{receipt_id}", openapi_extra=requires(ASSISTANT_USE), operation_id="agents_get_receipt")
def get_receipt(actor: Actor, receipt_id: uuid.UUID) -> ReceiptOut:
    with UnitOfWork(actor) as uow:
        return receipts.get_receipt(uow, receipt_id)


@receipts_router.post("/{receipt_id}/undo", openapi_extra=requires(ASSISTANT_USE), operation_id="agents_undo_receipt")
def undo_receipt(actor: Actor, receipt_id: uuid.UUID) -> UndoResult:
    with UnitOfWork(actor) as uow:
        return receipts.undo(uow, receipt_id)


# ---- trace (design section 13) ------------------------------------------------------------------------------------
traces_router = APIRouter(prefix="/traces", tags=["agents"])


@traces_router.get("/{correlation_id}", openapi_extra=requires(ASSISTANT_USE), operation_id="agents_get_trace")
def get_trace(actor: Actor, correlation_id: str) -> TraceOut:
    """Participants see their own traces; ``audit.trace.read`` holders see any in the company; else 404."""
    with UnitOfWork(actor) as uow:
        return trace.get_trace(uow, correlation_id)


# ---- AI administration (ai-routing.md sections 7-8) ---------------------------------------------------------------
admin_router = APIRouter(prefix="/admin/ai", tags=["agents"])


@admin_router.get("/status", openapi_extra=requires(AI_USAGE_READ), operation_id="agents_ai_status")
def ai_status(actor: Actor) -> AiStatusOut:
    with UnitOfWork(actor) as uow:
        return admin.get_status(uow)


@admin_router.get("/usage", openapi_extra=requires(AI_USAGE_READ), operation_id="agents_ai_usage")
def ai_usage(actor: Actor, days: int = Query(default=7, ge=1, le=admin.MAX_WINDOW_DAYS)) -> AiUsageOut:
    with UnitOfWork(actor) as uow:
        return admin.get_usage(uow, days=days)


@admin_router.post("/verify", openapi_extra=requires(INTEGRATION_MANAGE), operation_id="agents_ai_verify")
def ai_verify(actor: Actor) -> AiVerifyOut:
    with UnitOfWork(actor) as uow:
        return admin.verify(uow)
