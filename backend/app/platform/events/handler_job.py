"""The ``event.handle`` job: dispatch one event to one subscribed handler inside the job's UoW."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import PermanentJobError
from app.platform.events.models import DomainEvent
from app.platform.jobs.runtime import JobContext


def handle_event(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.registry import get_registry

    event_id = uuid.UUID(payload["event_id"])
    handler_key = payload["handler"]
    subscription = get_registry().handlers.get(handler_key)
    if subscription is None:
        raise PermanentJobError(f"handler {handler_key} is no longer registered")
    event = ctx.uow.session.scalars(select(DomainEvent).where(DomainEvent.id == event_id)).first()
    if event is None:
        raise PermanentJobError(f"event {event_id} not found")
    subscription.handler(ctx.uow, event)
    return {"event_type": event.event_type, "handler": handler_key}
