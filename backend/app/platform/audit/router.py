"""Audit read API (``audit.log.read``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.platform.audit import query as audit_query
from app.platform.audit.schemas import AuditEntryRead, CursorPage

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "",
    openapi_extra=requires("audit.log.read"),
    operation_id="audit_list_entries",
    summary="Audit entries, newest first, with keyset pagination (pass next_cursor back as cursor)",
)
def list_entries(
    actor: Actor,
    action: str | None = Query(default=None, max_length=120),
    action_prefix: str | None = Query(default=None, max_length=120),
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = Query(default=None, max_length=80),
    resource_id: uuid.UUID | None = None,
    outcome: Literal["success", "denied", "failed"] | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=audit_query.DEFAULT_LIMIT, ge=1, le=audit_query.MAX_LIMIT),
) -> CursorPage[AuditEntryRead]:
    return audit_query.list_entries(
        actor,
        action=action,
        action_prefix=action_prefix,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        cursor=cursor,
        limit=limit,
    )
