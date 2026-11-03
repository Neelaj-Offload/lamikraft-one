"""Voice API (``/api/v1/voice``, design section 16).

operationIds: ``voice_get_capabilities``, ``voice_create_transcription``, ``voice_create_utterance`` (browser
fallback), ``voice_get_utterance``, ``voice_create_utterance_submission``, ``voice_create_speech``,
``voice_download_speech_audio``, ``voice_create_readback``. Transcriptions, utterances and read-backs require
``agents.assistant.use`` (voice is an input to the assistant); spoken replies require ``voice.speech.use``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.voice import service
from app.modules.voice.audio import MAX_AUDIO_BYTES
from app.modules.voice.schemas import (
    BrowserUtteranceCreate,
    LanguageCode,
    ReadbackCreate,
    ReadbackOut,
    SpeechCreate,
    SpeechOut,
    UtteranceOut,
    UtteranceSubmit,
    UtteranceSubmitted,
    VoiceCapabilities,
)
from app.platform.files.storage import staging_dir
from app.platform.files.upload import receive_upload
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/voice", tags=["voice"])
ASSISTANT_USE = service.ASSISTANT_USE
SPEECH_USE = service.SPEECH_USE

_AUDIO_BODY = {
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
def get_capabilities(actor: Actor) -> VoiceCapabilities:
    with UnitOfWork(actor) as uow:
        return service.capabilities(uow)


@router.post(
    "/transcriptions", openapi_extra={**requires(ASSISTANT_USE), **_AUDIO_BODY},
    summary="Transcribe one recording (at most 60 s and 10 MB; webm, ogg-opus, mp4 or wav by magic bytes)",
    responses={409: {"description": "not_configured"}, 413: {"description": "payload_too_large"},
               415: {"description": "unsupported_media_type"}},
)
def create_transcription(
    request: Request,
    actor: Actor,
    utterance_id: Annotated[uuid.UUID, Query()],
    conversation_id: Annotated[uuid.UUID | None, Query()] = None,
    language: Annotated[LanguageCode, Query()] = "en-IN",
    duration_ms: Annotated[int | None, Query(ge=0, le=600_000)] = None,
) -> UtteranceOut:
    actor.require(ASSISTANT_USE)
    received = receive_upload(request, max_bytes=MAX_AUDIO_BYTES, staging=staging_dir())
    try:
        return service.transcribe_upload(
            actor, utterance_id=utterance_id, path=received.path, sha256=received.sha256, size=received.size,
            declared_duration_ms=duration_ms, conversation_id=conversation_id, language=language,
        )
    finally:
        received.discard()


@router.post("/utterances", status_code=201, openapi_extra=requires(ASSISTANT_USE))
def create_utterance(actor: Actor, body: BrowserUtteranceCreate) -> UtteranceOut:
    with UnitOfWork(actor) as uow:
        return service.create_browser_utterance(uow, body)


@router.get("/utterances/{utterance_id}", openapi_extra=requires(ASSISTANT_USE))
def get_utterance(actor: Actor, utterance_id: uuid.UUID) -> UtteranceOut:
    with UnitOfWork(actor) as uow:
        return service.get_utterance(uow, utterance_id)


@router.post("/utterances/{utterance_id}/submit", status_code=202, openapi_extra=requires(ASSISTANT_USE))
def create_utterance_submission(actor: Actor, utterance_id: uuid.UUID, body: UtteranceSubmit, response: Response) -> UtteranceSubmitted:
    with UnitOfWork(actor) as uow:
        submitted = service.submit_utterance(uow, utterance_id, body)
    response.headers["Location"] = f"/api/v1/agents/runs/{submitted.turn.run_id}"
    return submitted


@router.post("/speech", status_code=201, openapi_extra=requires(SPEECH_USE))
def create_speech(actor: Actor, body: SpeechCreate) -> SpeechOut:
    return service.speak(actor, body)


@router.get(
    "/speech/{speech_id}/audio", openapi_extra=requires(SPEECH_USE), response_class=Response,
    responses={200: {"content": {"audio/wav": {}}, "description": "the synthesised reply (valid for 5 minutes)"}},
)
def download_speech_audio(actor: Actor, speech_id: uuid.UUID) -> Response:
    with UnitOfWork(actor) as uow:
        data, mime = service.speech_audio(uow, speech_id)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store"})


@router.post("/readbacks", status_code=201, openapi_extra=requires(ASSISTANT_USE))
def create_readback(actor: Actor, body: ReadbackCreate) -> ReadbackOut:
    with UnitOfWork(actor) as uow:
        return service.present_readback(uow, body.subject_type, body.subject_id)
