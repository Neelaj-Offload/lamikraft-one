"""Audit read API models (keyset pages, api-conventions §9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):  # noqa: UP046 - pydantic generic model, kept explicit
    items: list[T]
    #: opaque base64url cursor of the last row's (occurred_at, id); null on the last page
    next_cursor: str | None
    limit: int


class AuditEntryRead(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    on_behalf_of_user_id: uuid.UUID | None
    channel: str | None
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    resource_label: str | None
    outcome: str
    reason: str | None
    #: changed field names (and non-restricted values where the writer recorded them); restricted values
    #: are never stored, only their names in ``restricted_fields``
    changes: dict[str, Any] | None
    restricted_fields: list[str] | None
    details: dict[str, Any] | None
    ip: str | None
    user_agent: str | None
    request_id: str | None
    correlation_id: str | None
