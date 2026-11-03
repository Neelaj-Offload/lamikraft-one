"""Health endpoints. ``live`` = process up; ``ready`` = DB reachable, migrations at head, worker seen."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.clock import get_clock
from app.core.db.engine import session_factory
from app.core.http.authz_decl import public

router = APIRouter(prefix="/health", tags=["system"])


@router.get("/live", openapi_extra=public("liveness probe"), operation_id="system_get_live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", openapi_extra=public("readiness probe"), operation_id="system_get_ready")
def ready() -> JSONResponse:
    checks: dict[str, Any] = {}
    healthy = True
    try:
        with session_factory()() as s:
            s.execute(text("SELECT 1"))
            checks["database"] = "ok"
            from app.migrations_state import head_matches

            at_head, current, head = head_matches(s)
            checks["migrations"] = "ok" if at_head else f"pending (db={current}, code={head})"
            healthy = healthy and at_head
            beat = s.execute(text("SELECT max(last_beat_at) FROM worker_heartbeat")).scalar()
            if beat is None:
                checks["worker"] = "not_seen"
            elif get_clock().now() - beat > timedelta(seconds=60):
                checks["worker"] = "stale"
            else:
                checks["worker"] = "ok"
    except Exception as exc:  # report, never raise from a probe
        checks["database"] = f"unavailable: {type(exc).__name__}"
        healthy = False
    checks["ai"] = _ai_check()
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503)


def _ai_check() -> str:
    """``demo``, ``ok`` or ``misconfigured`` (live without a key). Informational: live AI without a key fails
    visibly in the assistant and on the integration status, never as a readiness failure (ai-routing.md section 1)."""
    from app.core.config import get_settings
    from app.platform.system.integrations import integration_def

    definition = integration_def("ai.anthropic")
    if definition is None:
        return "not_registered"
    settings = get_settings()
    if definition.configured_mode(settings).value != "live":
        return "demo"
    return "misconfigured" if definition.missing_secrets(settings) else "ok"
