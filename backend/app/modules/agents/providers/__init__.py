"""AI providers behind one provider-neutral interface (``base.py``).

``get_provider`` is the single switch: ``LK_AI_MODE=demo`` (default, no keys) returns the deterministic Demo
orchestrator; ``live`` returns the Anthropic adapter (``providers/anthropic.py``) and fails visibly with
``not_configured`` when ``ANTHROPIC_API_KEY`` is missing — never a silent fallback to Demo (ai-routing.md section 1,
rule 5). The integration registry entry ``ai.anthropic`` gets its verification routine here (``register``).
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.errors import NotConfigured
from app.modules.agents.providers.base import Provider, ProviderError
from app.modules.agents.providers.demo import DemoProvider

LIVE_ADAPTER_MODULE = "app.modules.agents.providers.anthropic"


def ai_mode() -> str:
    return get_settings().ai_mode


def key_missing() -> bool:
    return not get_settings().anthropic_api_key.get_secret_value()


def readiness() -> str:
    """``ok`` (demo, or live with a key) or ``misconfigured`` (live without a key); never a readiness failure."""
    return "misconfigured" if ai_mode() == "live" and key_missing() else "ok"


def check_configured() -> None:
    """Raise ``NotConfigured`` (409) when live mode is selected without a key."""
    if ai_mode() == "live" and key_missing():
        raise NotConfigured(
            "AI live mode is selected but ANTHROPIC_API_KEY is not configured; set the key on the server or "
            "switch LK_AI_MODE to demo.",
            integration="anthropic",
            mode="live",
        )


def get_provider(task_class: str = "orchestration") -> Provider:  # noqa: ARG001 - one adapter serves every class
    check_configured()
    if ai_mode() == "live":
        from app.modules.agents.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    return DemoProvider()


def provider_label() -> str:
    if ai_mode() == "live":
        from app.modules.agents.providers.anthropic import PROVIDER_LABEL

        return PROVIDER_LABEL
    from app.modules.agents.providers.demo import PROVIDER_LABEL as DEMO_LABEL

    return DEMO_LABEL


def verify_integration(uow: Any) -> Any:
    """Verification routine for ``ai.anthropic``: deterministic in demo, a minimal real call in live."""
    from app.platform.system.integrations import VerificationResult

    if ai_mode() != "live":
        return VerificationResult(ok=True, details={"mode": "demo", "provider": "demo", "checked_at": uow.now().isoformat()})
    if key_missing():
        return VerificationResult(ok=False, error_code="secret_missing", details={"missing": ["ANTHROPIC_API_KEY"]})
    try:
        from app.modules.agents.providers.anthropic import AnthropicProvider

        details = AnthropicProvider().verify()
    except ProviderError as exc:
        return VerificationResult(ok=False, error_code=exc.code, details={"request_id": exc.request_id})
    return VerificationResult(ok=True, details={"mode": "live", **details})


def register() -> None:
    """Attach the verification routine to the ``ai.anthropic`` integration definition (manifest ``on_load``)."""
    from app.platform.system.integrations import IntegrationDef, integration_def, register_integration

    current = integration_def("ai.anthropic")
    if current is None or current.verify is verify_integration:
        return
    register_integration(IntegrationDef(
        key=current.key, label=current.label, configured_mode=current.configured_mode,
        missing_secrets=current.missing_secrets, verify=verify_integration,
    ))


__all__ = [
    "LIVE_ADAPTER_MODULE",
    "ai_mode",
    "check_configured",
    "get_provider",
    "key_missing",
    "provider_label",
    "readiness",
    "register",
    "verify_integration",
]
