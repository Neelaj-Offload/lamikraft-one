"""Postgres-backed rate limits and login lockout (api-conventions §7).

- Fixed 10-minute windows: 30 sign-in attempts per IP and 10 per email (keyed HMACs, never raw values).
- Lockout keyed by the email HMAC, so known and unknown emails behave identically: after 5 consecutive
  failures the email is blocked for ``15 min × 2^lock_count`` (capped at 4 h); success clears the state.
Counters are upserted atomically (``INSERT … ON CONFLICT DO UPDATE … RETURNING``) and use business time
from the Clock so tests can move through windows deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.identity.auth_models import RateLimitCounter

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

WINDOW = timedelta(minutes=10)
IP_LIMIT = 30
EMAIL_LIMIT = 10
LOCK_THRESHOLD = 5
LOCK_BASE = timedelta(minutes=15)
LOCK_CAP = timedelta(hours=4)
LOCK_STATE_RETENTION = timedelta(hours=24)
#: lockout rows live in a single, non-windowed slot
_LOCK_WINDOW = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after_seconds: int = 0
    code: str | None = None  # rate_limited | account_locked


def _window_start(now: datetime) -> datetime:
    seconds = int(WINDOW.total_seconds())
    ts = int(now.timestamp())
    return datetime.fromtimestamp(ts - ts % seconds, UTC)


def hit(session: Session, bucket: str, *, limit: int, now: datetime) -> Verdict:
    """Count one attempt in ``bucket``'s current window; refuse once the window holds more than ``limit``."""
    start = _window_start(now)
    stmt = pg_insert(RateLimitCounter).values(
        bucket_key=bucket, window_start=start, count=1, lock_count=0, updated_at=now, expires_at=start + 2 * WINDOW
    )
    count = session.execute(
        stmt.on_conflict_do_update(
            index_elements=[RateLimitCounter.bucket_key, RateLimitCounter.window_start],
            set_={"count": RateLimitCounter.count + 1, "updated_at": now},
        ).returning(RateLimitCounter.count)
    ).scalar_one()
    if count > limit:
        retry = max(1, int((start + WINDOW - now).total_seconds()))
        return Verdict(False, retry, "rate_limited")
    return Verdict(True)


def _lock_bucket(email_key: str) -> str:
    return f"login:lock:{email_key}"


def lock_state(session: Session, email_key: str, *, now: datetime) -> Verdict:
    row = session.get(RateLimitCounter, (_lock_bucket(email_key), _LOCK_WINDOW))
    if row is not None and row.blocked_until is not None and row.blocked_until > now:
        return Verdict(False, max(1, int((row.blocked_until - now).total_seconds())), "account_locked")
    return Verdict(True)


@dataclass(frozen=True)
class FailureResult:
    consecutive_failures: int
    locked_until: datetime | None
    lock_count: int


def record_failure(session: Session, email_key: str, *, now: datetime) -> FailureResult:
    """Count a failed sign-in; the fifth consecutive failure locks the email with exponential backoff."""
    stmt = pg_insert(RateLimitCounter).values(
        bucket_key=_lock_bucket(email_key),
        window_start=_LOCK_WINDOW,
        count=1,
        lock_count=0,
        updated_at=now,
        expires_at=now + LOCK_STATE_RETENTION,
    )
    count, lock_count = session.execute(
        stmt.on_conflict_do_update(
            index_elements=[RateLimitCounter.bucket_key, RateLimitCounter.window_start],
            set_={
                "count": RateLimitCounter.count + 1,
                "updated_at": now,
                "expires_at": stmt.excluded.expires_at,
            },
        ).returning(RateLimitCounter.count, RateLimitCounter.lock_count)
    ).one()
    if count < LOCK_THRESHOLD:
        return FailureResult(count, None, lock_count)
    duration = min(LOCK_BASE * (2**lock_count), LOCK_CAP)
    until = now + duration
    row = session.get(RateLimitCounter, (_lock_bucket(email_key), _LOCK_WINDOW), populate_existing=True)
    assert row is not None  # noqa: S101 - just upserted in this transaction
    row.count = 0
    row.lock_count = lock_count + 1
    row.blocked_until = until
    row.expires_at = until + LOCK_STATE_RETENTION
    session.flush()
    return FailureResult(count, until, lock_count + 1)


def clear_failures(session: Session, email_key: str) -> None:
    session.execute(
        delete(RateLimitCounter).where(
            RateLimitCounter.bucket_key == _lock_bucket(email_key), RateLimitCounter.window_start == _LOCK_WINDOW
        )
    )


def purge_expired(session: Session, *, now: datetime) -> int:
    result = session.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
