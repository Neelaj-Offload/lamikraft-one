"""Voice configuration (prefix ``LK_VOICE_``), read from the environment or the repository-root ``.env``.

The STT/TTS vendor is undecided (BUILD_STATE section 5 decision 5: shortlist Sarvam, Google, Azure), so the Demo
adapters are the default and the vendor adapter reports ``not_configured``. The browser fallback (Web Speech API in
the person's browser) is labelled "Browser fallback" and off by default; production readiness fails when it is the
only speech-to-text path.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import REPO_ROOT


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LK_VOICE_",
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: ``demo`` (fixture hash -> transcript), ``vendor`` (pending the owner's choice), ``none``
    stt_provider: Literal["demo", "vendor", "none"] = "demo"
    tts_provider: Literal["demo", "vendor", "none"] = "demo"
    #: the browser's own speech recognition / synthesis, labelled "Browser fallback"; off by default
    browser_fallback: bool = False
    #: the chosen vendor's name and key once decided (never sent to the web)
    vendor_name: str = ""
    vendor_api_key: SecretStr = SecretStr("")


@lru_cache(maxsize=1)
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()


__all__ = ["VoiceSettings", "get_voice_settings"]
