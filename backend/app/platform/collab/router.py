"""Collab API: the internal note of any record, authorised through the record's own policy."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import authenticated, requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.platform.collab import activity, attachments, service
from app.platform.collab.schemas import (
    ActivityPage,
    AttachmentCreate,
    AttachmentList,
    AttachmentRead,
    AttachmentRename,
    NoteRead,
    NoteUpdate,
)

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


# ---- attachments (Slice 2) ---------------------------------------------------------------------------------------
@router.get("/attachments", openapi_extra=authenticated(), operation_id="collab_list_attachments", response_model=AttachmentList)
def list_attachments(
    actor: Actor,
    resource_type: str = Query(pattern=RESOURCE_TYPE, max_length=80),
    resource_id: uuid.UUID = Query(),
) -> AttachmentList:
    """Files attached to a record (needs the record's read right; 404 when it is not visible)."""
    return attachments.list_attachments(actor, resource_type, resource_id)


@router.post(
    "/attachments", status_code=201, openapi_extra=authenticated(), operation_id="collab_create_attachment", response_model=AttachmentRead
)
def add_attachment(body: AttachmentCreate, actor: Actor) -> AttachmentRead:
    """Attach an uploaded image or document to a record (needs the record's update right)."""
    return attachments.add_attachment(actor, body.resource_type, body.resource_id, file_id=body.file_id, title=body.title)


@router.patch(
    "/attachments/{attachment_id}", openapi_extra=authenticated(), operation_id="collab_update_attachment", response_model=AttachmentRead
)
def rename_attachment(attachment_id: uuid.UUID, body: AttachmentRename, actor: Actor) -> AttachmentRead:
    return attachments.rename_attachment(actor, attachment_id, title=body.title, expected_version=body.expected_version)


@router.delete(
    "/attachments/{attachment_id}",
    openapi_extra=authenticated(),
    operation_id="collab_delete_attachment",
    status_code=204,
    response_class=Response,
)
def remove_attachment(attachment_id: uuid.UUID, actor: Actor) -> Response:
    """Remove (archive) an attachment; the record's update right is needed."""
    attachments.remove_attachment(actor, attachment_id)
    return Response(status_code=204)


# ---- activity (Slice 2) ------------------------------------------------------------------------------------------
@router.get(
    "/activity", openapi_extra=requires("collab.activity.read"), operation_id="collab_list_activity", response_model=ActivityPage
)
def list_activity(
    actor: Actor,
    resource_type: str | None = Query(default=None, pattern=RESOURCE_TYPE, max_length=80),
    resource_id: uuid.UUID | None = None,
    before: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
) -> ActivityPage:
    """A record's timeline, or the company feed: only records the caller may read contribute."""
    return activity.list_activity(actor, resource_type=resource_type, resource_id=resource_id, before=before, limit=limit)
