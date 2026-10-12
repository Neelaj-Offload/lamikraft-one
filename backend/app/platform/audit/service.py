"""Audit recording. Restricted values are never written; only their field names are listed."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from app.platform.audit.models import AuditLog

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

_SECRET_HINTS = ("password", "token", "secret", "hash", "otp", "key")


def _clean_changes(changes: dict[str, Any] | None) -> dict[str, Any] | None:
    if not changes:
        return None
    return {k: ("[redacted]" if any(h in k.lower() for h in _SECRET_HINTS) else v) for k, v in changes.items()}


def record(
    uow: UnitOfWork,
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    resource_label: str | None = None,
    outcome: str = "success",
    reason: str | None = None,
    changes: dict[str, Any] | None = None,
    restricted_fields: list[str] | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    actor = uow.actor
    if actor.company_id is None:
        return  # platform-level events without a tenant are logged, not audited per company
    uow.session.add(
        AuditLog(
            id=uuid.uuid7(),
            company_id=actor.company_id,
            occurred_at=uow.now(),
            actor_type=actor.actor_type,
            actor_user_id=actor.user_id,
            on_behalf_of_user_id=actor.on_behalf_of_user_id,
            session_id=actor.session_id,
            channel=actor.channel,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_label=(resource_label or "")[:200] or None,
            outcome=outcome,
            reason=reason,
            changes=_clean_changes(changes),
            restricted_fields=restricted_fields,
            details=details,
            ip=ip,
            user_agent=(user_agent or "")[:256] or None,
            request_id=actor.request_id,
            correlation_id=actor.correlation_id,
        )
    )
