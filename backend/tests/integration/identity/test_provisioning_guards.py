"""Provisioning guards added by the review-fix pass: tenant checks on ids, deactivation, the batched last-admin guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.events.models import DomainEvent
from app.platform.identity import provisioning, service
from app.platform.identity.actors import actor_for
from app.platform.identity.auth_models import AuthSession, DemoSignInToken
from app.platform.identity.models import Membership
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import Tenant, make_member, make_tenant, system

pytestmark = pytest.mark.db


def _user(tenant: Tenant) -> object:
    from app.platform.identity.provisioning import ensure_user

    with UnitOfWork(system(None)) as uow:
        user_id, _ = ensure_user(uow, email=f"guard-{tenant.key}@example.test", display_name="Guard Test", status="active")
    return user_id


def test_provisioning_rejects_branches_and_managers_of_another_company(tenant: Tenant) -> None:
    other = make_tenant()
    foreign_manager = make_member(other, ["sales"])
    user_id = _user(tenant)
    with pytest.raises(ValidationFailed), UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.provision_membership(
            uow, user_id=user_id, status="active", role_keys=["sales"], branch_ids=[other.ho_branch_id], default_branch_id=tenant.ho_branch_id
        )
    with pytest.raises(ValidationFailed), UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.provision_membership(
            uow, user_id=user_id, status="active", role_keys=["sales"], default_branch_id=other.fac_branch_id
        )
    with pytest.raises(NotFound), UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.provision_membership(
            uow,
            user_id=user_id,
            status="active",
            role_keys=["sales"],
            default_branch_id=tenant.ho_branch_id,
            manager_membership_id=foreign_manager.membership_id,
        )
    own_manager = make_member(tenant, ["management"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        membership_id, created = provisioning.provision_membership(
            uow,
            user_id=user_id,
            status="active",
            role_keys=["sales"],
            branch_ids=[tenant.fac_branch_id],
            default_branch_id=tenant.ho_branch_id,
            manager_membership_id=own_manager.membership_id,
        )
    assert created and membership_id


def test_deactivation_revokes_sessions_and_links_and_emits(client: TestClient) -> None:
    from tests.integration.identity.fixtures import origin_headers

    tenant = make_tenant(is_demo=True)  # demo links exist only in demo companies
    admin = make_member(tenant, ["admin"])
    target = make_member(tenant, ["sales"])
    keeper = make_member(tenant, ["sales"])
    used = service.issue_demo_link(company_key=tenant.key, email=target.email)
    assert client.post("/api/v1/identity/demo-sign-in", json={"token": used.token}, headers=origin_headers()).status_code == 200
    unused = service.issue_demo_link(company_key=tenant.key, email=target.email)
    admin_actor = actor_for(tenant.company_id, admin.user_id, "test")
    assert admin_actor is not None
    with pytest.raises(ValidationFailed), UnitOfWork(admin_actor) as uow:
        provisioning.deactivate_membership(uow, target.membership_id, reason="  ")
    with pytest.raises(Forbidden), UnitOfWork(admin_actor) as uow:
        provisioning.deactivate_membership(uow, admin.membership_id, reason="leaving")  # never yourself
    with UnitOfWork(admin_actor) as uow:
        assert provisioning.deactivate_membership(
            uow, target.membership_id, reason="Left the company", reassign_to_membership_id=keeper.membership_id
        )
    with UnitOfWork(admin_actor) as uow:
        assert not provisioning.deactivate_membership(uow, target.membership_id, reason="again")  # idempotent
    assert client.get("/api/v1/identity/me").json()["code"] == "session_expired"
    fresh = TestClient(client.app, base_url="http://testserver")
    late = fresh.post("/api/v1/identity/demo-sign-in", json={"token": unused.token}, headers=origin_headers())
    assert late.status_code == 401 and late.json()["code"] == "link_invalid_or_used"
    with UnitOfWork(system(tenant.company_id)) as uow:
        membership = uow.session.get(Membership, target.membership_id)
        assert membership is not None and membership.status == "deactivated"
        assert membership.deactivated_by == admin.user_id and membership.deactivation_reason == "Left the company"
        sessions = list(uow.session.scalars(select(AuthSession).where(AuthSession.membership_id == target.membership_id)))
        assert sessions and all(s.revoked_reason == "deactivated" for s in sessions)
        tokens = list(uow.session.scalars(select(DemoSignInToken).where(DemoSignInToken.membership_id == target.membership_id)))
        assert tokens and all(t.revoked_at is not None or t.used_at is not None for t in tokens)
        events = list(
            uow.session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "identity.membership.deactivated", DomainEvent.aggregate_id == target.membership_id
                )
            )
        )
    assert len(events) == 1
    assert events[0].payload["reassign_to_membership_id"] == str(keeper.membership_id)
    assert events[0].payload["user_id"] == str(target.user_id)
    assert actor_for(tenant.company_id, target.user_id, "test") is None


def test_the_last_role_manager_cannot_be_deactivated(tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"])
    with pytest.raises(Conflict) as exc, UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.deactivate_membership(uow, admin.membership_id, reason="leaving")
    assert exc.value.code == "last_admin"


def test_a_company_grant_of_role_management_counts_for_the_last_admin_guard(tenant: Tenant) -> None:
    """The batched guard finds holders through roles and through open company-scope grants; revokes still win."""
    admin = make_member(tenant, ["admin"])
    delegate = make_member(tenant, ["management"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, delegate.membership_id, permission_key="identity.role.manage", effect="grant", scope="company", reason="deputy"
        )
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert provisioning.assign_roles(uow, admin.membership_id, ["management"])  # the deputy keeps role management
    with pytest.raises(Conflict) as exc, UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, delegate.membership_id, permission_key="identity.role.manage", effect="revoke", reason="no deputies"
        )
    assert exc.value.code == "last_admin"
