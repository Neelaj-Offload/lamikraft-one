"""Typed payloads for the agent events (docs/architecture/events.md section 3.7) and the ``agent.run`` job kind."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

RUN_COMPLETED = "agents.run.completed"
RUN_FAILED = "agents.run.failed"
JOB_KIND = "agent.run"
JOB_QUEUE = "ai"


class RunCompletedPayload(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    trigger: str
    status: str
    origin: str | None = None


class RunFailedPayload(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    error_code: str
    origin: str | None = None


def payload(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json", exclude_none=True)
