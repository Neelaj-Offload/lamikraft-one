"""The ``agent.run`` job handler: rebuild the member's context and run the orchestrator as that user.

The job itself runs as the company system actor (it only reads the run row); every business step runs as the
member through ``actor_for_member`` so tools are permission-checked as that user. The handler never raises for
business outcomes: a failed run is recorded on ``agents_run`` and the job succeeds with the outcome.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import NotFound
from app.core.logging import get_logger
from app.modules.agents import service
from app.modules.agents.cards import error_card
from app.modules.agents.models import Run
from app.modules.agents.orchestrator import run_agent
from app.platform.authz.actors import actor_for_member
from app.platform.authz.context import ActorContext, Channel
from app.platform.uow import UnitOfWork

log = get_logger("lk.agents.job")


def _fail(company_id: uuid.UUID, run_id: uuid.UUID, code: str, message: str) -> None:
    with UnitOfWork(ActorContext.system(company_id, reason="agent.run")) as uow:
        run = uow.session.get(Run, run_id)
        if run is None or run.status in ("succeeded", "failed", "budget_exceeded", "cancelled"):
            return
        service.finish_run(
            uow, run, status="failed", text="Demo: the assistant could not run; see the card.",
            cards=[error_card(code, message, provider_label="Demo", tainted=run.tainted)], error_code=code, error_message=message,
        )


def handle_agent_run(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = uuid.UUID(str(payload["run_id"]))
    company_id = ctx.uow.actor.company_id
    run = ctx.uow.session.get(Run, run_id)
    if run is None:
        return {"run_id": str(run_id), "status": "missing"}
    if run.status != "queued":
        return {"run_id": str(run_id), "status": run.status, "skipped": True}
    user_id, channel, correlation_id = run.user_id, run.channel, run.correlation_id
    ctx.uow.session.expunge(run)
    try:
        actor = actor_for_member(company_id, user_id, channel=channel)  # type: ignore[arg-type]
        # the trace id (design section 13): events and audit rows written by the run's steps carry it
        actor = actor.with_(correlation_id=correlation_id) if correlation_id else actor
    except (NotFound, RuntimeError) as exc:
        log.warning("agents.actor_unavailable", run_id=str(run_id), error=str(exc)[:200])
        _fail(company_id, run_id, "actor_unavailable", "The member's context could not be built; the run was not started.")
        return {"run_id": str(run_id), "status": "failed", "error_code": "actor_unavailable"}
    try:
        status = run_agent(actor, run_id)
    except Exception as exc:  # last resort: never leave a run stuck in running
        log.exception("agents.run_crashed", run_id=str(run_id), error_type=type(exc).__name__)
        _fail(company_id, run_id, "internal_error", f"{type(exc).__name__}: {str(exc)[:300]}")
        return {"run_id": str(run_id), "status": "failed", "error_code": "internal_error"}
    return {"run_id": str(run_id), "status": status}


__all__ = ["Channel", "handle_agent_run"]
