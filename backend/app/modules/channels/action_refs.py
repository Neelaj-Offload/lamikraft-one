"""Action refs: a WhatsApp button is a random nonce bound to (user, identity, proposal, content hash, action).
Consuming one needs the nonce from the bound identity before expiry; the model is never involved. Unlink,
suspension, a changed proposal and acknowledgements elsewhere void armed refs."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.modules.channels.models import ActionRef
from app.platform.uow import UnitOfWork

DEFAULT_TTL = timedelta(hours=24)
NONCE_PREFIX = "a:"


def new_nonce() -> str:
    return secrets.token_urlsafe(18)


def button_id(ref: ActionRef) -> str:
    return f"{NONCE_PREFIX}{ref.nonce}"


def nonce_from_button_id(value: str | None) -> str | None:
    if not value or not value.startswith(NONCE_PREFIX):
        return None
    return value[len(NONCE_PREFIX):]


def arm(
    uow: UnitOfWork, *, user_id: uuid.UUID, identity_id: uuid.UUID, action: str, proposal_id: uuid.UUID | None = None,
    content_hash: str | None = None, option_payload: dict[str, Any] | None = None, ttl: timedelta = DEFAULT_TTL,
) -> ActionRef:
    now = uow.now()
    row = ActionRef(
        id=uuid.uuid7(), user_id=user_id, identity_id=identity_id, proposal_id=proposal_id, content_hash=content_hash,
        action=action, option_payload=dict(option_payload or {}), nonce=new_nonce(), armed_at=now, expires_at=now + ttl,
    )
    uow.add(row)
    uow.flush()
    return row


def get(uow: UnitOfWork, ref_id: uuid.UUID) -> ActionRef | None:
    row = uow.session.get(ActionRef, ref_id)
    return row if row is not None and row.company_id == uow.actor.company_id else None


def bind_message(uow: UnitOfWork, refs: list[ActionRef], message_id: uuid.UUID) -> None:
    for ref in refs:
        ref.outbound_message_id = message_id


def consume(uow: UnitOfWork, nonce: str, *, identity_id: uuid.UUID, now: datetime, provider_ts: datetime | None) -> tuple[ActionRef | None, str]:
    """(ref, outcome): ``ok`` when consumed now; otherwise ``unknown``, ``wrong_identity``, ``expired``, ``consumed``,
    ``voided`` or ``stale`` (the reply predates the arming, so it cannot answer this button)."""
    row = uow.session.scalars(select(ActionRef).where(ActionRef.nonce == nonce).with_for_update()).first()
    if row is None or row.company_id != uow.actor.company_id:
        return None, "unknown"
    if row.identity_id != identity_id:
        return row, "wrong_identity"
    if row.voided_at is not None:
        return row, "voided"
    if row.consumed_at is not None:
        return row, "consumed"
    if row.expires_at <= now:
        return row, "expired"
    if provider_ts is not None and provider_ts < row.armed_at:
        return row, "stale"
    row.consumed_at = now
    uow.flush()
    return row, "ok"


def _void(uow: UnitOfWork, clause: Any, reason: str) -> int:
    now = uow.now()
    result = uow.session.execute(
        update(ActionRef)
        .where(ActionRef.company_id == uow.actor.company_id, ActionRef.consumed_at.is_(None), ActionRef.voided_at.is_(None), clause)
        .values(voided_at=now, void_reason=reason[:80], updated_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def void_for_identity(uow: UnitOfWork, identity_id: uuid.UUID, *, reason: str) -> int:
    return _void(uow, ActionRef.identity_id == identity_id, reason)


def void_for_user(uow: UnitOfWork, user_id: uuid.UUID, *, reason: str) -> int:
    return _void(uow, ActionRef.user_id == user_id, reason)


def void_for_proposal(uow: UnitOfWork, proposal_id: uuid.UUID, *, reason: str) -> int:
    return _void(uow, ActionRef.proposal_id == proposal_id, reason)


def void_for_target(uow: UnitOfWork, target_type: str, target_id: uuid.UUID, *, reason: str) -> int:
    return _void(
        uow,
        (ActionRef.option_payload["target_type"].astext == target_type) & (ActionRef.option_payload["target_id"].astext == str(target_id)),
        reason,
    )


def armed_for_identity(uow: UnitOfWork, identity_id: uuid.UUID, now: datetime) -> list[ActionRef]:
    return list(uow.session.scalars(
        select(ActionRef).where(
            ActionRef.identity_id == identity_id, ActionRef.consumed_at.is_(None), ActionRef.voided_at.is_(None), ActionRef.expires_at > now
        ).order_by(ActionRef.armed_at)
    ))


__all__ = [
    "DEFAULT_TTL", "NONCE_PREFIX", "arm", "get", "armed_for_identity", "bind_message", "button_id", "consume", "new_nonce", "nonce_from_button_id",
    "void_for_identity", "void_for_proposal", "void_for_target", "void_for_user",
]
