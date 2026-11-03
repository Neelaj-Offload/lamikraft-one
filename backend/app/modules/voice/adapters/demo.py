"""Demo STT/TTS (no vendor, no network), labelled "Demo".

STT maps the SHA-256 of a fixture recording to its transcript (``voice/fixtures``). A recording it does not know
(a real microphone, Chromium's fake device) gets the scripted Demo phrase with ``simulated=True`` and confidence 0,
so the UI can say "Demo transcript — not from your recording" and the person edits it before sending. Nothing is
ever presented as recognised speech when it was not.

TTS returns a silent 8 kHz mono WAV whose length follows the text (1–8 s), so playback, interruption and Stop can be
exercised end to end without a vendor.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

from app.modules.voice.adapters.base import AdapterStatus, Segment, Speech, Transcription

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_PHRASE = "Prepare Nordhaus's usual oak tray quote"

#: sha256 -> (transcript, language, confidence); Hinglish is labelled untested everywhere it appears
FIXTURES: dict[str, tuple[str, str, float]] = {
    "cb8fbf45dfe1b79545bf7b0afe96c61a6a7a0c56183a8afa886cf0245f03fb2f": (DEMO_PHRASE, "en-IN", 0.94),
    "1b1c985cff213d1128df8ee2da52c824d81ba58b29c1c3b78aa49000290abf73": (
        "Nordhaus ka usual oak tray quote bana do", "hinglish", 0.81,
    ),
    "e758b742859e6801d835e47550e2d47ed29e5a9e9ae8dec0d743c7047b601c9c": ("change it to 300", "en-IN", 0.93),
}
FIXTURE_FILES = {
    "usual_oak_tray": FIXTURE_DIR / "demo-usual-oak-tray.wav",
    "hinglish_usual_oak_tray": FIXTURE_DIR / "demo-hinglish-usual-oak-tray.wav",
    "change_to_300": FIXTURE_DIR / "demo-change-to-300.wav",
}


def _segments(text: str) -> tuple[Segment, ...]:
    """One deterministic segment per word, 300 ms each (enough to drive the transcript view)."""
    return tuple(Segment(start_ms=i * 300, end_ms=(i + 1) * 300, text=word) for i, word in enumerate(text.split()))


class DemoSTT:
    name = "demo"
    label = "Demo"

    def status(self) -> AdapterStatus:
        return "demo"

    def transcribe(self, audio: bytes, mime_type: str, language: str, sha256: str) -> Transcription:  # noqa: ARG002
        known = FIXTURES.get(sha256)
        if known is not None:
            text, lang, confidence = known
            return Transcription(text=text, language=lang, confidence=confidence, segments=_segments(text))
        return Transcription(text=DEMO_PHRASE, language="en-IN", confidence=0.0, segments=_segments(DEMO_PHRASE),
                             simulated=True)


class DemoTTS:
    name = "demo"
    label = "Demo"

    def status(self) -> AdapterStatus:
        return "demo"

    def speak(self, text: str, language: str) -> Speech:  # noqa: ARG002
        words = max(1, len(text.split()))
        duration_ms = max(1_000, min(8_000, words * 300))
        rate = 8_000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(b"\x00\x00" * (rate * duration_ms // 1000))
        return Speech(audio=buffer.getvalue(), mime_type="audio/wav", duration_ms=duration_ms)


__all__ = ["DEMO_PHRASE", "FIXTURES", "FIXTURE_FILES", "DemoSTT", "DemoTTS"]
