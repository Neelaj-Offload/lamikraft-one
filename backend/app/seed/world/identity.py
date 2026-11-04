"""Identity part of the canonical fixture world (docs/architecture/fixtures.md §2-§3): SeedDefs ``identity``
(order 10) and ``identity.activation`` (order 75).

Created through the identity provisioning services as the seed actor (events carry ``origin=seed``):
- company ``crown-demo`` (created by the runner when absent), its system role templates, branches HO and FAC;
- teams EXP-SALES (lead Sahil; Meera, Neha, Arjun) and OPS-HO (lead Ravi; Kabir, and Vikram from Slice 2);
- the people of §3 with their role templates, branch HO and managers; Vikram only when ``slice_max >= 2``;
- Arjun is invited at D−3 10:00 (order 10) and his membership is activated at **D0 08:00** by the second SeedDef
  (order 75), emitting ``identity.membership.activated`` (onboarding and the manager check-in follow from it).
Pre-existing staff are provisioned active at the company set-up time, so they get no onboarding.
Every person is stored in ``SeedContext.refs`` under its ``keys.PEOPLE`` key (value: user id); memberships,
branches and teams are in ``SeedContext.facts``. Re-running is idempotent on emails, codes and keys.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock
from app.platform.authz.context import ActorContext
from app.platform.identity import provisioning, roles
from app.platform.identity.provisioning import CompanySpec, TeamSeat
from app.platform.org.teams import TeamRole
from app.platform.uow import UnitOfWork
from app.seed.context import D0, SeedContext
from app.seed.world import keys

ORIGIN = "seed"
IST = ZoneInfo(keys.ZONE)

BRANCH_NAMES = {keys.BRANCHES.HO: "Head Office", keys.BRANCHES.FAC: "Factory"}
TEAM_NAMES = {keys.TEAMS.EXP_SALES: "Export Sales", keys.TEAMS.OPS_HO: "Operations HO"}
#: managers first so their memberships exist when reports are provisioned
PROVISION_ORDER = ("PRIYA", "SAHIL", "RAVI", "MEERA", "NEHA", "KABIR", "ANANYA", "VIKRAM", "DEEPA", "ARJUN")


def demo_company_spec() -> CompanySpec:
    return CompanySpec(
        company_key=keys.COMPANY_KEY,
        legal_name=keys.COMPANY_LEGAL_NAME,
        display_name=keys.COMPANY_DISPLAY_NAME,
        is_demo=True,
        country="IN",
        base_currency="INR",
        time_zone=keys.ZONE,
        locale="en-IN",
    )


def d0_for(anchor: date | None) -> datetime:
    """D0 is the anchor date at 08:55 in the company zone (fixtures.md §1 rule 5)."""
    if anchor is None:
        return D0
    return datetime.combine(anchor, time(8, 55), IST)


def setup_time(d0: datetime) -> datetime:
    """When the demo company, its structure and its existing staff were set up (before any business fact)."""
    return datetime.combine((d0 - timedelta(days=200)).date(), time(9, 0), IST)


def arjun_invited_at(d0: datetime) -> datetime:
    return datetime.combine((d0 - timedelta(days=3)).date(), time(10, 0), IST)


def arjun_activated_at(d0: datetime) -> datetime:
    return datetime.combine(d0.date(), time(8, 0), IST)


def _seed_actor(company_id: uuid.UUID | None) -> ActorContext:
    return ActorContext.system(company_id, reason="seed:identity")


def ensure_demo_company(clock: FrozenClock, d0: datetime) -> uuid.UUID:
    """Create ``crown-demo`` (at set-up time) only when absent; refuse to seed into a non-demo company."""
    from sqlalchemy import select

    from app.platform.org.models import Company

    with UnitOfWork(_seed_actor(None), clock=clock) as uow:
        existing = uow.session.scalars(select(Company).where(Company.company_key == keys.COMPANY_KEY)).first()
        if existing is not None:
            if not existing.is_demo:
                raise RuntimeError(f"company {keys.COMPANY_KEY!r} exists and is not a demo company; refusing to seed")
            return existing.id
    clock.set(setup_time(d0))
    with UnitOfWork(_seed_actor(None), clock=clock) as uow:
        roles.sync_permission_catalogue(uow)
        company_id, _ = provisioning.ensure_company(uow, demo_company_spec())
    return company_id


def seed_identity(ctx: SeedContext) -> None:
    d0: datetime = ctx.facts.get("d0", D0)
    company_id = ctx.company_id
    clock = ctx.clock

    ctx.at(setup_time(d0))
    with UnitOfWork(_seed_actor(None), clock=clock) as uow:
        roles.sync_permission_catalogue(uow)
    with UnitOfWork(_seed_actor(company_id), clock=clock) as uow:
        roles.ensure_system_roles(uow, company_id, origin=ORIGIN)
        branches = {
            keys.BRANCHES.HO: provisioning.ensure_branch(
                uow, code=keys.BRANCHES.HO, name=BRANCH_NAMES[keys.BRANCHES.HO], is_head_office=True
            ),
            keys.BRANCHES.FAC: provisioning.ensure_branch(uow, code=keys.BRANCHES.FAC, name=BRANCH_NAMES[keys.BRANCHES.FAC]),
        }
        teams = {
            team_key: provisioning.ensure_team(uow, team_key=team_key, name=name, branch_id=branches[keys.BRANCHES.HO])
            for team_key, name in TEAM_NAMES.items()
        }
    ctx.facts["branches"] = {code: str(i) for code, i in branches.items()}
    ctx.facts["teams"] = {key: str(i) for key, i in teams.items()}
    memberships: dict[str, uuid.UUID] = {}

    for key in PROVISION_ORDER:
        person = keys.PEOPLE[key]
        if person.slice_no > ctx.slice_max:
            continue
        new_hire = key == "ARJUN"
        ctx.at(arjun_invited_at(d0) if new_hire else setup_time(d0))
        with UnitOfWork(_seed_actor(None), clock=clock) as uow:
            user_id, _ = provisioning.ensure_user(
                uow,
                email=person.email,
                display_name=person.name,
                full_name=person.name,
                locale="en-IN",
                status="invited" if new_hire else "active",
            )
        with UnitOfWork(_seed_actor(company_id), clock=clock) as uow:
            seats = []
            if person.team is not None:
                lead = keys.TEAM_LEADS.get(person.team) == key
                seats.append(TeamSeat(teams[person.team], TeamRole.LEAD.value if lead else TeamRole.MEMBER.value))
            membership_id, _ = provisioning.provision_membership(
                uow,
                user_id=user_id,
                status="invited" if new_hire else "active",
                role_keys=[person.role_template],
                branch_ids=[branches[person.branch]],
                default_branch_id=branches[person.branch],
                teams=seats,
                manager_membership_id=memberships.get(person.manager) if person.manager else None,
                joined_on=None if new_hire else setup_time(d0).date(),
                origin=ORIGIN,
            )
        memberships[key] = membership_id
        ctx.refs[key] = user_id

    ctx.facts["memberships"] = {key: str(i) for key, i in memberships.items()}


def seed_activation(ctx: SeedContext) -> None:
    """SeedDef ``identity.activation`` (order 75): Arjun's membership becomes active at D0 08:00.

    It runs after the history seeds (parties 20 … approvals 60), so the activation event and the onboarding it
    starts come after the business history they describe, and before tasks/briefings (80), which assign Arjun's
    walkthrough task at D0 08:05 and include his onboarding in the D0 briefing. Idempotent: an already active
    membership is left alone.
    """
    d0: datetime = ctx.facts.get("d0", D0)
    membership_id = (ctx.facts.get("memberships") or {}).get("ARJUN")
    if membership_id is None:
        return
    ctx.at(arjun_activated_at(d0))
    with UnitOfWork(_seed_actor(ctx.company_id), clock=ctx.clock) as uow:
        provisioning.activate_membership(uow, uuid.UUID(membership_id), origin=ORIGIN)
