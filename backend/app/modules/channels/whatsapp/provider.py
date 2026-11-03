"""The provider seam: every outbound call to WhatsApp goes through a :class:`WhatsAppProvider` (Cloud API in live
mode, the Demo provider otherwise). Providers are stateless over an :class:`AccountConfig`; no transaction is ever
held across a provider call (the sender commits ``sending`` first, calls, then records the outcome)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.core.config import Settings, get_settings
from app.modules.channels.error_codes import Outcome

SendOutcome = Literal["accepted", "retry", "throttle", "failed", "blocked", "unknown"]


@dataclass(frozen=True)
class AccountConfig:
    account_id: Any
    company_id: Any
    mode: str
    phone_number_id: str
    waba_id: str | None
    display_phone: str | None
    api_version: str
    access_token: str = ""


@dataclass(frozen=True)
class SendResult:
    outcome: SendOutcome
    wamid: str | None = None
    http_status: int | None = None
    error_code: int | None = None
    error_title: str | None = None
    retry_after_seconds: int | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class MediaInfo:
    media_id: str
    url: str
    mime_type: str | None
    sha256: str | None
    file_size: int | None


@dataclass(frozen=True)
class TemplateInfo:
    provider_template_id: str | None
    name: str
    language: str
    category: str
    status: str
    components: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CheckOutcome:
    ok: bool
    detail: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class MediaError(Exception):
    """A media fetch that must not be retried blindly (expired URL, oversized, mismatch)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


class WhatsAppProvider(Protocol):
    name: str

    def send(self, account: AccountConfig, to: str, body: dict[str, Any], *, biz_opaque: str) -> SendResult: ...

    def get_media(self, account: AccountConfig, media_id: str) -> MediaInfo: ...

    def download_media(self, account: AccountConfig, info: MediaInfo, *, max_bytes: int) -> bytes: ...

    def upload_media(self, account: AccountConfig, data: bytes, mime_type: str, filename: str) -> str: ...

    def check_phone_number(self, account: AccountConfig) -> CheckOutcome: ...

    def list_templates(self, account: AccountConfig) -> list[TemplateInfo]: ...


ProviderFactory = Callable[[Settings], WhatsAppProvider]
_override: WhatsAppProvider | None = None


def set_provider_override(provider: WhatsAppProvider | None) -> None:
    """Tests install a scripted provider (restored on teardown)."""
    global _override
    _override = provider


def get_provider(settings: Settings | None = None) -> WhatsAppProvider:
    if _override is not None:
        return _override
    settings = settings or get_settings()
    if settings.whatsapp_mode == "live":
        from app.modules.channels.whatsapp.cloud_api import CloudApiProvider

        return CloudApiProvider()
    from app.modules.channels.whatsapp.demo_provider import DemoProvider

    return DemoProvider()


def outcome_from(outcome: Outcome) -> SendOutcome:
    return outcome


__all__ = [
    "AccountConfig", "CheckOutcome", "MediaError", "MediaInfo", "SendOutcome", "SendResult", "TemplateInfo", "WhatsAppProvider",
    "get_provider", "outcome_from", "set_provider_override",
]
