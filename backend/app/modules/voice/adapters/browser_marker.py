"""The browser fallback marker (design section 14): recognition and synthesis happen in the person's browser (Web
Speech API), never on the server. Labelled "Browser fallback", off by default (``LK_VOICE_BROWSER_FALLBACK``).

The server only accepts the browser's final transcript as an utterance (``POST /voice/utterances``); it never sees
audio. Quality, language support and privacy depend on the browser vendor, which is why production readiness fails
when this is the only speech-to-text path.
"""

from __future__ import annotations

from app.modules.voice.adapters.base import AdapterStatus, AdapterUnavailable, Speech, Transcription


class BrowserFallbackMarker:
    name = "browser"
    label = "Browser fallback"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def status(self) -> AdapterStatus:
        return "browser" if self.enabled else "off"

    def transcribe(self, audio: bytes, mime_type: str, language: str, sha256: str) -> Transcription:  # noqa: ARG002
        raise AdapterUnavailable("The browser fallback transcribes in the browser, not on the server.",
                                 code="browser_fallback_client_side")

    def speak(self, text: str, language: str) -> Speech:  # noqa: ARG002
        raise AdapterUnavailable("The browser fallback speaks in the browser, not on the server.",
                                 code="browser_fallback_client_side")


__all__ = ["BrowserFallbackMarker"]
