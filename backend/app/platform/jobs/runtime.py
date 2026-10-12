"""Job execution: claim with SKIP LOCKED, run in its own unit of work, fenced completion.

The handler's effects and the ``succeeded`` status commit in one transaction guarded by the lease
(``WHERE locked_by = me AND status = 'running'``); if the lease was lost the whole transaction rolls
back, so database side effects happen exactly once. Retryable failures back off exponentially;
permanent failures (validation, authorization, not-found) fail immediately.
"""

from __future__ import annotations

import random
import socket
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.db.engine import session_factory
from app.core.errors import AppError, PermanentJobError
from app.core.logging import get_logger
from app.platform.authz.context import ActorContext
from app.platform.jobs.models import Job

log = get_logger("lk.jobs")

#: pluggable: identity registers a builder that rebuilds a user's context for run_as="user" jobs
ActorBuilder = Callable[[Session, Job], ActorContext]
_actor_builder: ActorBuilder | None = None


def register_actor_builder(builder: ActorBuilder) -> None:
    global _actor_builder
    _actor_builder = builder


class LeaseLost(Exception):
    pass


class JobCancelled(Exception):
    pass


@dataclass
class JobContext:
    job_id: uuid.UUID
    kind: str
    attempt: int
    worker_id: str
    uow: Any  # UnitOfWork

    def check_cancelled(self) -> None:
        cancelled = self.uow.session.execute(
            text("SELECT cancel_requested_at IS NOT NULL FROM job WHERE id = :id"), {"id": self.job_id}
        ).scalar()
        if cancelled:
            raise JobCancelled()

    def heartbeat(self, lease_seconds: int = 300) -> None:
        with session_factory()() as s, s.begin():
            s.execute(
                text(
                    "UPDATE job SET heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => :l) "
                    "WHERE id = :id AND locked_by = :w AND status = 'running'"
                ),
                {"id": self.job_id, "w": self.worker_id, "l": lease_seconds},
            )


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


def claim(session: Session, worker_id: str, queues: list[str], limit: int = 1, lease_seconds: int = 300) -> list[Job]:
    rows = session.execute(
        text(
            """
            UPDATE job SET status = 'running', locked_by = :w, locked_at = now(),
                   lease_expires_at = now() + make_interval(secs => :lease), attempts = attempts + 1,
                   started_at = now(), heartbeat_at = now()
            WHERE id IN (
                SELECT id FROM job
                WHERE status = 'queued' AND run_at <= now() AND queue = ANY(:q)
                ORDER BY priority DESC, run_at, id
                LIMIT :n FOR UPDATE SKIP LOCKED)
            RETURNING id
            """
        ),
        {"w": worker_id, "lease": lease_seconds, "q": queues, "n": limit},
    ).all()
    ids = [r[0] for r in rows]
    if not ids:
        return []
    return list(session.scalars(select(Job).where(Job.id.in_(ids)).order_by(Job.priority.desc(), Job.run_at)))


def _backoff(attempt: int) -> timedelta:
    base = min(10 * (2 ** max(attempt - 1, 0)), 3600)
    return timedelta(seconds=base * random.uniform(0.8, 1.2))  # noqa: S311 - jitter, not security


def _build_actor(session: Session, job: Job) -> ActorContext:
    from app.registry import get_registry

    job_def = get_registry().jobs[job.kind]
    if job_def.run_as == "user" and job.actor_user_id is not None:
        if _actor_builder is None:
            raise PermanentJobError("no actor builder registered for user jobs")
        return _actor_builder(session, job)
    return ActorContext.system(job.company_id, reason=job.kind, correlation_id=job.correlation_id)


def execute(job: Job, worker_id: str) -> str:
    """Run one claimed job; returns the final status."""
    from app.platform.uow import UnitOfWork
    from app.registry import get_registry

    registry = get_registry()
    job_def = registry.jobs.get(job.kind)
    if job_def is None:
        _finish_failure(job, worker_id, PermanentJobError(f"unknown job kind {job.kind}"), permanent=True)
        return "failed"
    try:
        with session_factory()() as probe:
            actor = _build_actor(probe, job)
        with UnitOfWork(actor) as uow:
            ctx = JobContext(job_id=job.id, kind=job.kind, attempt=job.attempts, worker_id=worker_id, uow=uow)
            result = job_def.handler(ctx, dict(job.payload or {}))
            fenced = uow.session.execute(
                update(Job)
                .where(Job.id == job.id, Job.locked_by == worker_id, Job.status == "running")
                .values(status="succeeded", finished_at=get_clock().now(), result=result, lease_expires_at=None)
            )
            if fenced.rowcount != 1:  # type: ignore[attr-defined]
                raise LeaseLost()
        return "succeeded"
    except LeaseLost:
        log.warning("job.lease_lost", job_id=str(job.id), kind=job.kind)
        return "lease_lost"
    except JobCancelled:
        _set_status(job, worker_id, "cancelled")
        return "cancelled"
    except (PermanentJobError, AppError) as exc:
        _finish_failure(job, worker_id, exc, permanent=True)
        return "failed"
    except Exception as exc:  # retryable by default
        return _finish_failure(job, worker_id, exc, permanent=False)


def _set_status(job: Job, worker_id: str, status: str) -> None:
    with session_factory()() as s, s.begin():
        s.execute(
            update(Job)
            .where(Job.id == job.id, Job.locked_by == worker_id)
            .values(status=status, finished_at=get_clock().now(), lease_expires_at=None)
        )


def _finish_failure(job: Job, worker_id: str, exc: BaseException, *, permanent: bool) -> str:
    error = {
        "type": type(exc).__name__,
        "message": str(exc)[:500],
        "code": getattr(exc, "code", None),
        "trace": traceback.format_exception_only(type(exc), exc)[-1][:500],
        "at": get_clock().now().isoformat(),
    }
    history = list(job.error_history or [])[-4:] + [error]
    now: datetime = get_clock().now()
    if permanent:
        status, run_at = "failed", job.run_at
    elif job.attempts >= job.max_attempts:
        status, run_at = "dead", job.run_at
    else:  # infrastructure time: backoff is relative to the database clock, like claiming
        delay = _backoff(job.attempts).total_seconds()
        status, run_at = "queued", text(f"now() + make_interval(secs => {delay:.3f})")
    with session_factory()() as s, s.begin():
        s.execute(
            update(Job)
            .where(Job.id == job.id, Job.locked_by == worker_id)
            .values(
                status=status,
                run_at=run_at,
                last_error=error,
                error_history=history,
                locked_by=None if status == "queued" else worker_id,
                lease_expires_at=None,
                finished_at=None if status == "queued" else now,
            )
        )
    log.warning("job.failed", job_id=str(job.id), kind=job.kind, status=status, error=error["message"])
    return status


def reap_expired_leases(session: Session) -> int:
    result = session.execute(
        text(
            "UPDATE job SET status = 'queued', locked_by = NULL, lease_expires_at = NULL "
            "WHERE status = 'running' AND lease_expires_at < now()"
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def cancel(session: Session, job_id: uuid.UUID, by_user: uuid.UUID | None) -> str:
    row = session.execute(
        text(
            "UPDATE job SET status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END, "
            "cancel_requested_at = now(), cancelled_by = :u, "
            "finished_at = CASE WHEN status = 'queued' THEN now() ELSE finished_at END "
            "WHERE id = :id AND status IN ('queued','running') RETURNING status"
        ),
        {"id": job_id, "u": by_user},
    ).first()
    return row[0] if row else "not_cancellable"
