"""One-time demo sign-in links: 15 minutes, single use, demo companies only, token never in a URL query."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.errors import Forbidden, NotFound
from app.platform.identity import service
from app.platform.identity.auth_models import AuthSession, DemoSignInToken
from app.platform.identity.tokens import new_token, sha256
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import Tenant, make_member, origin_headers, system

pytestmark = pytest.mark.db

DEMO = "/api/v1/identity/demo-sign-in"


def _post(client: TestClient, token: str):  # type: ignore[no-untyped-def]
    return client.post(DEMO, json={"token": token}, headers=origin_headers())


def test_link_signs_in_once(client: TestClient, world: SeedContext) -> None:
    link = service.issue_demo_link(company_key=keys.COMPANY_KEY, email=keys.PEOPLE[keys.USERS.MEERA].email)
    assert link.expires_at - keys.CLOCK_D0 == timedelta(minutes=15)
    assert link.token.startswith(world.company_id.hex + ".")
    r = _post(client, link.token)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(world.refs[keys.USERS.MEERA])
    assert r.json()["session"]["auth_method"] == "demo_link"
    assert client.cookies.get("lk_session")
    me = client.get("/api/v1/identity/me")
    assert me.status_code == 200 and me.json()["membership"]["company"]["is_demo"] is True

    again = _post(TestClient(client.app, base_url="http://testserver"), link.token)
    assert again.status_code == 401 and again.json()["code"] == "link_invalid_or_used"
    with UnitOfWork(system(world.company_id)) as uow:
        row = uow.session.scalars(select(DemoSignInToken).where(DemoSignInToken.token_hash == sha256(link.token))).one()
        assert row.used_at == keys.CLOCK_D0 and row.session_id is not None
        session = uow.session.get(AuthSession, row.session_id)
        assert session is not None and session.auth_method == "demo_link"


def test_link_expires_after_fifteen_minutes(client: TestClient, world: SeedContext, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    link = service.issue_demo_link(company_key=keys.COMPANY_KEY, email=keys.PEOPLE[keys.USERS.SAHIL].email)
    frozen_clock.advance(minutes=15)
    r = _post(client, link.token)
    assert r.status_code == 401 and r.json()["code"] == "link_invalid_or_used"


def test_malformed_and_unknown_tokens_get_the_same_answer(client: TestClient, world: SeedContext) -> None:
    for token in ("x" * 40, f"{uuid.uuid4().hex}.{new_token()}", f"{world.company_id.hex}.{new_token()}"):
        r = _post(client, token)
        assert r.status_code == 401 and r.json()["code"] == "link_invalid_or_used"


def test_links_exist_only_for_demo_companies(client: TestClient, tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    with pytest.raises(Forbidden) as exc:
        service.issue_demo_link(company_key=tenant.key, email=member.email)
    assert exc.value.code == "not_demo_company"
    with pytest.raises(NotFound):
        service.issue_demo_link(company_key="no-such-company", email=member.email)
    # a token row in a non-demo company (written directly) still cannot sign anyone in
    token = f"{tenant.company_id.hex}.{new_token()}"
    with UnitOfWork(system(tenant.company_id)) as uow:
        now = uow.now()
        uow.add(
            DemoSignInToken(
                company_id=tenant.company_id,
                user_id=member.user_id,
                membership_id=member.membership_id,
                token_hash=sha256(token),
                issued_via="cli",
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )
    r = _post(client, token)
    assert r.status_code == 401 and r.json()["code"] == "link_invalid_or_used"


def test_inactive_member_cannot_get_or_use_a_link(client: TestClient, world: SeedContext) -> None:
    from app.platform.identity.models import Membership

    email = keys.PEOPLE[keys.USERS.NEHA].email
    link = service.issue_demo_link(company_key=keys.COMPANY_KEY, email=email)
    with UnitOfWork(system(world.company_id)) as uow:
        m = uow.session.scalars(select(Membership).where(Membership.user_id == world.refs[keys.USERS.NEHA])).one()
        m.status = "suspended"
    assert _post(client, link.token).json()["code"] == "link_invalid_or_used"
    from app.core.errors import Conflict

    with pytest.raises(Conflict):
        service.issue_demo_link(company_key=keys.COMPANY_KEY, email=email)


def test_demo_users_cannot_use_password_sign_in(client: TestClient, world: SeedContext) -> None:
    r = client.post(
        "/api/v1/identity/session",
        json={"email": keys.PEOPLE[keys.USERS.PRIYA].email, "password": "any-password-at-all"},
        headers=origin_headers(),
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
