"""Voice module manifest: utterance, speech and read-back tables, the API, the 7-day audio purge, the ``voice.stt``
and ``voice.tts`` integration definitions, the readiness check, and the WhatsApp voice-note transcriber."""

from __future__ import annotations

from typing import Any

from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.manifest import ModuleManifest

PURGE_JOB = "voice.audio.purge"


def _router() -> Any:
    from app.modules.voice.router import router

    return router


def _purge(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    from app.modules.tasks.jobs import for_each_company
    from app.modules.voice.service import purge_due

    return for_each_company(ctx, PURGE_JOB, purge_due)


def _verify(kind: str) -> Any:
    def verify(uow: Any) -> Any:
        from app.modules.voice import adapters
        from app.platform.system.integrations import VerificationResult

        adapter = adapters.stt_adapter() if kind == "stt" else adapters.tts_adapter()
        if adapter is None:
            return VerificationResult(ok=False, error_code="off", details={"provider": "none"})
        status = adapter.status()
        if status == "demo":
            return VerificationResult(ok=True, details={"mode": "demo", "provider": "demo", "checked_at": uow.now().isoformat()})
        return VerificationResult(ok=False, error_code=status, details={"provider": adapter.name})

    return verify


def _integration_defs() -> list[Any]:
    from app.modules.voice.config import get_voice_settings
    from app.platform.system.integrations import IntegrationDef
    from app.platform.system.models import IntegrationMode

    def mode(attr: str) -> Any:
        return lambda _s: IntegrationMode.LIVE if getattr(get_voice_settings(), attr) == "vendor" else IntegrationMode.DEMO

    def missing(attr: str) -> Any:
        def check(_s: Any) -> list[str]:
            voice = get_voice_settings()
            if getattr(voice, attr) != "vendor":
                return []
            return [] if voice.vendor_api_key.get_secret_value() else ["LK_VOICE_VENDOR_API_KEY"]

        return check

    return [
        IntegrationDef(key="voice.stt", label="Speech-to-text", configured_mode=mode("stt_provider"),
                       missing_secrets=missing("stt_provider"), verify=_verify("stt")),
        IntegrationDef(key="voice.tts", label="Spoken replies", configured_mode=mode("tts_provider"),
                       missing_secrets=missing("tts_provider"), verify=_verify("tts")),
    ]


def _on_load() -> None:
    from app.modules.voice import service
    from app.platform.system.integrations import integration_def, register_integration
    from app.platform.system.readiness import register_readiness_check

    for definition in _integration_defs():
        if integration_def(definition.key) is None:
            register_integration(definition)
    register_readiness_check("voice", service.readiness)
    try:  # the WhatsApp lane's seam (lane/s3-whatsapp); absent until that lane is merged
        from app.modules.channels.whatsapp.stt import register_transcriber  # type: ignore[import-not-found]
    except ImportError:
        return
    register_transcriber(service.whatsapp_transcriber)


MANIFEST = ModuleManifest(
    name="voice",
    models=("app.modules.voice.models",),
    routers=[_router],
    jobs=[JobDef(PURGE_JOB, _purge, queue="default", max_attempts=3)],
    schedules=[ScheduleDef(PURGE_JOB, PURGE_JOB, "interval", interval_seconds=3600)],
    on_load=_on_load,
)
