"""Event emission, outbox relay and exactly-once consumption."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.platform.events.models import DomainEvent, EventConsumption

_ORIGIN = {"user": "user", "agent": "agent", "system": "system", "integration": "channel", "cli": "system"}

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


def emit(
    uow: UnitOfWork,
    event_name: str,
    *,
    aggregate_id: uuid.UUID | None,
    payload: BaseModel | dict[str, Any] | None = None,
    aggregate_version: int | None = None,
    causation_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.registry import get_registry

    definition = get_registry().events.get(event_name)
    if definition is None:
        raise KeyError(f"event {event_name!r} is not registered")
    actor = uow.actor
    data = definition.validate_payload(payload)
    data.setdefault("origin", _ORIGIN.get(actor.actor_type, "system"))
    row = DomainEvent(
        id=uuid.uuid7(),
        company_id=actor.company_id,
        event_type=definition.name,
        event_version=definition.version,
        aggregate_type=definition.aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        payload=data,
        actor_user_id=actor.user_id,
        actor_type=actor.actor_type,
        on_behalf_of=actor.on_behalf_of_user_id,
        correlation_id=actor.correlation_id,
        causation_id=causation_id,
        occurred_at=uow.now(),
    )
    uow.session.add(row)
    return row.id


def relay_batch(session: Session, *, limit: int = 100) -> int:
    """Fan undispatched events out to per-handler ``event.handle`` jobs. Returns events relayed."""
    from app.platform.jobs.models import Job
    from app.registry import get_registry

    registry = get_registry()
    rows = list(
        session.scalars(
            select(DomainEvent)
            .where(DomainEvent.dispatched_at.is_(None))
            .order_by(DomainEvent.seq)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not rows:
        return 0
    from app.core.clock import get_clock

    now = get_clock().now()
    for evt in rows:
        for sub in registry.subscriptions.get(evt.event_type, []):
            session.execute(
                pg_insert(Job)
                .values(
                    id=uuid.uuid7(),
                    company_id=evt.company_id,
                    queue=sub.queue,
                    kind="event.handle",
                    payload={"event_id": str(evt.id), "handler": sub.handler_key},
                    max_attempts=sub.max_attempts,
                    dedupe_key=f"evt:{evt.id}:{sub.handler_key}",
                    correlation_id=evt.correlation_id,
                    resource_type=evt.aggregate_type,
                    resource_id=evt.aggregate_id,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )
    session.execute(
        update(DomainEvent).where(DomainEvent.id.in_([e.id for e in rows])).values(dispatched_at=now)
    )
    return len(rows)


def once(uow: UnitOfWork, consumer: str, event_id: uuid.UUID) -> bool:
    """Return True the first time ``consumer`` sees ``event_id`` (inside the caller's transaction)."""
    inserted = uow.session.execute(
        pg_insert(EventConsumption)
        .values(consumer=consumer, event_id=event_id)
        .on_conflict_do_nothing()
        .returning(EventConsumption.event_id)
    ).first()
    return inserted is not None
