"""Collab API: the internal note of any record, authorised through the record's own policy."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.core.http.authz_decl import authenticated
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.platform.collab import service
from app.platform.collab.schemas import NoteRead, NoteUpdate

router = APIRouter(prefix="/collab", tags=["collab"])

RESOURCE_TYPE = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"


@router.get("/notes", openapi_extra=authenticated(), operation_id="collab_get_note")
def get_note(
    actor: Actor,
    resource_type: str = Query(pattern=RESOURCE_TYPE, max_length=80),
    resource_id: uuid.UUID = Query(),
) -> NoteRead:
    return service.get_note(actor, resource_type, resource_id)


@router.put(
    "/notes",
    openapi_extra=authenticated(),
    operation_id="collab_update_note",
    summary="Save the internal note (needs the parent's update right; 409 carries the current note)",
)
def update_note(
    body: NoteUpdate,
    actor: Actor,
    resource_type: str = Query(pattern=RESOURCE_TYPE, max_length=80),
    resource_id: uuid.UUID = Query(),
    idempotency_key: IdempotencyKeyHeader = None,  # optional; read by the actor dependency
) -> NoteRead:
    return service.save_note(actor, resource_type, resource_id, body=body.body, expected_version=body.expected_version)
