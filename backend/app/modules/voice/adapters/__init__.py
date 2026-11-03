"""STT/TTS adapters: Demo (default), the browser fallback marker (off by default) and the unimplemented vendor."""

from __future__ import annotations

from app.modules.voice.adapters.base import STTAdapter, TTSAdapter
from app.modules.voice.adapters.browser_marker import BrowserFallbackMarker
from app.modules.voice.adapters.demo import DemoSTT, DemoTTS
from app.modules.voice.adapters.vendor import VendorSTT, VendorTTS
from app.modules.voice.config import get_voice_settings


def stt_adapter() -> STTAdapter | None:
    settings = get_voice_settings()
    if settings.stt_provider == "demo":
        return DemoSTT()
    if settings.stt_provider == "vendor":
        return VendorSTT(settings.vendor_name, settings.vendor_api_key.get_secret_value())
    return None


def tts_adapter() -> TTSAdapter | None:
    settings = get_voice_settings()
    if settings.tts_provider == "demo":
        return DemoTTS()
    if settings.tts_provider == "vendor":
        return VendorTTS(settings.vendor_name, settings.vendor_api_key.get_secret_value())
    return None


def browser_fallback() -> BrowserFallbackMarker:
    return BrowserFallbackMarker(get_voice_settings().browser_fallback)


__all__ = ["browser_fallback", "stt_adapter", "tts_adapter"]
