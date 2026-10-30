"""Collab API models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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
