"""Speech-to-text seam for voice notes. The voice lane's adapter registers itself through
:func:`register_transcriber` (``on_load``); until then, and in demo mode, the Demo transcriber answers from the
fixture SHA-256 table, so this lane never imports the voice module's files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str = "en-IN"
    confidence: float | None = None
    provider_label: str = "Demo"
    #: the transcriber could not produce usable text (the user gets an honest reply)
    empty: bool = False


class Transcriber(Protocol):
    def __call__(self, data: bytes, mime_type: str | None, sha256: str) -> Transcript: ...


_transcriber: Transcriber | None = None


def register_transcriber(fn: Transcriber | None) -> None:
    global _transcriber
    _transcriber = fn


def demo_transcriber(data: bytes, mime_type: str | None, sha256: str) -> Transcript:
    from app.modules.channels.whatsapp.demo_provider import transcript_for_sha256

    text = transcript_for_sha256(sha256)
    if text is None:
        return Transcript(text="", provider_label="Demo", empty=True)
    if not text:
        return Transcript(text="", provider_label="Demo", confidence=0.1, empty=True)
    language = "hi-IN" if any(w in text.lower() for w in (" ka ", " bana ", " karo")) else "en-IN"
    return Transcript(text=text, language=language, confidence=0.92, provider_label="Demo")


def transcribe(data: bytes, mime_type: str | None, sha256: str) -> Transcript:
    fn: Callable[[bytes, str | None, str], Transcript] = _transcriber or demo_transcriber
    return fn(data, mime_type, sha256)


__all__ = ["Transcriber", "Transcript", "demo_transcriber", "register_transcriber", "transcribe"]
