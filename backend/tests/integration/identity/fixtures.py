"""Shared fixtures for identity and ui integration tests (imported by the conftest of each test folder).

Business rows are created through the identity provisioning services; HTTP tests use a real app with the
CSRF/Origin middleware and real session cookies.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.platform.authz.context import ActorContext
from app.platform.identity import passwords, provisioning, roles
from app.platform.identity.access import ACCESS_CACHE
from app.platform.identity.provisioning import CompanySpec, TeamSeat
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext

#: a policy-compliant test password (not a real credential; generated for these tests only)
TEST_PASSWORD = "plover-Granite-41-quarry"  # noqa: S105


@dataclass(frozen=True)
class Tenant:
    company_id: uuid.UUID
    key: str
    ho_branch_id: uuid.UUID
    fac_branch_id: uuid.UUID


@dataclass(frozen=True)
class Member:
    company_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str


def system(company_id: uuid.UUID | None) -> ActorContext:
    return ActorContext.system(company_id, reason="test-setup")


def make_tenant(key: str | None = None, *, is_demo: bool = False) -> Tenant:
    key = key or f"t-{uuid.uuid4().hex[:10]}"
    with UnitOfWork(system(None)) as uow:
        roles.sync_permission_catalogue(uow)
        company_id, _ = provisioning.ensure_company(
            uow, CompanySpec(company_key=key, legal_name=f"{key} Pvt. Ltd.", display_name=key, is_demo=is_demo)
        )
    with UnitOfWork(system(company_id)) as uow:
        roles.ensure_system_roles(uow, company_id)
        ho = provisioning.ensure_branch(uow, code="HO", name="Head Office", is_head_office=True)
        fac = provisioning.ensure_branch(uow, code="FAC", name="Factory")
    return Tenant(company_id, key, ho, fac)


def make_member(
    tenant: Tenant,
    role_keys: Sequence[str] = ("sales",),
    *,
    email: str | None = None,
    name: str = "Test Person",
    password: str | None = None,
    status: str = "active",
    branch_ids: Sequence[uuid.UUID] | None = None,
    teams: Sequence[TeamSeat] = (),
    time_zone: str | None = None,
) -> Member:
    email = email or f"{uuid.uuid4().hex[:12]}@example.test"
    password_hash = passwords.hash_password(password) if password else None
    with UnitOfWork(system(None)) as uow:
        user_id, _ = provisioning.ensure_user(
            uow,
            email=email,
            display_name=name,
            status="active" if status == "active" else "invited",
            password_hash=password_hash,
            time_zone=time_zone,
        )
    with UnitOfWork(system(tenant.company_id)) as uow:
        membership_id, _ = provisioning.provision_membership(
            uow,
            user_id=user_id,
            status=status,
            role_keys=list(role_keys),
            branch_ids=list(branch_ids) if branch_ids is not None else [tenant.ho_branch_id],
            default_branch_id=tenant.ho_branch_id,
            teams=teams,
        )
    return Member(tenant.company_id, user_id, membership_id, email)


def count(model: type, company_id: uuid.UUID | None = None, *where: object) -> int:
    with UnitOfWork(system(company_id)) as uow:
        stmt = select(func.count()).select_from(model)
        for clause in where:
            stmt = stmt.where(clause)  # type: ignore[arg-type]
        return int(uow.session.scalar(stmt) or 0)


def origin_headers() -> dict[str, str]:
    return {"Origin": get_settings().public_origin}


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {**origin_headers(), "X-CSRF-Token": client.cookies.get("lk_csrf") or ""}


def login(client: TestClient, email: str, password: str = TEST_PASSWORD):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/identity/session", json={"email": email, "password": password}, headers=origin_headers())


def test_sign_in(client: TestClient, user_key: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/_test/sign-in", json={"user_key": user_key}, headers=origin_headers())


test_sign_in.__test__ = False  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def api_app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(db: None, api_app: FastAPI) -> Iterator[TestClient]:
    ACCESS_CACHE.clear()
    with TestClient(api_app, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def tenant(db: None) -> Tenant:
    return make_tenant()


@pytest.fixture
def world(db: None) -> SeedContext:
    """The canonical Slice-1 world seeded through the runner (savepoint mode: rolled back after the test)."""
    from app.seed.runner import run_demo_seed

    ACCESS_CACHE.clear()
    return run_demo_seed(slice_max=1)


# ---- MFA helpers (Slice 2) -----------------------------------------------------------------------------------
def totp_code(secret: str, *, step_offset: int = 0) -> str:
    """The authenticator code for the frozen business clock (``step_offset`` 30-second steps later)."""
    from datetime import timedelta

    from app.core.clock import get_clock
    from app.platform.identity import mfa

    return mfa.code_at(secret, get_clock().now() + timedelta(seconds=30 * step_offset))


def enrol_mfa(client: TestClient) -> tuple[str, list[str]]:
    """Enrol an authenticator for the signed-in (or enrolment-required) session; returns (secret, recovery codes).

    Moves the frozen clock one step so the confirming code is never a replay of an earlier test step.
    """
    from app.core.clock import get_clock

    started = client.post("/api/v1/identity/me/mfa/totp", headers=csrf_headers(client))
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    clock = get_clock()
    if hasattr(clock, "advance"):
        clock.advance(seconds=30)
    confirmed = client.post(
        "/api/v1/identity/me/mfa/totp/confirmation", json={"code": totp_code(secret)}, headers=csrf_headers(client)
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


def login_admin(client: TestClient, member: Member, password: str = TEST_PASSWORD) -> str:
    """Sign an administrator in the Slice-2 way: password, then the enrolment the role requires. Returns the
    TOTP secret (an already enrolled admin is not supported here; use ``verify_code``)."""
    r = login(client, member.email, password)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "mfa_enrollment_required", r.json()
    secret, _codes = enrol_mfa(client)
    return secret


def verify_code(client: TestClient, code: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/identity/session/verification", json={"code": code}, headers=csrf_headers(client))


@pytest.fixture
def demo_outbox(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Redirect the demo mail outbox to a temporary folder; yields that folder."""
    from app.platform.identity import mail

    folder = tmp_path / "mail"
    monkeypatch.setattr(mail, "outbox_dir", lambda: folder)
    return folder
