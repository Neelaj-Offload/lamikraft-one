"""Vision API (``/api/v1/vision``): capabilities, masked screen captures, instant screen answers, extractions.

Every route requires ``agents.assistant.use`` (vision is part of the assistant); every resource is the caller's own
(another user's capture or request is a 404). The capture upload streams one multipart part named ``file`` (WebP or
PNG, at most 1.5 MB); its parameters travel in the query string (ids and counts only, never content).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.vision import service
from app.modules.vision.schemas import (
    ExtractionCard,
    ExtractionConfirm,
    ExtractionCreate,
    ScreenAnswerCreate,
    ScreenAnswerOut,
    ScreenCaptureOut,
    VisionCapabilities,
)
from app.platform.files.storage import staging_dir
from app.platform.files.upload import receive_upload
from app.platform.uow import UnitOfWork

ASSISTANT_USE = service.ASSISTANT_USE
router = APIRouter(prefix="/vision", tags=["vision"])

_CAPTURE_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.get("/capabilities", openapi_extra=requires(ASSISTANT_USE))
def get_capabilities(actor: Actor) -> VisionCapabilities:
    with UnitOfWork(actor) as uow:
        return service.capabilities(uow)


@router.post(
    "/screen-captures", status_code=201, openapi_extra={**requires(ASSISTANT_USE), **_CAPTURE_BODY},
    summary="Attach a masked screenshot (WebP/PNG, at most 1.5 MB and 1568 px); deduplicated per conversation",
    responses={403: {"description": "screen_capture_disabled"}, 413: {"description": "payload_too_large"}},
)
def create_screen_capture(
    request: Request,
    actor: Actor,
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
    masked_count: Annotated[int, Query(ge=0, le=10_000)] = 0,
    route_path: Annotated[str | None, Query(max_length=300)] = None,
) -> ScreenCaptureOut:
    actor.require(ASSISTANT_USE)
    received = receive_upload(request, max_bytes=service.MAX_CAPTURE_BYTES, staging=staging_dir())
    try:
        data = received.path.read_bytes()
    finally:
        received.discard()
    with UnitOfWork(actor) as uow:
        return service.store_capture(uow, data, conversation_id=conversation_id, masked_count=masked_count,
                                     route_path=route_path)


@router.delete("/screen-captures/{capture_id}", openapi_extra=requires(ASSISTANT_USE))
def delete_screen_capture(actor: Actor, capture_id: uuid.UUID) -> ScreenCaptureOut:
    with UnitOfWork(actor) as uow:
        return service.remove_capture(uow, capture_id)


@router.post("/screen-answers", openapi_extra=requires(ASSISTANT_USE))
def create_screen_answer(actor: Actor, body: ScreenAnswerCreate) -> ScreenAnswerOut:
    with UnitOfWork(actor) as uow:
        return service.answer_screen(uow, body)


@router.post("/extractions", status_code=201, openapi_extra=requires(ASSISTANT_USE))
def create_extraction(actor: Actor, body: ExtractionCreate) -> ExtractionCard:
    with UnitOfWork(actor) as uow:
        return service.extract(uow, body)


@router.get("/extractions/{request_id}", openapi_extra=requires(ASSISTANT_USE))
def get_extraction(actor: Actor, request_id: uuid.UUID) -> ExtractionCard:
    with UnitOfWork(actor) as uow:
        return service.get_extraction(uow, request_id)


@router.post("/extractions/{request_id}/confirm", openapi_extra=requires(ASSISTANT_USE))
def update_extraction_confirmation(actor: Actor, request_id: uuid.UUID, body: ExtractionConfirm) -> ExtractionCard:
    with UnitOfWork(actor) as uow:
        return service.confirm_extraction(uow, request_id, body)
