"""The integration registry (ADR-040): one definition per external integration.

The mode comes from configuration (``demo`` = a labelled local stand-in, ``live`` = the real provider).
The state is ``not_connected`` until a verification routine succeeds; ``connected`` is never set by
configuration or by an API call. Live mode with a missing server-side secret is reported as ``error``
(``secret_missing``) so it fails visibly. Adapters attach their verification routine in a later slice with
``register_integration`` (Slice 3: AI and WhatsApp; Slice 2: S3; Slice 5: accounting).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.platform.system.models import IntegrationMode

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    error_code: str | None = None
    #: sanitised, non-secret facts (account display name, API version); never tokens or keys
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationDef:
    key: str
    label: str
    configured_mode: Callable[[Settings], IntegrationMode]
    #: names of the server-side secrets live mode needs that are not configured
    missing_secrets: Callable[[Settings], list[str]] = lambda _s: []
    #: the verification routine; None until the live adapter exists
    verify: Callable[[UnitOfWork], VerificationResult] | None = None


def _mode(value: str, live_values: tuple[str, ...] = ("live",)) -> IntegrationMode:
    return IntegrationMode.LIVE if value in live_values else IntegrationMode.DEMO


def _missing(*pairs: tuple[str, Any]) -> Callable[[Settings], list[str]]:
    def check(settings: Settings) -> list[str]:
        out = []
        for name, getter in pairs:
            value = getter(settings)
            secret = value.get_secret_value() if hasattr(value, "get_secret_value") else value
            if not secret:
                out.append(name)
        return out

    return check


BUILTIN_INTEGRATIONS: tuple[IntegrationDef, ...] = (
    IntegrationDef(
        key="ai.anthropic",
        label="Claude (Anthropic)",
        configured_mode=lambda s: _mode(s.ai_mode),
        missing_secrets=_missing(("ANTHROPIC_API_KEY", lambda s: s.anthropic_api_key)),
    ),
    IntegrationDef(
        key="ai.gemini",
        label="Gemini (Google)",
        configured_mode=lambda s: _mode(s.ai_mode),
        missing_secrets=_missing(("GEMINI_API_KEY", lambda s: s.gemini_api_key)),
    ),
    IntegrationDef(
        key="channels.whatsapp",
        label="WhatsApp",
        configured_mode=lambda s: _mode(s.whatsapp_mode),
    ),
    IntegrationDef(
        key="email",
        label="Email delivery",
        configured_mode=lambda s: _mode(s.email_mode, ("smtp",)),
    ),
    IntegrationDef(
        key="storage",
        label="File storage (S3)",
        configured_mode=lambda s: _mode(s.storage_backend, ("s3",)),
        missing_secrets=lambda s: (
            [n for n, v in (("LK_S3_ENDPOINT_URL", s.s3_endpoint_url), ("LK_S3_BUCKET", s.s3_bucket)) if not v]
            if s.storage_backend == "s3"
            else []
        ),
    ),
    IntegrationDef(
        key="accounting",
        label="Accounting system",
        configured_mode=lambda _s: IntegrationMode.DEMO,  # no live adapter before Slice 5
    ),
)

_DEFS: dict[str, IntegrationDef] = {d.key: d for d in BUILTIN_INTEGRATIONS}


def register_integration(definition: IntegrationDef) -> None:
    """Replace a definition by key (adapters add their verification routine)."""
    _DEFS[definition.key] = definition


def integration_defs() -> list[IntegrationDef]:
    return [_DEFS[k] for k in sorted(_DEFS)]


def integration_def(key: str) -> IntegrationDef | None:
    return _DEFS.get(key)
