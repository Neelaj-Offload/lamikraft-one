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
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503)
