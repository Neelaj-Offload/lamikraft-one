"""Upload rate limiter: a sliding window per (company, user), checked before the body is read (no database)."""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import RateLimited
from app.platform.authz.context import ActorContext
from app.platform.files import limits
from app.platform.files.limits import SlidingWindowLimiter, check_upload_rate, set_upload_limiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _actor(company_id: uuid.UUID, user_id: uuid.UUID) -> ActorContext:
    return ActorContext(actor_type="user", company_id=company_id, user_id=user_id)


def test_the_window_slides_per_user() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, 60, clock=clock)
    company = uuid.uuid7()
    meera, neha = _actor(company, uuid.uuid7()), _actor(company, uuid.uuid7())
    assert limiter(meera) is None and limiter(meera) is None
    clock.now += 10
    assert limiter(meera) == pytest.approx(50)  # the first hit leaves the window in 50 s
    assert limiter(neha) is None  # other users are counted separately
    clock.now += 50
    assert limiter(meera) is None  # the first hit has left the window


def test_check_raises_429_with_retry_after_and_skips_system_actors() -> None:
    clock = FakeClock()
    set_upload_limiter(SlidingWindowLimiter(1, 30, clock=clock))
    try:
        actor = _actor(uuid.uuid7(), uuid.uuid7())
        check_upload_rate(actor)
        with pytest.raises(RateLimited) as exc:
            check_upload_rate(actor)
        assert exc.value.status == 429 and exc.value.code == "rate_limited"
        assert exc.value.extra["retry_after_seconds"] == 30
        system = ActorContext.system(actor.company_id)
        check_upload_rate(system)
        check_upload_rate(system)
    finally:
        set_upload_limiter(None)
    assert isinstance(limits._limiter, SlidingWindowLimiter)
    assert (limits._limiter.limit, limits._limiter.window) == (limits.UPLOADS_PER_WINDOW, limits.WINDOW_SECONDS)
