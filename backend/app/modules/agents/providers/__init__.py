"""AI providers behind one provider-neutral interface (``base.py``).

Slice 1 ships only the deterministic Demo orchestrator. ``get_provider`` is the single switch: ``LK_AI_MODE=demo``
(default, no keys) returns the Demo provider; ``live`` needs a configured key *and* the Slice-3 Anthropic adapter
(``agents/providers/anthropic.py``), and fails visibly with ``not_configured`` until both exist — never a silent
fallback to Demo (ai-routing.md section 1, rule 5).
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.errors import NotConfigured
from app.modules.agents.providers.base import Provider
from app.modules.agents.providers.demo import DemoProvider

LIVE_ADAPTER_MODULE = "app.modules.agents.providers.anthropic"


def ai_mode() -> str:
    return get_settings().ai_mode


def check_configured() -> None:
    """Raise ``NotConfigured`` (409) when live mode is selected without a usable adapter."""
    settings = get_settings()
    if settings.ai_mode != "live":
        return
    if not settings.anthropic_api_key.get_secret_value():
        raise NotConfigured(
            "AI live mode is selected but ANTHROPIC_API_KEY is not configured; set the key on the server or "
            "switch LK_AI_MODE to demo.",
            integration="anthropic",
            mode="live",
        )
    raise NotConfigured(
        "AI live mode is selected but the live adapter ships in Slice 3; switch LK_AI_MODE to demo.",
        integration="anthropic",
        mode="live",
    )


def get_provider() -> Provider:
    check_configured()
    return DemoProvider()
