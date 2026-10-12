"""Enqueue jobs inside the caller's transaction (dedupe-key aware)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.jobs.models import Job

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


def enqueue(
    uow: UnitOfWork,
    kind: str,
    payload: dict[str, Any],
    *,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    priority: int = 0,
    queue: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    as_user: bool = False,
) -> uuid.UUID | None:
    from app.registry import get_registry

    job_def = get_registry().jobs.get(kind)
    if job_def is None:
        raise KeyError(f"job kind {kind!r} is not registered")
    actor = uow.actor
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "company_id": actor.company_id,
        "queue": queue or job_def.queue,
        "kind": kind,
        "payload": payload,
        "priority": priority,
        "max_attempts": job_def.max_attempts,
        "dedupe_key": dedupe_key,
        "correlation_id": actor.correlation_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_user_id": actor.user_id if (as_user or job_def.run_as == "user") else None,
        "actor_membership_id": actor.membership_id if (as_user or job_def.run_as == "user") else None,
    }
    if run_at is not None:
        values["run_at"] = run_at  # explicit business-time schedule; otherwise DB now()
    stmt = pg_insert(Job).values(**values)
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    row = uow.session.execute(stmt.returning(Job.id)).first()
    return row[0] if row else None
