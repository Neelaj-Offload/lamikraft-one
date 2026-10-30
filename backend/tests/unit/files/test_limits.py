"""Upload rate check: runs the installed limiter before the body is read, skips system actors, fails closed.

The limiter itself is identity's Postgres counter (``app.platform.identity.ratelimit.upload_limiter``); it is
exercised over HTTP in ``tests/integration/files/test_files.py``. These tests need no database.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import RateLimited
from app.platform.authz.context import ActorContext
from app.platform.files.limits import check_upload_rate, set_upload_limiter


def _actor(company_id: uuid.UUID, user_id: uuid.UUID) -> ActorContext:
    return ActorContext(actor_type="user", company_id=company_id, user_id=user_id)


class StubLimiter:
    """Allows ``allowed`` calls, then answers ``retry`` seconds; records who was counted."""

    def __init__(self, allowed: int, retry: float) -> None:
        self.allowed, self.retry = allowed, retry
        self.seen: list[ActorContext] = []

    def __call__(self, actor: ActorContext) -> float | None:
        self.seen.append(actor)
        return None if len(self.seen) <= self.allowed else self.retry


def test_check_raises_429_with_retry_after_and_skips_system_actors() -> None:
    limiter = StubLimiter(allowed=1, retry=29.2)
    previous = set_upload_limiter(limiter)
    try:
        actor = _actor(uuid.uuid7(), uuid.uuid7())
        check_upload_rate(actor)
        with pytest.raises(RateLimited) as exc:
            check_upload_rate(actor)
        assert exc.value.status == 429 and exc.value.code == "rate_limited"
        assert exc.value.extra["retry_after_seconds"] == 30  # rounded up, never 0
        system = ActorContext.system(actor.company_id)
        check_upload_rate(system)
        check_upload_rate(system)
        assert len(limiter.seen) == 2  # system actors are never counted
    finally:
        set_upload_limiter(previous)


def test_without_an_installed_limiter_uploads_fail_closed() -> None:
    previous = set_upload_limiter(None)
    try:
        with pytest.raises(RuntimeError, match="no upload limiter"):
            check_upload_rate(_actor(uuid.uuid7(), uuid.uuid7()))
        check_upload_rate(ActorContext.system(None))  # system actors do not need one
    finally:
        set_upload_limiter(previous)


def test_set_upload_limiter_returns_the_previous_limiter() -> None:
    first, second = StubLimiter(0, 1), StubLimiter(0, 2)
    original = set_upload_limiter(first)
    try:
        assert set_upload_limiter(second) is first
    finally:
        set_upload_limiter(original)
