"""The hourly ``identity.purge_auth_state`` job removes expired authentication state only."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.platform.identity import ratelimit, service
from app.platform.identity.auth_models import AuthAttempt, AuthSession, RateLimitCounter
from app.platform.identity.sessions import ClientInfo
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from tests.integration.identity.fixtures import Tenant, make_member, system

pytestmark = pytest.mark.db


def test_purge_keeps_live_state_and_removes_expired_state(tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    assert "identity.purge_auth_state" in get_registry().jobs
    assert get_registry().schedules["identity.purge_auth_state"].interval_seconds == 3600
    old_member = make_member(tenant, ["sales"])
    service.test_sign_in(tenant.company_id, old_member.user_id, ClientInfo(ip="10.1.1.1"))
    with UnitOfWork(system(None)) as uow:
        ratelimit.hit(uow.session, "login:ip:old", limit=30, now=uow.now())
    frozen_clock.advance(days=95)
    fresh_member = make_member(tenant, ["sales"])
    fresh = service.test_sign_in(tenant.company_id, fresh_member.user_id, ClientInfo(ip="10.1.1.2"))
    with UnitOfWork(system(None)) as uow:
        ratelimit.hit(uow.session, f"login:ip:{uuid.uuid4().hex}", limit=30, now=uow.now())
        result = service.purge_auth_state(uow)
    assert result == {"counters": 1, "attempts": 1, "sessions": 1}
    with UnitOfWork(system(None)) as uow:
        sessions = list(uow.session.scalars(select(AuthSession.id)))
        attempts = list(uow.session.scalars(select(AuthAttempt.session_id)))
        counters = list(uow.session.scalars(select(RateLimitCounter.bucket_key)))
    assert sessions == [fresh.issued.session_id]
    assert attempts == [fresh.issued.session_id]
    assert len(counters) == 1 and counters[0] != "login:ip:old"
    assert frozen_clock.now() - fresh.issued.created_at < timedelta(seconds=1)
