"""Effective permissions from the database: roles, overrides (revoke wins), branches, teams, zones and epochs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.platform.authz.actors import actor_for_member
from app.platform.authz.permissions import Scope
from app.platform.events.models import DomainEvent
from app.platform.identity import provisioning
from app.platform.identity.actors import actor_for
from app.platform.identity.models import Membership, UserPreference
from app.platform.identity.provisioning import TeamSeat
from app.platform.org.models import Branch, Company
from app.platform.org.teams import TeamRole
from app.platform.uow import UnitOfWork
from tests.integration.identity.fixtures import Tenant, make_member, system

pytestmark = pytest.mark.db


def _epoch(tenant: Tenant) -> int:
    with UnitOfWork(system(tenant.company_id)) as uow:
        return int(uow.session.scalar(select(Company.authz_epoch).where(Company.id == tenant.company_id)) or 0)


def test_role_union_takes_the_maximum_scope(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales", "operations"])
    actor = actor_for(member.company_id, member.user_id, "test")
    assert actor is not None
    assert actor.permissions["sales.quote.read"] == Scope.COMPANY  # sales own + operations company
    assert actor.permissions["sales.quote.update"] == Scope.OWN  # only sales grants it
    assert actor.permissions["tasks.task.read"] == Scope.BRANCH  # employee own + operations branch
    assert actor.permissions["org.company.read"] == Scope.COMPANY  # employee base


def test_user_grant_raises_scope_and_revoke_wins_over_roles(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.read", effect="grant", scope="team", reason="covers the team"
        )
        provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.export", effect="revoke", reason="no exports"
        )
    actor = actor_for(member.company_id, member.user_id, "test")
    assert actor is not None
    assert actor.permissions["sales.quote.read"] == Scope.TEAM
    assert "sales.quote.export" not in actor.permissions
    # a revoke also beats a user grant for the same key (the open override is replaced)
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.read", effect="revoke", reason="read access withdrawn"
        )
    actor = actor_for(member.company_id, member.user_id, "test")
    assert actor is not None and "sales.quote.read" not in actor.permissions


def test_expired_overrides_stop_applying(tenant: Tenant, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    member = make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow,
            member.membership_id,
            permission_key="sales.quote.approve",
            effect="grant",
            scope="company",
            reason="cover for leave",
            expires_at=uow.now() + timedelta(hours=2),
        )
    first = actor_for(member.company_id, member.user_id, "test")
    assert first is not None and first.permissions["sales.quote.approve"] == Scope.COMPANY
    frozen_clock.advance(hours=2, seconds=1)
    later = actor_for(member.company_id, member.user_id, "test")
    assert later is not None and "sales.quote.approve" not in later.permissions  # cache honours the expiry


def test_override_validation(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        with pytest.raises(ValidationFailed):
            provisioning.set_permission_override(
                uow, member.membership_id, permission_key="briefings.briefing.read", effect="grant", scope="company", reason="x"
            )
        with pytest.raises(ValidationFailed):
            provisioning.set_permission_override(
                uow, member.membership_id, permission_key="sales.quote.read", effect="revoke", scope="own", reason="x"
            )
        with pytest.raises(ValidationFailed):
            provisioning.set_permission_override(
                uow, member.membership_id, permission_key="sales.quote.read", effect="grant", scope="own", reason="  "
            )
        with pytest.raises(ValidationFailed):
            provisioning.set_permission_override(
                uow, member.membership_id, permission_key="no.such.key", effect="revoke", reason="x"
            )


def test_every_access_change_bumps_the_epoch_and_emits(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    start = _epoch(tenant)
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.assign_roles(uow, member.membership_id, ["sales", "finance"])
        provisioning.set_membership_branches(uow, member.membership_id, [tenant.ho_branch_id, tenant.fac_branch_id])
        team = provisioning.ensure_team(uow, team_key="T-ONE", name="Team one")
        provisioning.add_team_member(uow, team, member.membership_id)
        provisioning.set_permission_override(uow, member.membership_id, permission_key="sales.quote.export", effect="revoke", reason="r")
    assert _epoch(tenant) == start + 4
    with UnitOfWork(system(tenant.company_id)) as uow:
        kinds = [
            e.payload["change_kinds"]
            for e in uow.session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type == "identity.membership.access_changed",
                    DomainEvent.aggregate_id == member.membership_id,
                )
                .order_by(DomainEvent.seq)
            )
        ]
    assert kinds[-4:] == [["roles"], ["branches"], ["teams"], ["overrides"]]
    actor = actor_for(member.company_id, member.user_id, "test")
    assert actor is not None
    assert actor.branch_ids == {tenant.ho_branch_id, tenant.fac_branch_id}
    assert "finance.invoice.read" in actor.permissions and "sales.quote.export" not in actor.permissions


def test_team_peers_and_branches(tenant: Tenant) -> None:
    with UnitOfWork(system(tenant.company_id)) as uow:
        team = provisioning.ensure_team(uow, team_key="EXP", name="Export")
        other = provisioning.ensure_team(uow, team_key="OTHER", name="Other")
    lead = make_member(tenant, ["management"], teams=[TeamSeat(team, TeamRole.LEAD.value)])
    a = make_member(tenant, ["sales"], teams=[TeamSeat(team)])
    b = make_member(tenant, ["sales"], teams=[TeamSeat(team)], branch_ids=[tenant.fac_branch_id])
    outsider = make_member(tenant, ["sales"], teams=[TeamSeat(other)])
    actor_a = actor_for(tenant.company_id, a.user_id, "test")
    actor_b = actor_for(tenant.company_id, b.user_id, "test")
    assert actor_a is not None and actor_b is not None
    assert actor_a.team_peer_user_ids == {lead.user_id, b.user_id}
    assert outsider.user_id not in actor_a.team_peer_user_ids
    assert actor_b.branch_ids == {tenant.fac_branch_id, tenant.ho_branch_id}  # default branch is always attached


def test_inactive_membership_or_user_has_no_actor(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        membership = uow.session.get(Membership, member.membership_id)
        assert membership is not None
        membership.status = "suspended"
    assert actor_for(tenant.company_id, member.user_id, "test") is None
    from app.core.errors import NotFound

    with pytest.raises(NotFound):
        actor_for_member(tenant.company_id, member.user_id)
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert provisioning.effective_permissions(uow, member.membership_id) == {}


def test_time_zone_resolution_order(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    actor = actor_for(tenant.company_id, member.user_id, "test")
    assert actor is not None and actor.time_zone == "Asia/Kolkata"  # company default
    with UnitOfWork(system(tenant.company_id)) as uow:
        branch = uow.session.get(Branch, tenant.ho_branch_id)
        assert branch is not None
        branch.time_zone = "Asia/Dubai"
    actor = actor_for(tenant.company_id, member.user_id, "test")
    assert actor is not None and actor.time_zone == "Asia/Dubai"  # default branch
    with UnitOfWork(system(tenant.company_id)) as uow:
        membership = uow.session.get(Membership, member.membership_id)
        assert membership is not None
        membership.work_time_zone = "Europe/London"
    actor = actor_for(tenant.company_id, member.user_id, "test")
    assert actor is not None and actor.time_zone == "Europe/London"  # membership
    berlin = make_member(tenant, ["sales"], time_zone="Europe/Berlin")
    actor = actor_for(tenant.company_id, berlin.user_id, "test")
    assert actor is not None and actor.time_zone == "Europe/Berlin"  # user
    with UnitOfWork(system(None)) as uow:
        uow.add(UserPreference(user_id=berlin.user_id, ui={}, locale={"time_zone": "America/New_York", "locale": "en-US"}, briefing={}, voice={}, assistant={}))
    actor = actor_for(tenant.company_id, berlin.user_id, "test")
    assert actor is not None and actor.time_zone == "America/New_York" and actor.locale == "en-US"  # preference


def test_user_actors_cannot_escalate_or_change_themselves(tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"])
    manager = make_member(tenant, ["management"])
    target = make_member(tenant, ["sales"])
    admin_actor = actor_for(tenant.company_id, admin.user_id, "test")
    manager_actor = actor_for(tenant.company_id, manager.user_id, "test")
    assert admin_actor is not None and manager_actor is not None
    with pytest.raises(Forbidden), UnitOfWork(manager_actor) as uow:
        provisioning.assign_roles(uow, target.membership_id, ["finance"])  # no identity.role.manage
    with pytest.raises(Forbidden), UnitOfWork(admin_actor) as uow:
        provisioning.assign_roles(uow, admin.membership_id, ["sales"])  # own roles
    with UnitOfWork(admin_actor) as uow:
        assert provisioning.assign_roles(uow, target.membership_id, ["finance"])
    with UnitOfWork(admin_actor) as uow:
        provisioning.set_permission_override(
            uow, target.membership_id, permission_key="sales.quote.read", effect="grant", scope="company", reason="cover"
        )
    # a non-admin holding identity.permission.manage cannot grant beyond its own keys
    with UnitOfWork(admin_actor) as uow:
        provisioning.set_permission_override(
            uow, manager.membership_id, permission_key="identity.permission.manage", effect="grant", scope="company", reason="delegated admin"
        )
    manager_actor = actor_for(tenant.company_id, manager.user_id, "test")
    assert manager_actor is not None
    with pytest.raises(Forbidden) as exc, UnitOfWork(manager_actor) as uow:
        provisioning.set_permission_override(
            uow, target.membership_id, permission_key="sales.quote.delete", effect="grant", scope="company", reason="x"
        )
    assert exc.value.code == "permission_escalation"


def test_last_admin_cannot_lose_role_management(tenant: Tenant) -> None:
    admin = make_member(tenant, ["admin"])
    with pytest.raises(Conflict) as exc, UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.assign_roles(uow, admin.membership_id, ["management"])
    assert exc.value.code == "last_admin"
    with pytest.raises(Conflict), UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.set_permission_override(
            uow, admin.membership_id, permission_key="identity.role.manage", effect="revoke", reason="x"
        )
    second = make_member(tenant, ["admin"])
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert provisioning.assign_roles(uow, admin.membership_id, ["management"])
    assert actor_for(tenant.company_id, second.user_id, "test") is not None


def test_cache_follows_the_epoch(tenant: Tenant) -> None:
    member = make_member(tenant, ["sales"])
    before = actor_for(tenant.company_id, member.user_id, "test")
    assert before is not None and "finance.invoice.read" not in before.permissions
    with UnitOfWork(system(tenant.company_id)) as uow:
        provisioning.assign_roles(uow, member.membership_id, ["finance"])
    after = actor_for(tenant.company_id, member.user_id, "test")
    assert after is not None
    assert after.authz_epoch == before.authz_epoch + 1
    assert "finance.invoice.read" in after.permissions and "sales.quote.create" not in after.permissions


def test_archiving_an_override_and_leaving_a_team_take_effect(tenant: Tenant) -> None:
    with UnitOfWork(system(tenant.company_id)) as uow:
        team = provisioning.ensure_team(uow, team_key="T-TWO", name="Team two")
    member = make_member(tenant, ["sales"], teams=[TeamSeat(team)])
    peer = make_member(tenant, ["sales"], teams=[TeamSeat(team)])
    with UnitOfWork(system(tenant.company_id)) as uow:
        override_id = provisioning.set_permission_override(
            uow, member.membership_id, permission_key="sales.quote.read", effect="revoke", reason="temporary"
        )
    revoked = actor_for(tenant.company_id, member.user_id, "test")
    assert revoked is not None and "sales.quote.read" not in revoked.permissions
    assert revoked.team_peer_user_ids == {peer.user_id}
    with UnitOfWork(system(tenant.company_id)) as uow:
        assert provisioning.archive_permission_override(uow, override_id)
        assert not provisioning.archive_permission_override(uow, override_id)  # already archived
        assert provisioning.remove_team_member(uow, team, peer.membership_id)
    restored = actor_for(tenant.company_id, member.user_id, "test")
    assert restored is not None and restored.permissions["sales.quote.read"] == Scope.OWN
    assert restored.team_peer_user_ids == frozenset()
    with UnitOfWork(system(tenant.company_id)) as uow:
        events = [
            (e.payload["permission_key"], e.payload["effect"], e.payload["archived"])
            for e in uow.session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == "identity.permission_override.changed")
                .order_by(DomainEvent.seq)
            )
        ]
    assert events == [("sales.quote.read", "revoke", False), ("sales.quote.read", "revoke", True)]
