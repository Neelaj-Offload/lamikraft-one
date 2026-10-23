"""Briefing subscriptions: ``tasks.*`` facts refresh affected members' current briefings (stage two of the
pipeline; briefings never interpret raw domain events), and access changes regenerate on next open."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.platform.events.defs import Subscription
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

REFRESH_HANDLER = "briefings.refresh"
ACCESS_HANDLER = "briefings.access_refresh"
TASK_EVENTS = (
    "tasks.task.created",
    "tasks.task.assigned",
    "tasks.task.started",
    "tasks.task.completed",
    "tasks.task.dismissed",
    "tasks.task.cancelled",
    "tasks.task.expired",
    "tasks.task.became_overdue",
    "tasks.issue.opened",
    "tasks.issue.changed",
    "tasks.issue.resolved",
    "tasks.reminder.fired",
)
ACCESS_EVENTS = ("identity.membership.access_changed", "identity.permission_override.changed")


def _uuid(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _enqueue(uow: UnitOfWork, event: DomainEvent, users: set[uuid.UUID], cause: str) -> None:
    for user_id in sorted(users):
        uow.enqueue(
            "briefings.refresh_user",
            {"user_id": str(user_id), "cause_event_id": str(event.id), "cause": cause},
            dedupe_key=f"brf:{event.id}:{user_id}",
            resource_type="identity.user",
            resource_id=user_id,
        )


def _refresh(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.modules.briefings import service
    from app.modules.tasks import service as tasks

    payload = event.payload or {}
    if event.event_type == "tasks.reminder.fired":
        user_id = _uuid(payload.get("user_id"))
        _enqueue(uow, event, service.users_with_current_briefing(uow, {user_id} if user_id else set()), "event_update")
        return
    issue_id = _uuid(payload.get("issue_id"))
    if issue_id is None:
        return
    audience = tasks.issue_audience(uow, issue_id) | service.users_showing_issue(uow, issue_id)
    users = service.users_with_current_briefing(uow, audience)  # others compute everything on first open
    if event.event_type == "tasks.task.became_overdue":
        for user_id in tasks.wake_snoozes(uow, issue_id):  # an overdue fact wakes snoozed items
            uow.emit("briefings.item.unsnoozed", aggregate_id=issue_id,
                     payload={"issue_id": str(issue_id), "user_id": str(user_id), "snoozed_until": None})
    _enqueue(uow, event, users, "event_update")


def _access(uow: UnitOfWork, event: DomainEvent) -> None:
    from app.platform.identity.models import Membership

    payload = event.payload or {}
    user_id = _uuid(payload.get("user_id"))
    if user_id is None:
        membership_id = _uuid(payload.get("membership_id"))
        if membership_id is not None:
            user_id = uow.session.scalar(
                select(Membership.user_id).where(Membership.company_id == uow.actor.company_id, Membership.id == membership_id)
            )
    if user_id is not None:
        _enqueue(uow, event, {user_id}, "permission_change")


SUBSCRIPTIONS: list[Subscription] = [
    Subscription(event=name, handler_key=f"{REFRESH_HANDLER}:{name}", handler=_refresh) for name in TASK_EVENTS
] + [Subscription(event=name, handler_key=f"{ACCESS_HANDLER}:{name}", handler=_access) for name in ACCESS_EVENTS]
