"""Audit log reads: filters plus keyset pagination ordered newest first ``(occurred_at DESC, id DESC)``.

Reading the audit log needs ``audit.log.read`` (sensitive: every read is itself audited). The tenant filter
is explicit and RLS-backed; filters apply before the page limit, so pages never skip or repeat rows even
while new entries arrive.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select, tuple_

from app.core.errors import ValidationFailed
from app.core.text import LIKE_ESCAPE, escape_like
from app.platform.audit.models import AuditLog
from app.platform.audit.schemas import AuditEntryRead, CursorPage
from app.platform.identity.models import AppUser
from app.platform.service import query

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def encode_cursor(occurred_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps([occurred_at.isoformat(), str(row_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, row_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError("naive cursor timestamp")
        return parsed, uuid.UUID(row_id)
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ValidationFailed(
            "The page cursor is not valid; start from the first page.",
            errors=[{"loc": ["query", "cursor"], "msg": "invalid cursor", "code": "invalid_cursor"}],
        ) from None


@query("audit.log.read")
def list_entries(
    uow: UnitOfWork,
    *,
    action: str | None = None,
    action_prefix: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    outcome: Literal["success", "denied", "failed"] | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> CursorPage[AuditEntryRead]:
    limit = max(1, min(limit, MAX_LIMIT))
    for name, value in (("occurred_from", occurred_from), ("occurred_to", occurred_to)):
        if value is not None and value.tzinfo is None:
            raise ValidationFailed(
                "Timestamps need a time zone (RFC 3339, e.g. 2026-10-12T03:25:00Z).",
                errors=[{"loc": ["query", name], "msg": "timestamp without time zone", "code": "naive_datetime"}],
            )
    stmt = (
        select(AuditLog, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == AuditLog.actor_user_id)
        .where(AuditLog.company_id == uow.actor.company_id)
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.like(f"{escape_like(action_prefix)}%", escape=LIKE_ESCAPE))
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if occurred_from:
        stmt = stmt.where(AuditLog.occurred_at >= occurred_from)
    if occurred_to:
        stmt = stmt.where(AuditLog.occurred_at < occurred_to)
    if cursor:
        at, row_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(AuditLog.occurred_at, AuditLog.id) < tuple_(at, row_id))
    rows = uow.session.execute(
        stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    items = [
        AuditEntryRead(
            id=entry.id,
            occurred_at=entry.occurred_at,
            actor_type=entry.actor_type,
            actor_user_id=entry.actor_user_id,
            actor_name=name,
            on_behalf_of_user_id=entry.on_behalf_of_user_id,
            channel=entry.channel,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            resource_label=entry.resource_label,
            outcome=entry.outcome,
            reason=entry.reason,
            changes=entry.changes,
            restricted_fields=entry.restricted_fields,
            details=entry.details,
            ip=str(entry.ip) if entry.ip is not None else None,
            user_agent=entry.user_agent,
            request_id=entry.request_id,
            correlation_id=entry.correlation_id,
        )
        for entry, name in page
    ]
    next_cursor = encode_cursor(page[-1][0].occurred_at, page[-1][0].id) if len(rows) > limit and page else None
    filters = {
        k: (str(v) if v is not None else None)
        for k, v in {
            "action": action,
            "action_prefix": action_prefix,
            "actor_user_id": actor_user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
        }.items()
        if v is not None
    }
    uow.audit("audit.log.read", resource_type="audit.log", details={"filters": filters, "rows": len(items)})
    return CursorPage[AuditEntryRead](items=items, next_cursor=next_cursor, limit=limit)
