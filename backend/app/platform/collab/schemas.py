"""Collab API models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.http.capabilities import Capability
from app.platform.collab.models import NOTE_MAX_CHARS


class NoteRead(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    #: null until the first save
    note_id: uuid.UUID | None
    body: str
    #: 0 until the first save; send it back as ``expected_version``
    version: int
    updated_at: datetime | None
    updated_by: uuid.UUID | None
    updated_by_name: str | None
    capabilities: dict[str, Capability]


class NoteUpdate(BaseModel):
    body: str = Field(max_length=NOTE_MAX_CHARS)
    expected_version: int = Field(ge=0)


# ---- attachments and activity (Slice 2) ------------------------------------------------------------------------
class AttachmentRead(BaseModel):
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    file_id: uuid.UUID
    title: str
    role: Literal["general", "document", "image"]
    kind: str
    content_type: str
    size_bytes: int
    #: same-origin, cookie-authenticated (no token in the URL)
    content_url: str
    thumbnail_url: str | None
    created_at: datetime
    created_by_name: str | None
    version: int
    capabilities: dict[str, Capability]


class AttachmentList(BaseModel):
    items: list[AttachmentRead]
    capabilities: dict[str, Capability]


class AttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", max_length=80)
    resource_id: uuid.UUID
    #: from ``POST /api/v1/files?purpose=image|document``
    file_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)


class AttachmentRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)


class ActivityItem(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    event_type: str
    verb: str
    #: e.g. "Quote created" (labels and field names only; never restricted values)
    summary: str
    actor_name: str | None
    actor_type: str
    resource_type: str
    resource_id: uuid.UUID | None
    resource_label: str | None
    path: str | None
    changed_fields: list[str]


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    #: pass as ``before`` for older items; null at the end
    next_cursor: str | None
