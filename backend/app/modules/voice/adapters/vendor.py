"""The server vendor adapter, intentionally unimplemented until the owner chooses the STT/TTS vendor (BUILD_STATE
section 5 decision 5; shortlist Sarvam, Google, Azure).

It reports ``not_configured`` and every call raises ``AdapterUnavailable(code="not_configured")``: selecting
``LK_VOICE_STT_PROVIDER=vendor`` fails visibly instead of pretending to transcribe. Implementing it means: the
vendor's sync HTTP client with an explicit timeout, the request built from ``(audio, mime_type, language)``,
the response mapped to ``Transcription`` (text, language, confidence, word segments), and a recorded en-IN /
hi-IN / Hinglish phrase set before the "Untested" labels are removed.
"""

from __future__ import annotations

from app.modules.voice.adapters.base import AdapterStatus, AdapterUnavailable, Speech, Transcription

NOT_CONFIGURED = "The speech vendor is not chosen yet; voice uses the Demo adapter."


class VendorSTT:
    name = "vendor"
    label = "Speech vendor (not configured)"

    def __init__(self, vendor_name: str = "", api_key: str = "") -> None:
        self.vendor_name = vendor_name
        self.api_key = api_key

    def status(self) -> AdapterStatus:
        return "not_configured"

    def transcribe(self, audio: bytes, mime_type: str, language: str, sha256: str) -> Transcription:  # noqa: ARG002
        raise AdapterUnavailable(NOT_CONFIGURED, code="not_configured")


class VendorTTS:
    name = "vendor"
    label = "Speech vendor (not configured)"

    def __init__(self, vendor_name: str = "", api_key: str = "") -> None:
        self.vendor_name = vendor_name
        self.api_key = api_key

    def status(self) -> AdapterStatus:
        return "not_configured"

    def speak(self, text: str, language: str) -> Speech:  # noqa: ARG002
        raise AdapterUnavailable(NOT_CONFIGURED, code="not_configured")


__all__ = ["NOT_CONFIGURED", "VendorSTT", "VendorTTS"]
