"""Tasks API: the Inbox, task commands, manual tasks and personal reminders (own only).

Routers never import models; every call goes through ``service`` inside one unit of work. Unsafe
commands honour ``Idempotency-Key`` (stored response replayed with ``Idempotent-Replayed: true``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor
from app.modules.tasks import service
from app.modules.tasks.schemas import (
    InboxCounts,
    InboxPage,
    InboxScope,
    InboxTab,
    ReminderCreate,
    ReminderList,
    ReminderOut,
    ReminderUpdate,
    SnoozeOut,
    SnoozeRequest,
    TaskAssignment,
    TaskCreate,
    TaskDetail,
    TaskTransition,
)
from app.platform.authz.context import ActorContext
from app.platform.idempotency.service import run_idempotent
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/tasks", tags=["tasks"])


def run_command(
    actor: ActorContext, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], BaseModel]
) -> dict[str, Any]:
    """One unit of work; idempotent when the client sent an ``Idempotency-Key``."""
    with UnitOfWork(actor) as uow:
        result, replayed = run_idempotent(
            uow, key=actor.idempotency_key, operation=operation, body=body,
            fn=lambda: fn(uow).model_dump(mode="json"),
        )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


# ---- inbox ----------------------------------------------------------------------------------------
@router.get("/inbox", openapi_extra=requires("tasks.task.read"))
def list_inbox(
    actor: Actor,
    tab: InboxTab = "tasks",
    scope: InboxScope = "mine",
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> InboxPage:
    with UnitOfWork(actor) as uow:
        return service.inbox(uow, tab=tab, scope=scope, cursor=cursor, limit=limit)


@router.get("/inbox/counts", openapi_extra=requires("tasks.task.read"))
def get_inbox_counts(actor: Actor) -> InboxCounts:
    with UnitOfWork(actor) as uow:
        return service.inbox_counts(uow)


# ---- tasks ----------------------------------------------------------------------------------------
@router.post("/tasks", status_code=201, openapi_extra=requires("tasks.task.create"))
def create_task(actor: Actor, body: TaskCreate, response: Response) -> TaskDetail:
    return run_command(actor, response, "tasks.create_task", body.model_dump(mode="json"),
                       lambda uow: service.create_task(uow, body))  # type: ignore[return-value]


@router.get("/tasks/{task_id}", openapi_extra=requires("tasks.task.read"))
def get_task(actor: Actor, task_id: uuid.UUID) -> TaskDetail:
    with UnitOfWork(actor) as uow:
        return service.get_task(uow, task_id)


@router.post("/tasks/{task_id}/transitions", openapi_extra=requires("tasks.task.update", "tasks.task.dismiss"))
def transition_task(actor: Actor, task_id: uuid.UUID, body: TaskTransition, response: Response) -> TaskDetail:
    return run_command(
        actor, response, "tasks.transition_task", {"task_id": str(task_id), **body.model_dump(mode="json")},
        lambda uow: service.transition_task(
            uow, task_id, action=body.action, expected_version=body.expected_version,
            reason_code=body.reason_code, note=body.note,
        ),
    )  # type: ignore[return-value]


@router.put("/tasks/{task_id}/assignee", openapi_extra=requires("tasks.task.assign"))
def update_task_assignee(actor: Actor, task_id: uuid.UUID, body: TaskAssignment, response: Response) -> TaskDetail:
    return run_command(
        actor, response, "tasks.update_task_assignee", {"task_id": str(task_id), **body.model_dump(mode="json")},
        lambda uow: service.assign_task(uow, task_id, assignee_user_id=body.assignee_user_id, expected_version=body.expected_version),
    )  # type: ignore[return-value]


@router.put("/tasks/{task_id}/snooze", openapi_extra=requires("tasks.task.read"))
def update_task_snooze(actor: Actor, task_id: uuid.UUID, body: SnoozeRequest, response: Response) -> SnoozeOut:
    return run_command(
        actor, response, "tasks.update_task_snooze", {"task_id": str(task_id), **body.model_dump(mode="json")},
        lambda uow: service.snooze_task(uow, task_id, body.until),
    )  # type: ignore[return-value]


@router.delete("/tasks/{task_id}/snooze", openapi_extra=requires("tasks.task.read"))
def delete_task_snooze(actor: Actor, task_id: uuid.UUID) -> SnoozeOut:
    with UnitOfWork(actor) as uow:
        return service.unsnooze_task(uow, task_id)


# ---- personal reminders (self-service; others' reminders return 404) ------------------------------
@router.get("/reminders", openapi_extra=authenticated())
def list_reminders(actor: Actor, include_closed: bool = False) -> ReminderList:
    with UnitOfWork(actor) as uow:
        return service.list_reminders(uow, include_closed=include_closed)


@router.post("/reminders", status_code=201, openapi_extra=authenticated())
def create_reminder(actor: Actor, body: ReminderCreate, response: Response) -> ReminderOut:
    return run_command(actor, response, "tasks.create_reminder", body.model_dump(mode="json"),
                       lambda uow: service.create_reminder(uow, body))  # type: ignore[return-value]


@router.get("/reminders/{reminder_id}", openapi_extra=authenticated())
def get_reminder(actor: Actor, reminder_id: uuid.UUID) -> ReminderOut:
    with UnitOfWork(actor) as uow:
        return service.get_reminder(uow, reminder_id)


@router.patch("/reminders/{reminder_id}", openapi_extra=authenticated())
def update_reminder(actor: Actor, reminder_id: uuid.UUID, body: ReminderUpdate, response: Response) -> ReminderOut:
    return run_command(
        actor, response, "tasks.update_reminder", {"reminder_id": str(reminder_id), **body.model_dump(mode="json")},
        lambda uow: service.update_reminder(uow, reminder_id, body),
    )  # type: ignore[return-value]


@router.delete("/reminders/{reminder_id}", openapi_extra=authenticated())
def delete_reminder(actor: Actor, reminder_id: uuid.UUID) -> ReminderOut:
    """Cancels the reminder (kept for the owner's history; never visible to anyone else)."""
    with UnitOfWork(actor) as uow:
        return service.cancel_reminder(uow, reminder_id)
