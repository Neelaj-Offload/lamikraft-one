"""The identity part of the canonical world (fixtures.md §2-§3): structure, people, Arjun's activation, idempotency."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.platform.authz.permissions import Scope
from app.platform.events.models import DomainEvent
from app.platform.identity.actors import actor_for
from app.platform.identity.models import AppUser, Membership, MembershipRole, Role
from app.platform.org.models import Branch, Company
from app.platform.org.teams import Team, TeamMember
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.runner import last_world, run_demo_seed
from app.seed.world import keys
from tests.integration.identity.fixtures import count, make_tenant, system

pytestmark = pytest.mark.db

SLICE_1_PEOPLE = sorted(k for k, p in keys.PEOPLE.items() if p.slice_no == 1)


def _membership(ctx: SeedContext, key: str) -> Membership:
    with UnitOfWork(system(ctx.company_id)) as uow:
        return uow.session.scalars(select(Membership).where(Membership.user_id == ctx.refs[key])).one()


def test_demo_company_branches_and_teams(world: SeedContext) -> None:
    with UnitOfWork(system(world.company_id)) as uow:
        company = uow.session.get(Company, world.company_id)
        assert company is not None
        assert (company.company_key, company.legal_name, company.display_name) == (
            keys.COMPANY_KEY,
            keys.COMPANY_LEGAL_NAME,
            keys.COMPANY_DISPLAY_NAME,
        )
        assert company.is_demo and company.default_time_zone == keys.ZONE and company.base_currency == "INR"
        branches = {b.branch_code: b for b in uow.session.scalars(select(Branch))}
        assert set(branches) == {keys.BRANCHES.HO, keys.BRANCHES.FAC}
        assert branches[keys.BRANCHES.HO].is_head_office and not branches[keys.BRANCHES.FAC].is_head_office
        teams = {t.team_key: t for t in uow.session.scalars(select(Team))}
        assert set(teams) == {keys.TEAMS.EXP_SALES, keys.TEAMS.OPS_HO}
        seats = uow.session.execute(
            select(Team.team_key, Membership.user_id, TeamMember.team_role)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .join(Membership, Membership.id == TeamMember.membership_id)
        ).all()
    by_user = {v: k for k, v in world.refs.items()}
    roster = {(team, by_user[user], role) for team, user, role in seats}
    assert roster == {
        (keys.TEAMS.EXP_SALES, "SAHIL", "lead"),
        (keys.TEAMS.EXP_SALES, "MEERA", "member"),
        (keys.TEAMS.EXP_SALES, "NEHA", "member"),
        (keys.TEAMS.EXP_SALES, "ARJUN", "member"),
        (keys.TEAMS.OPS_HO, "RAVI", "lead"),
        (keys.TEAMS.OPS_HO, "KABIR", "member"),
    }


def test_people_roles_managers_and_refs(world: SeedContext) -> None:
    # other seeds (org calendar, parties, ...) add their own refs; Vikram is a Slice-2 person
    assert sorted(k for k in world.refs if k in keys.PEOPLE) == SLICE_1_PEOPLE
    with UnitOfWork(system(world.company_id)) as uow:
        rows = uow.session.execute(
            select(AppUser.email, AppUser.display_name, AppUser.password_hash, Membership.status, Role.role_key, Membership.manager_membership_id, Membership.id, Membership.user_id)
            .join(Membership, Membership.user_id == AppUser.id)
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .join(Role, Role.id == MembershipRole.role_id)
        ).all()
    by_user = {r.user_id: r for r in rows}
    membership_of = {key: by_user[world.refs[key]].id for key in world.refs if key in keys.PEOPLE}
    for key in SLICE_1_PEOPLE:
        person, row = keys.PEOPLE[key], by_user[world.refs[key]]
        assert row.email == person.email and row.display_name == person.name
        assert row.password_hash is None  # demo users sign in only through one-time links
        assert row.status == "active"
        assert row.role_key == person.role_template
        expected_manager = membership_of[person.manager] if person.manager else None
        assert row.manager_membership_id == expected_manager


def test_arjun_activated_at_d0_0800_with_event(world: SeedContext) -> None:
    arjun = _membership(world, "ARJUN")
    sahil = _membership(world, "SAHIL")
    with UnitOfWork(system(world.company_id)) as uow:
        events = list(
            uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "identity.membership.activated"))
        )
    assert len(events) == 1
    event = events[0]
    assert event.aggregate_id == arjun.id
    assert event.occurred_at == keys.CLOCK_D0 - timedelta(minutes=55)  # 08:00 IST = 02:30Z
    assert event.payload == {
        "membership_id": str(arjun.id),
        "user_id": str(world.refs["ARJUN"]),
        "manager_membership_id": str(sahil.id),
        "origin": "seed",
    }
    assert arjun.joined_on == keys.CLOCK_D0.date()


def test_seeded_scopes_resolve_per_persona(world: SeedContext) -> None:
    meera = actor_for(world.company_id, world.refs["MEERA"], "test")
    sahil = actor_for(world.company_id, world.refs["SAHIL"], "test")
    ravi = actor_for(world.company_id, world.refs["RAVI"], "test")
    kabir = actor_for(world.company_id, world.refs["KABIR"], "test")
    assert meera and sahil and ravi and kabir
    assert meera.permissions["sales.quote.read"] == Scope.OWN
    assert sahil.permissions["sales.quote.read"] == Scope.COMPANY
    assert ravi.permissions["tasks.task.read"] == Scope.BRANCH
    assert ravi.branch_ids == {uuid.UUID(world.facts["branches"][keys.BRANCHES.HO])}
    assert world.refs["KABIR"] in ravi.team_peer_user_ids
    assert {world.refs["MEERA"], world.refs["NEHA"], world.refs["ARJUN"]} <= sahil.team_peer_user_ids
    assert not any(k.startswith("sales.") for k in kabir.permissions)
    assert meera.time_zone == keys.ZONE and meera.locale == "en-IN"


def test_reseeding_is_idempotent(world: SeedContext) -> None:
    before = {
        "users": count(AppUser),
        "memberships": count(Membership, world.company_id),
        "roles": count(Role, world.company_id),
        "events": count(DomainEvent),
        "teams": count(TeamMember, world.company_id),
    }
    again = run_demo_seed(slice_max=1)
    assert again.company_id == world.company_id
    assert again.refs == world.refs
    after = {
        "users": count(AppUser),
        "memberships": count(Membership, world.company_id),
        "roles": count(Role, world.company_id),
        "events": count(DomainEvent),
        "teams": count(TeamMember, world.company_id),
    }
    assert after == before


def test_slice_two_adds_vikram(world: SeedContext) -> None:
    ctx = run_demo_seed(slice_max=2)
    assert "VIKRAM" in ctx.refs
    vikram = _membership(ctx, "VIKRAM")
    ravi = _membership(ctx, "RAVI")
    assert vikram.manager_membership_id == ravi.id


def test_last_world_exposes_refs(world: SeedContext) -> None:
    summary = last_world()
    assert summary is not None
    assert summary["company_id"] == str(world.company_id)
    assert summary["refs"] == {k: str(v) for k, v in world.refs.items()}


def test_refuses_to_seed_into_a_non_demo_company(db: None) -> None:
    make_tenant(keys.COMPANY_KEY, is_demo=False)
    with pytest.raises(RuntimeError, match="not a demo company"):
        run_demo_seed(slice_max=1)
