"""PARITY PERM-29 / FG-USR-05: generic sign-in errors, lockout with backoff, IP and email rate limits, attempts and
last sign-in recorded; administrators then need their authenticator (Slice 2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.identity import ratelimit
from app.platform.identity.auth_models import AuthAttempt
from app.platform.identity.models import AppUser
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import TEST_PASSWORD, Tenant, login, make_member, system

pytestmark = pytest.mark.db


def test_generic_errors_lockout_and_rate_limits(client: TestClient, tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    admin = make_member(tenant, ["admin"], password=TEST_PASSWORD)
    wrong = login(client, member.email, "not-the-password-1")
    unknown = login(client, "nobody@example.test", "not-the-password-1")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] and wrong.json()["code"] == "invalid_credentials"

    for _ in range(ratelimit.LOCK_THRESHOLD - 2):
        login(client, member.email, "not-the-password-1")
    locked = login(client, member.email, "not-the-password-1")
    assert locked.status_code in (401, 429)
    blocked = login(client, member.email)  # even the right password is refused while locked
    assert blocked.status_code == 429 and blocked.json()["code"] == "account_locked" and blocked.headers.get("retry-after")
    frozen_clock.advance(minutes=16)
    assert login(client, member.email).status_code == 200

    # an administrator's correct password opens only the second step
    assert login(TestClient(client.app, base_url="http://testserver"), admin.email).json()["stage"] == "mfa_enrollment_required"


def test_attempts_and_last_login_recorded(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"], password=TEST_PASSWORD)
    assert login(client, member.email, "not-the-password-1").status_code == 401
    assert login(client, member.email).status_code == 200
    with UnitOfWork(system(None)) as uow:
        outcomes = [a.outcome for a in uow.session.scalars(select(AuthAttempt).where(AuthAttempt.user_id == member.user_id).order_by(AuthAttempt.occurred_at, AuthAttempt.id))]
        user = uow.session.get(AppUser, member.user_id)
    assert outcomes == ["invalid_credentials", "success"]
    assert user is not None and user.last_login_at is not None and user.failed_login_count == 0
