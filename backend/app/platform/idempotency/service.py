"""Idempotent commands: replay the stored (already redacted) response for a repeated key.

The row is inserted inside the business transaction, so a concurrent duplicate blocks until the
first commits, then replays. A different request under the same key returns 422.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import IdempotencyKeyReused, ValidationFailed
from app.platform.idempotency.models import IdempotencyKey

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

TTL = timedelta(hours=48)


def request_hash(operation: str, body: Any) -> str:
    canonical = json.dumps({"op": operation, "body": body}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_idempotent(
    uow: UnitOfWork,
    *,
    key: str | None,
    operation: str,
    body: Any,
    fn: Callable[[], dict[str, Any]],
    status: int = 200,
) -> tuple[dict[str, Any], bool]:
    """Return ``(response_body, replayed)``. Without a key the function simply runs."""
    if not key:
        return fn(), False
    if len(key) > 128:
        raise ValidationFailed("Idempotency-Key is too long", code="idempotency_key_invalid")
    actor = uow.actor
    if actor.company_id is None or actor.user_id is None:
        return fn(), False
    digest = request_hash(operation, body)
    now = uow.now()
    inserted = uow.session.execute(
        pg_insert(IdempotencyKey)
        .values(
            company_id=actor.company_id, user_id=actor.user_id, key=key, operation=operation,
            request_hash=digest, created_at=now, expires_at=now + TTL,
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    ).first()
    if inserted is None:
        row = uow.session.scalars(
            select(IdempotencyKey).where(
                IdempotencyKey.company_id == actor.company_id,
                IdempotencyKey.user_id == actor.user_id,
                IdempotencyKey.key == key,
            )
        ).one()
        if row.request_hash != digest or row.operation != operation:
            raise IdempotencyKeyReused()
        return dict(row.response_body or {}), True
    response = fn()
    row = uow.session.get(IdempotencyKey, (actor.company_id, actor.user_id, key))
    if row is not None:
        row.response_status = status
        row.response_body = json.loads(json.dumps(response, default=str))
    return response, False
