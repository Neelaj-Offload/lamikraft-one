"""Building the server-side ActorContext of a member from the database.

Used by the HTTP session resolver, ``app.platform.authz.actors.actor_for_member`` (jobs, briefings, agents,
channels) and the job runtime. An inactive membership, a disabled user or a suspended company yields no
actor. Effective access comes from :mod:`app.platform.identity.access` (cached per membership and epoch);
profile fields (display name, zone, locale) are read fresh on every build.

Zone resolution (conventions §7): user preference → user → membership → default branch → company →
``Asia/Kolkata``. Locale: user preference → user → company.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db.engine import session_factory
from app.platform.authz.context import ActorContext, AuthStrength, Channel
from app.platform.authz.permissions import Scope
from app.platform.identity.access import (
    ACCESS_CACHE,
    AccessSnapshot,
    Override,
    next_expiry,
    resolve_permissions,
)
from app.platform.identity.models import (
    AppUser,
    Membership,
    MembershipBranch,
    MembershipRole,
    Role,
    RolePermission,
    UserPermissionOverride,
    UserPreference,
)
from app.platform.org.models import Branch, Company
from app.platform.org.teams import Team, TeamMember

FALLBACK_ZONE = "Asia/Kolkata"


def bind_tenant(session: Session, company_id: uuid.UUID | None, user_id: uuid.UUID | None = None) -> None:
    """Set the RLS GUCs transaction-locally (platform code; the UoW does the same on entry)."""
    session.execute(
        text("SELECT set_config('app.company_id', :c, true), set_config('app.user_id', :u, true)"),
        {"c": str(company_id) if company_id else "", "u": str(user_id) if user_id else ""},
    )


@contextmanager
def tenant_scope(session: Session, company_id: uuid.UUID | None, user_id: uuid.UUID | None = None) -> Iterator[None]:
    """Bind a tenant for a block and restore the previous GUC values afterwards.

    ``set_config(..., true)`` lasts until the end of the *transaction*, so a helper transaction that joins an
    outer one as a savepoint (test savepoint mode, or a caller's connection) must not leave its tenant behind.
    On an exception the enclosing savepoint/transaction rolls back, which restores the values by itself.
    """
    previous = session.execute(
        text("SELECT current_setting('app.company_id', true), current_setting('app.user_id', true)")
    ).one()
    bind_tenant(session, company_id, user_id)
    yield
    session.execute(
        text("SELECT set_config('app.company_id', :c, true), set_config('app.user_id', :u, true)"),
        {"c": previous[0] or "", "u": previous[1] or ""},
    )


def _zone_ok(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def resolve_time_zone(*candidates: str | None) -> str:
    for candidate in candidates:
        if ok := _zone_ok(candidate):
            return ok
    return _zone_ok(get_settings().default_time_zone) or FALLBACK_ZONE


def load_access(
    session: Session, company_id: uuid.UUID, membership_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
) -> AccessSnapshot:
    """Uncached resolution for one membership (the caller has bound the tenant)."""
    role_rows = session.execute(
        select(Role.role_key, RolePermission.permission_key, RolePermission.scope)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            Role.company_id == company_id,
            Role.archived_at.is_(None),
            RolePermission.effect == "grant",
            (Role.role_key == "employee")
            | Role.id.in_(select(MembershipRole.role_id).where(MembershipRole.membership_id == membership_id)),
        )
    ).all()
    per_role: dict[str, dict[str, Scope]] = {}
    for role_key, key, label in role_rows:
        per_role.setdefault(role_key, {})[key] = Scope.parse(label)
    assigned = list(
        session.scalars(
            select(Role.role_key)
            .join(MembershipRole, MembershipRole.role_id == Role.id)
            .where(MembershipRole.membership_id == membership_id, Role.archived_at.is_(None))
        )
    )
    overrides = [
        Override(key=o.permission_key, effect=o.effect, scope=Scope.parse(o.scope) if o.scope else None, expires_at=o.expires_at)
        for o in session.scalars(
            select(UserPermissionOverride).where(
                UserPermissionOverride.membership_id == membership_id, UserPermissionOverride.archived_at.is_(None)
            )
        )
    ]
    permissions = resolve_permissions(per_role.values(), overrides, now=now)
    branch_ids = set(
        session.scalars(
            select(MembershipBranch.branch_id)
            .join(Branch, Branch.id == MembershipBranch.branch_id)
            .where(MembershipBranch.membership_id == membership_id, Branch.archived_at.is_(None))
        )
    )
    my_teams = select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id).where(
        TeamMember.membership_id == membership_id, Team.archived_at.is_(None)
    )
    peers = set(
        session.scalars(
            select(Membership.user_id)
            .join(TeamMember, TeamMember.membership_id == Membership.id)
            .where(TeamMember.team_id.in_(my_teams), Membership.user_id != user_id)
            .distinct()
        )
    )
    return AccessSnapshot.build(permissions, assigned, branch_ids, peers, next_expiry(overrides, now=now))


def cached_access(
    session: Session, company_id: uuid.UUID, membership_id: uuid.UUID, user_id: uuid.UUID, epoch: int, *, now: datetime
) -> AccessSnapshot:
    snap = ACCESS_CACHE.get(membership_id, epoch, now)
    if snap is None:
        snap = load_access(session, company_id, membership_id, user_id, now=now)
        ACCESS_CACHE.put(membership_id, epoch, snap)
    return snap


def build_member_actor(
    session: Session,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    channel: Channel = "web",
    now: datetime | None = None,
    session_id: uuid.UUID | None = None,
    auth_strength: AuthStrength = "password",
    recent_auth_at: datetime | None = None,
) -> ActorContext | None:
    """The effective context of an active member, or None (the caller bound the tenant GUCs)."""
    company = session.get(Company, company_id)
    if company is None or company.status != "active":
        return None
    membership = session.scalars(
        select(Membership).where(Membership.company_id == company_id, Membership.user_id == user_id)
    ).first()
    if membership is None or membership.status != "active":
        return None
    user = session.get(AppUser, user_id)
    if user is None or user.status != "active":
        return None
    now = now or get_clock(company_id).now()
    access = cached_access(session, company_id, membership.id, user_id, int(company.authz_epoch), now=now)
    prefs = session.get(UserPreference, user_id)
    locale_prefs: dict[str, Any] = dict(prefs.locale) if prefs is not None and prefs.locale else {}
    branch_zone = None
    if membership.default_branch_id is not None:
        branch_zone = session.scalar(select(Branch.time_zone).where(Branch.id == membership.default_branch_id))
    zone = resolve_time_zone(
        locale_prefs.get("time_zone"), user.time_zone, membership.work_time_zone, branch_zone, company.default_time_zone
    )
    locale = locale_prefs.get("locale") or user.locale or company.default_locale
    return ActorContext(
        actor_type="user",
        company_id=company_id,
        user_id=user_id,
        membership_id=membership.id,
        display_name=user.display_name,
        branch_ids=access.branch_ids,
        team_peer_user_ids=access.team_peer_user_ids,
        permissions=access.permissions,
        session_id=session_id,
        auth_strength=auth_strength,
        recent_auth_at=recent_auth_at,
        channel=channel,
        locale=locale,
        time_zone=zone,
        authz_epoch=int(company.authz_epoch),
    )


def actor_for(company_id: uuid.UUID, user_id: uuid.UUID, channel: Channel = "job") -> ActorContext | None:
    """Standalone builder (own short transaction); registered as the member actor builder."""
    with session_factory()() as session, session.begin(), tenant_scope(session, company_id, user_id):
        return build_member_actor(session, company_id, user_id, channel=channel, now=get_clock(company_id).now())


def actor_for_job(_session: Session, job: Any) -> ActorContext:
    """Job runtime hook for ``run_as="user"`` jobs: rebuild the enqueuing user's context at execution time."""
    from app.core.errors import PermanentJobError

    if job.company_id is None or job.actor_user_id is None:
        raise PermanentJobError("user job without company or actor")
    actor = actor_for(job.company_id, job.actor_user_id, "job")
    if actor is None:
        raise PermanentJobError("the job's actor no longer has an active membership")
    return actor.with_(correlation_id=job.correlation_id)
