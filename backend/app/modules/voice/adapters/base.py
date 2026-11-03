"""The STT/TTS adapter interface (design section 14). Adapters are synchronous and stateless; the voice service
calls them outside any database transaction and records the outcome afterwards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

AdapterStatus = Literal["demo", "configured", "not_configured", "browser", "off"]


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str
    confidence: float | None
    segments: tuple[Segment, ...] = field(default_factory=tuple)
    #: the Demo adapter did not recognise the recording and returned its scripted phrase (labelled in the UI)
    simulated: bool = False


@dataclass(frozen=True)
class Speech:
    audio: bytes
    mime_type: str
    duration_ms: int


class AdapterUnavailable(Exception):
    def __init__(self, message: str, *, code: str = "voice_unavailable") -> None:
        super().__init__(message)
        self.code = code


class STTAdapter(Protocol):
    name: str
    label: str

    def status(self) -> AdapterStatus: ...

    def transcribe(self, audio: bytes, mime_type: str, language: str, sha256: str) -> Transcription: ...


class TTSAdapter(Protocol):
    name: str
    label: str

    def status(self) -> AdapterStatus: ...

    def speak(self, text: str, language: str) -> Speech: ...


__all__ = ["AdapterStatus", "AdapterUnavailable", "STTAdapter", "Segment", "Speech", "TTSAdapter", "Transcription"]
