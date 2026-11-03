"""Vision module manifest: the masked screenshot and extraction tables, the ``screen_capture`` setting, the API,
the 24-hour capture purge job, and the verification routine of the ``ai.gemini`` integration."""

from __future__ import annotations

from typing import Any

from app.modules.vision.schemas import SCREEN_CAPTURE_SETTING
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest

PURGE_JOB = "vision.captures.purge"


def _router() -> Any:
    from app.modules.vision.router import router

    return router


def _purge(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    from app.modules.tasks.jobs import for_each_company
    from app.modules.vision.service import purge_due

    return for_each_company(ctx, PURGE_JOB, purge_due)


def verify_gemini(uow: Any) -> Any:
    """``ai.gemini``: deterministic in demo; in live a minimal classification call (no business data)."""
    from app.core.config import get_settings
    from app.modules.vision.contract import VisionUnavailable
    from app.platform.system.integrations import VerificationResult

    settings = get_settings()
    if settings.ai_mode != "live":
        return VerificationResult(ok=True, details={"mode": "demo", "provider": "demo", "checked_at": uow.now().isoformat()})
    if not settings.gemini_api_key.get_secret_value():
        return VerificationResult(ok=False, error_code="secret_missing", details={"missing": ["GEMINI_API_KEY"]})
    from app.modules.agents.providers.gemini_vision import GeminiVisionProvider
    from app.modules.vision.service import vision_model

    try:
        details = GeminiVisionProvider(api_key=settings.gemini_api_key.get_secret_value(), model=vision_model(uow)).verify()
    except VisionUnavailable as exc:
        return VerificationResult(ok=False, error_code=exc.code, details={"request_id": exc.request_id})
    return VerificationResult(ok=True, details={"mode": "live", **details})


def _on_load() -> None:
    from app.platform.system.integrations import IntegrationDef, integration_def, register_integration

    current = integration_def("ai.gemini")
    if current is None or current.verify is verify_gemini:
        return
    register_integration(IntegrationDef(
        key=current.key, label=current.label, configured_mode=current.configured_mode,
        missing_secrets=current.missing_secrets, verify=verify_gemini,
    ))


MANIFEST = ModuleManifest(
    name="vision",
    models=("app.modules.vision.models",),
    settings=[SCREEN_CAPTURE_SETTING],
    routers=[_router],
    jobs=[JobDef(PURGE_JOB, _purge, queue="default", max_attempts=3)],
    schedules=[ScheduleDef(PURGE_JOB, PURGE_JOB, "interval", interval_seconds=900)],
    on_load=_on_load,
)
