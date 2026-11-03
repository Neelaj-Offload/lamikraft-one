"""Voice API models (design section 16: ``/voice/transcriptions``, ``/voice/speech``, ``/voice/capabilities``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.agents.schemas import MAX_TURN_TEXT, ScreenContext, TurnAccepted

LanguageCode = Literal["en-IN", "hi-IN", "hinglish"]


class LanguageOption(BaseModel):
    code: LanguageCode
    label: str
    #: hi-IN and Hinglish stay "Untested" until a recorded phrase set passes (BUILD_STATE section 5 #5)
    tested: bool
    status_label: str


class AdapterInfo(BaseModel):
    provider: str
    label: str
    status: Literal["demo", "configured", "not_configured", "browser", "off"]


class VoiceCapabilities(BaseModel):
    #: push-to-talk is offered (an STT path exists: the Demo adapter, a vendor, or the browser fallback)
    available: bool
    stt: AdapterInfo
    tts: AdapterInfo
    browser_fallback: AdapterInfo
    #: TTS replies need ``voice.speech.use``
    can_speak: bool
    languages: list[LanguageOption]
    max_seconds: int
    max_bytes: int
    accepted_types: list[str]
    #: personal preferences (voice section)
    speech_language: LanguageCode
    speak_responses: bool
    read_back_values: bool


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class UtteranceOut(BaseModel):
    id: uuid.UUID
    status: Literal["received", "transcribed", "failed", "submitted"]
    source: Literal["server", "browser"]
    provider_label: str
    text: str
    language: str | None
    confidence: float | None
    segments: list[Segment]
    #: Demo did not know the recording: the text is the scripted Demo phrase, not what was said
    simulated: bool
    untested_language: bool
    duration_ms: int | None
    error_code: str | None
    turn_id: uuid.UUID | None
    run_id: uuid.UUID | None
    corrects_turn_id: uuid.UUID | None
    replayed: bool = False


class BrowserUtteranceCreate(BaseModel):
    """A final transcript produced by the browser fallback (no audio reaches the server)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TURN_TEXT)]
    language: LanguageCode = "en-IN"
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_ms: int | None = Field(default=None, ge=0, le=60_000)
    conversation_id: uuid.UUID | None = None


class UtteranceSubmit(BaseModel):
    """Send the (possibly edited) final transcript as an assistant turn, once. A resend returns the same turn."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TURN_TEXT)]
    context: ScreenContext | None = None
    #: a correction after submission: the user turn it corrects (becomes a new turn, never an edit of the old one)
    corrects_turn_id: uuid.UUID | None = None


class UtteranceSubmitted(BaseModel):
    utterance: UtteranceOut
    turn: TurnAccepted


class SpeechCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
    language: LanguageCode | None = None


class SpeechOut(BaseModel):
    id: uuid.UUID
    #: same-origin, session-authenticated, valid until ``expires_at`` (no token in the URL)
    url: str
    expires_at: datetime
    mime_type: str
    duration_ms: int
    provider_label: str


class ReadbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: Annotated[str, StringConstraints(max_length=80)]
    subject_id: uuid.UUID


class ReadbackOut(BaseModel):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    subject_version: int | None
    text: str
    presented_at: datetime
    expires_at: datetime


__all__ = [
    "AdapterInfo",
    "BrowserUtteranceCreate",
    "LanguageCode",
    "LanguageOption",
    "ReadbackCreate",
    "ReadbackOut",
    "Segment",
    "SpeechCreate",
    "SpeechOut",
    "UtteranceOut",
    "UtteranceSubmit",
    "UtteranceSubmitted",
    "VoiceCapabilities",
]
