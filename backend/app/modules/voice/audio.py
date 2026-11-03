"""Audio checks for ``POST /voice/transcriptions`` (design section 14): at most 60 seconds and 10 MB; webm, ogg-opus,
mp4 or wav, decided by magic bytes (never by the declared type or the filename)."""

from __future__ import annotations

import io
import wave
from typing import Literal

from app.core.errors import ValidationFailed
from app.platform.files.errors import UnsupportedMediaType

AudioKind = Literal["webm", "ogg", "mp4", "wav"]
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_MS = 60_000
MIME_TYPES: dict[AudioKind, str] = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4", "wav": "audio/wav"}


def sniff_audio(head: bytes) -> AudioKind:
    """The container from its first bytes: EBML with a ``webm`` doctype, ``OggS`` carrying ``OpusHead``, an ISO BMFF
    ``ftyp`` box, or ``RIFF....WAVE``."""
    if head[:4] == b"\x1a\x45\xdf\xa3" and b"webm" in head[:64]:
        return "webm"
    if head[:4] == b"OggS" and b"OpusHead" in head[:128]:
        return "ogg"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    raise UnsupportedMediaType("The recording must be WebM, Ogg Opus, MP4 or WAV audio.", reason="unsupported_audio")


def wav_duration_ms(data: bytes) -> int:
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            frames, rate = reader.getnframes(), reader.getframerate()
    except (wave.Error, EOFError) as exc:
        raise UnsupportedMediaType("The WAV recording cannot be read.", reason="unsupported_audio") from exc
    return int(frames * 1000 / rate) if rate else 0


def check_audio(data: bytes, *, declared_duration_ms: int | None) -> tuple[AudioKind, int]:
    """Kind and duration. WAV durations are measured; compressed containers use the recorder's duration (the
    client stops at 60 s) and are bounded by the 10 MB cap."""
    if len(data) > MAX_AUDIO_BYTES:
        raise ValidationFailed("The recording is larger than 10 MB.", code="audio_too_large")
    if not data:
        raise ValidationFailed("The recording is empty.", code="audio_empty")
    kind = sniff_audio(data[:256])
    duration = wav_duration_ms(data) if kind == "wav" else int(declared_duration_ms or 0)
    if duration > MAX_AUDIO_MS:
        raise ValidationFailed("The recording is longer than 60 seconds.", code="audio_too_long")
    return kind, duration


__all__ = ["MAX_AUDIO_BYTES", "MAX_AUDIO_MS", "MIME_TYPES", "AudioKind", "check_audio", "sniff_audio", "wav_duration_ms"]
