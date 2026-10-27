"""Agents module manifest: models, own-scope policies, the durable ``agent.run`` job and the API."""

from __future__ import annotations

from typing import Any

from app.modules.agents.events import JOB_KIND, JOB_QUEUE
from app.modules.agents.policies import POLICIES
from app.platform.jobs.defs import JobDef
from app.platform.manifest import ModuleManifest


def _router() -> Any:
    from app.modules.agents.router import router

    return router


def _run_job(ctx: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    from app.modules.agents.run_job import handle_agent_run

    return handle_agent_run(ctx, payload)


MANIFEST = ModuleManifest(
    name="agents",
    models=("app.modules.agents.models",),
    policies=list(POLICIES),
    #: one attempt: a run is a business outcome recorded on ``agents_run``; the handler never raises
    jobs=[JobDef(JOB_KIND, _run_job, queue=JOB_QUEUE, max_attempts=1, lease_seconds=120)],
    routers=[_router],
)
