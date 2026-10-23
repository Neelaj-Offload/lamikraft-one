"""Provisioning and access administration: companies, branches, teams, users, memberships, roles, overrides.

Every function takes a :class:`UnitOfWork`. System, CLI and seed actors may provision freely; a user actor
needs the documented permission (``identity.user.manage``, ``identity.role.manage``,
``identity.permission.manage``, ``org.team.manage``) and is bound by the anti-escalation rules of
permissions.md §10: grant only keys you hold, at no more than your own scope, never to your own membership,
and never remove the last active holder of ``identity.role.manage`` at company scope.

Any change to roles, overrides, memberships, teams or branches increments ``company.authz_epoch`` in the same
transaction and emits ``identity.membership.access_changed``. Business keys make every ``ensure_*`` idempotent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select, update

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.authz.permissions import Scope
from app.platform.identity.access import Override, resolve_permissions
from app.platform.identity.models import (
    AppUser,
    Membership,
    MembershipBranch,
    MembershipRole,
    OverrideEffect,
    Permission,
    Role,
    RolePermission,
    UserPermissionOverride,
)
from app.platform.identity.tokens import normalize_email
from app.platform.org.models import Branch, Company
from app.platform.org.teams import Team, TeamMember, TeamRole

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

ACTIVE = "active"
INVITED = "invited"


# ---- authority helpers -----------------------------------------------------------------------------
def _is_privileged(uow: UnitOfWork) -> bool:
    actor = uow.actor
    return actor.is_system or actor.actor_type in ("cli", "system")


def _require(uow: UnitOfWork, key: str) -> None:
    if not _is_privileged(uow):
        uow.actor.require(key, Scope.COMPANY)


def bump_authz_epoch(uow: UnitOfWork) -> int:
    company_id = uow.actor.company_id
    if company_id is None:
        raise RuntimeError("authz epoch changes need a company-bound unit of work")
    epoch = uow.session.execute(
        update(Company).where(Company.id == company_id).values(authz_epoch=Company.authz_epoch + 1).returning(Company.authz_epoch)
    ).scalar_one()
    return int(epoch)


def access_changed(
    uow: UnitOfWork,
    membership_ids: Iterable[uuid.UUID],
    change_kinds: Sequence[str],
    *,
    origin: str | None = None,
    all_members: bool = False,
) -> int:
    """Bump the company epoch once and emit ``identity.membership.access_changed`` per membership."""
    ids = set(membership_ids)
    if all_members:
        ids |= set(uow.session.scalars(select(Membership.id).where(Membership.company_id == uow.actor.company_id)))
    epoch = bump_authz_epoch(uow)
    if not ids:
        return epoch
    rows = uow.session.execute(select(Membership.id, Membership.user_id).where(Membership.id.in_(ids))).all()
    for membership_id, user_id in sorted(rows):
        payload: dict[str, object] = {
            "membership_id": str(membership_id),
            "user_id": str(user_id),
            "authz_epoch": epoch,
            "change_kinds": sorted(set(change_kinds)),
        }
        if origin:
            payload["origin"] = origin
        uow.emit("identity.membership.access_changed", aggregate_id=membership_id, payload=payload)
    return epoch


def valid_time_zone(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed(code="validation_failed", errors=[{"loc": ["time_zone"], "msg": "Unknown time zone", "code": "unknown_time_zone"}]) from None
    return name


# ---- company, branches, teams ----------------------------------------------------------------------
@dataclass(frozen=True)
class CompanySpec:
    company_key: str
    legal_name: str
    display_name: str
    is_demo: bool = False
    country: str = "IN"
    base_currency: str = "INR"
    time_zone: str = "Asia/Kolkata"
    locale: str = "en-IN"


def ensure_company(uow: UnitOfWork, spec: CompanySpec) -> tuple[uuid.UUID, bool]:
    """Find or create a company by key (``company`` is RLS-exempt). Returns (id, created)."""
    if not _is_privileged(uow):
        raise Forbidden(code="permission_denied", permission="org.company.update")
    existing = uow.session.scalars(select(Company).where(Company.company_key == spec.company_key)).first()
    if existing is not None:
        return existing.id, False
    valid_time_zone(spec.time_zone)
    company = Company(
        id=uuid.uuid7(),
        company_key=spec.company_key,
        legal_name=spec.legal_name,
        display_name=spec.display_name,
        is_demo=spec.is_demo,
        country=spec.country,
        base_currency=spec.base_currency,
        default_time_zone=spec.time_zone,
        default_locale=spec.locale,
        status="active",
        authz_epoch=0,
    )
    uow.add(company)
    uow.flush()
    return company.id, True


def ensure_branch(
    uow: UnitOfWork, *, code: str, name: str, is_head_office: bool = False, time_zone: str | None = None
) -> uuid.UUID:
    if not _is_privileged(uow):
        uow.actor.require("org.branch.manage", Scope.COMPANY)
    company_id = uow.actor.company_id
    existing = uow.session.scalars(
        select(Branch).where(Branch.company_id == company_id, Branch.branch_code == code)
    ).first()
    if existing is not None:
        return existing.id
    branch = Branch(
        id=uuid.uuid7(),
        company_id=company_id,
        branch_code=code,
        name=name,
        is_head_office=is_head_office,
        time_zone=valid_time_zone(time_zone),
    )
    uow.add(branch)
    uow.flush()
    return branch.id


def ensure_team(uow: UnitOfWork, *, team_key: str, name: str, branch_id: uuid.UUID | None = None) -> uuid.UUID:
    _require(uow, "org.team.manage")
    company_id = uow.actor.company_id
    existing = uow.session.scalars(select(Team).where(Team.company_id == company_id, Team.team_key == team_key)).first()
    if existing is not None:
        return existing.id
    team = Team(id=uuid.uuid7(), company_id=company_id, team_key=team_key, name=name, branch_id=branch_id)
    uow.add(team)
    uow.flush()
    return team.id


def add_team_member(
    uow: UnitOfWork,
    team_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    team_role: str = TeamRole.MEMBER.value,
    origin: str | None = None,
    emit: bool = True,
) -> bool:
    """Add (or change the role of) a team member. Returns True when something changed."""
    _require(uow, "org.team.manage")
    if team_role not in {r.value for r in TeamRole}:
        raise ValidationFailed("Unknown team role", code="validation_failed")
    _membership(uow, membership_id)
    if uow.session.get(Team, team_id) is None:
        raise NotFound(code="not_found", resource_type="org.team")
    row = uow.session.get(TeamMember, (team_id, membership_id))
    if row is not None and row.team_role == team_role:
        return False
    if row is None:
        uow.add(TeamMember(team_id=team_id, membership_id=membership_id, team_role=team_role, added_at=uow.now()))
    else:
        row.team_role = team_role
    uow.flush()
    if emit:
        access_changed(uow, [membership_id], ["teams"], origin=origin)
    return True


def remove_team_member(uow: UnitOfWork, team_id: uuid.UUID, membership_id: uuid.UUID, *, origin: str | None = None) -> bool:
    _require(uow, "org.team.manage")
    deleted = uow.session.execute(
        delete(TeamMember).where(TeamMember.team_id == team_id, TeamMember.membership_id == membership_id)
    ).rowcount  # type: ignore[attr-defined]
    if deleted:
        access_changed(uow, [membership_id], ["teams"], origin=origin)
    return bool(deleted)


# ---- users and memberships -------------------------------------------------------------------------
def ensure_user(
    uow: UnitOfWork,
    *,
    email: str,
    display_name: str,
    full_name: str | None = None,
    locale: str = "en-IN",
    time_zone: str | None = None,
    status: str = ACTIVE,
    password_hash: str | None = None,
) -> tuple[uuid.UUID, bool]:
    """Find a user by normalised email or create one (``app_user`` is global). Returns (id, created)."""
    _require(uow, "identity.user.manage")
    normalized = normalize_email(email)
    existing = uow.session.scalars(select(AppUser).where(AppUser.email_normalized == normalized)).first()
    if existing is not None:
        return existing.id, False
    user = AppUser(
        id=uuid.uuid7(),
        email=email.strip(),
        email_normalized=normalized,
        display_name=display_name,
        full_name=full_name or display_name,
        locale=locale,
        time_zone=valid_time_zone(time_zone),
        status=status,
        password_hash=password_hash,
        password_changed_at=uow.now() if password_hash else None,
    )
    uow.add(user)
    uow.flush()
    return user.id, True


def _membership(uow: UnitOfWork, membership_id: uuid.UUID) -> Membership:
    membership = uow.session.get(Membership, membership_id)
    if membership is None or membership.company_id != uow.actor.company_id:
        raise NotFound(code="not_found", resource_type="identity.membership")
    return membership


def membership_for_user(uow: UnitOfWork, user_id: uuid.UUID) -> Membership | None:
    return uow.session.scalars(
        select(Membership).where(Membership.company_id == uow.actor.company_id, Membership.user_id == user_id)
    ).first()


def roles_by_key(uow: UnitOfWork) -> dict[str, Role]:
    return {
        r.role_key: r
        for r in uow.session.scalars(
            select(Role).where(Role.company_id == uow.actor.company_id, Role.archived_at.is_(None))
        )
    }


@dataclass(frozen=True)
class TeamSeat:
    team_id: uuid.UUID
    team_role: str = TeamRole.MEMBER.value


def provision_membership(
    uow: UnitOfWork,
    *,
    user_id: uuid.UUID,
    status: str,
    role_keys: Sequence[str],
    branch_ids: Sequence[uuid.UUID] = (),
    default_branch_id: uuid.UUID | None = None,
    teams: Sequence[TeamSeat] = (),
    manager_membership_id: uuid.UUID | None = None,
    job_title: str | None = None,
    joined_on: date | None = None,
    origin: str | None = None,
) -> tuple[uuid.UUID, bool]:
    """Create a membership with roles, branches and teams in one transaction (idempotent per user).

    A membership created directly as ``active`` is a pre-existing member being provisioned; only the
    ``invited`` → ``active`` transition (:func:`activate_membership`) emits ``identity.membership.activated``.
    """
    _require(uow, "identity.user.manage")
    if status not in (ACTIVE, INVITED):
        raise ValidationFailed("A new membership is active or invited", code="validation_failed")
    existing = membership_for_user(uow, user_id)
    if existing is not None:
        return existing.id, False
    if not role_keys:
        raise ValidationFailed("A membership needs at least one role", code="validation_failed")
    roles = roles_by_key(uow)
    missing = [k for k in role_keys if k not in roles or not roles[k].is_assignable]
    if missing:
        raise ValidationFailed(f"Unknown or unassignable roles: {', '.join(missing)}", code="validation_failed")
    _check_role_grants_within_actor(uow, [roles[k] for k in role_keys])
    membership = Membership(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        user_id=user_id,
        status=status,
        job_title=job_title,
        manager_membership_id=manager_membership_id,
        default_branch_id=default_branch_id,
        joined_on=joined_on,
    )
    uow.add(membership)
    uow.flush()
    now = uow.now()
    for key in dict.fromkeys(role_keys):
        uow.add(MembershipRole(membership_id=membership.id, role_id=roles[key].id, assigned_by=uow.actor.user_id, assigned_at=now))
    branch_set = list(dict.fromkeys([*branch_ids, *([default_branch_id] if default_branch_id else [])]))
    for branch_id in branch_set:
        uow.add(MembershipBranch(membership_id=membership.id, branch_id=branch_id, assigned_at=now))
    uow.flush()
    for seat in teams:
        add_team_member(uow, seat.team_id, membership.id, team_role=seat.team_role, origin=origin, emit=False)
    access_changed(uow, [membership.id], ["roles", "branches", "teams", "status"], origin=origin)
    uow.audit(
        "identity.membership.provisioned",
        resource_type="identity.membership",
        resource_id=membership.id,
        details={"roles": sorted(set(role_keys)), "status": status, "origin": origin},
    )
    return membership.id, True


def activate_membership(uow: UnitOfWork, membership_id: uuid.UUID, *, origin: str | None = None) -> bool:
    """``invited`` → ``active``; activates the user too and emits ``identity.membership.activated``."""
    _require(uow, "identity.user.manage")
    membership = _membership(uow, membership_id)
    if membership.status == ACTIVE:
        return False
    if membership.status != INVITED:
        raise Conflict(f"A {membership.status} membership cannot be activated here", code="invalid_transition")
    membership.status = ACTIVE
    if membership.joined_on is None:
        membership.joined_on = uow.now().astimezone(ZoneInfo(_company(uow).default_time_zone)).date()
    user = uow.session.get(AppUser, membership.user_id)
    if user is not None and user.status == INVITED:
        user.status = ACTIVE
    uow.flush()
    payload: dict[str, object] = {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "manager_membership_id": str(membership.manager_membership_id) if membership.manager_membership_id else None,
    }
    if origin:
        payload["origin"] = origin
    uow.emit("identity.membership.activated", aggregate_id=membership.id, aggregate_version=membership.version, payload=payload)
    access_changed(uow, [membership.id], ["status"], origin=origin)
    uow.audit("identity.membership.activated", resource_type="identity.membership", resource_id=membership.id)
    return True


def _company(uow: UnitOfWork) -> Company:
    company = uow.session.get(Company, uow.actor.company_id)
    if company is None:
        raise NotFound(code="not_found", resource_type="org.company")
    return company


# ---- roles -----------------------------------------------------------------------------------------
def _role_grants(uow: UnitOfWork, role_ids: Iterable[uuid.UUID]) -> dict[str, Scope]:
    grants: dict[str, Scope] = {}
    rows = uow.session.execute(
        select(RolePermission.permission_key, RolePermission.scope).where(
            RolePermission.role_id.in_(list(role_ids)), RolePermission.effect == "grant"
        )
    ).all()
    for key, label in rows:
        scope = Scope.parse(label)
        grants[key] = max(grants.get(key, scope), scope)
    return grants


def _check_role_grants_within_actor(uow: UnitOfWork, roles: Sequence[Role]) -> None:
    if _is_privileged(uow):
        return
    uow.actor.require("identity.role.manage", Scope.COMPANY)
    for key, scope in _role_grants(uow, [r.id for r in roles]).items():
        held = uow.actor.permissions.get(key)
        if held is None or held < scope:
            raise Forbidden(code="permission_escalation", permission=key)


def _not_self(uow: UnitOfWork, membership: Membership) -> None:
    if not _is_privileged(uow) and membership.user_id == uow.actor.user_id:
        raise Forbidden("You cannot change your own access", code="self_access_change")


def assign_roles(uow: UnitOfWork, membership_id: uuid.UUID, role_keys: Sequence[str], *, origin: str | None = None) -> bool:
    """Replace a membership's roles (at least one). Returns True when the set changed."""
    _require(uow, "identity.role.manage")
    membership = _membership(uow, membership_id)
    _not_self(uow, membership)
    if not role_keys:
        raise ValidationFailed("A membership needs at least one role", code="validation_failed")
    roles = roles_by_key(uow)
    missing = [k for k in role_keys if k not in roles or not roles[k].is_assignable]
    if missing:
        raise ValidationFailed(f"Unknown or unassignable roles: {', '.join(missing)}", code="validation_failed")
    wanted = {roles[k].id for k in role_keys}
    current = set(uow.session.scalars(select(MembershipRole.role_id).where(MembershipRole.membership_id == membership_id)))
    if wanted == current:
        return False
    _check_role_grants_within_actor(uow, [roles[k] for k in role_keys])
    was_holder = _holds_role_manage(uow, membership)
    removed = current - wanted
    if removed:
        uow.session.execute(
            delete(MembershipRole).where(MembershipRole.membership_id == membership_id, MembershipRole.role_id.in_(removed))
        )
    now = uow.now()
    for role_id in wanted - current:
        uow.add(MembershipRole(membership_id=membership_id, role_id=role_id, assigned_by=uow.actor.user_id, assigned_at=now))
    uow.flush()
    _last_admin_guard(uow, membership, was_holder)
    access_changed(uow, [membership_id], ["roles"], origin=origin)
    uow.audit(
        "identity.membership.roles_changed",
        resource_type="identity.membership",
        resource_id=membership_id,
        changes={"roles": {"from": sorted(_keys(roles, current)), "to": sorted(set(role_keys))}},
    )
    return True


def _keys(roles: dict[str, Role], ids: set[uuid.UUID]) -> list[str]:
    return [k for k, r in roles.items() if r.id in ids]


def set_membership_branches(
    uow: UnitOfWork, membership_id: uuid.UUID, branch_ids: Sequence[uuid.UUID], *, origin: str | None = None
) -> bool:
    _require(uow, "identity.user.manage")
    membership = _membership(uow, membership_id)
    _not_self(uow, membership)
    wanted = set(branch_ids)
    valid = set(uow.session.scalars(select(Branch.id).where(Branch.id.in_(wanted), Branch.company_id == membership.company_id)))
    if valid != wanted:
        raise ValidationFailed("Unknown branch", code="validation_failed")
    current = set(uow.session.scalars(select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership_id)))
    if wanted == current:
        return False
    uow.session.execute(
        delete(MembershipBranch).where(MembershipBranch.membership_id == membership_id, MembershipBranch.branch_id.in_(current - wanted))
    )
    for branch_id in wanted - current:
        uow.add(MembershipBranch(membership_id=membership_id, branch_id=branch_id, assigned_at=uow.now()))
    uow.flush()
    access_changed(uow, [membership_id], ["branches"], origin=origin)
    return True


# ---- per-user overrides ----------------------------------------------------------------------------
def set_permission_override(
    uow: UnitOfWork,
    membership_id: uuid.UUID,
    *,
    permission_key: str,
    effect: str,
    reason: str,
    scope: Scope | str | None = None,
    expires_at: datetime | None = None,
    origin: str | None = None,
) -> uuid.UUID:
    """Grant or revoke one key for one membership (replaces the open override for that key)."""
    _require(uow, "identity.permission.manage")
    membership = _membership(uow, membership_id)
    _not_self(uow, membership)
    if effect not in {e.value for e in OverrideEffect}:
        raise ValidationFailed("effect must be grant or revoke", code="validation_failed")
    if not reason or not reason.strip():
        raise ValidationFailed("A reason is required", code="validation_failed")
    perm = uow.session.get(Permission, permission_key)
    if perm is None or perm.deprecated_at is not None:
        raise ValidationFailed("Unknown permission", code="validation_failed")
    parsed: Scope | None = None
    if effect == OverrideEffect.GRANT.value:
        if scope is None:
            raise ValidationFailed("A grant needs a scope", code="validation_failed")
        parsed = Scope.parse(scope)
        if parsed.label not in perm.allowed_scopes:
            raise ValidationFailed(f"{permission_key} does not allow {parsed.label} scope", code="validation_failed")
        if not _is_privileged(uow):
            held = uow.actor.permissions.get(permission_key)
            if held is None or held < parsed:
                raise Forbidden(code="permission_escalation", permission=permission_key)
    elif scope is not None:
        raise ValidationFailed("A revoke has no scope", code="validation_failed")
    if expires_at is not None and expires_at <= uow.now():
        raise ValidationFailed("expires_at must be in the future", code="validation_failed")
    now = uow.now()
    was_holder = _holds_role_manage(uow, membership)
    for open_row in uow.session.scalars(
        select(UserPermissionOverride).where(
            UserPermissionOverride.membership_id == membership_id,
            UserPermissionOverride.permission_key == permission_key,
            UserPermissionOverride.archived_at.is_(None),
        )
    ):
        open_row.archived_at = now
        open_row.archived_by = uow.actor.user_id
    uow.flush()
    row = UserPermissionOverride(
        id=uuid.uuid7(),
        company_id=membership.company_id,
        membership_id=membership_id,
        permission_key=permission_key,
        effect=effect,
        scope=parsed.label if parsed else None,
        reason=reason.strip()[:500],
        expires_at=expires_at,
        created_by=uow.actor.user_id,
    )
    uow.add(row)
    uow.flush()
    _last_admin_guard(uow, membership, was_holder)
    _override_events(uow, membership, permission_key, effect, archived=False, origin=origin)
    uow.audit(
        "identity.permission_override.set",
        resource_type="identity.membership",
        resource_id=membership_id,
        reason=row.reason,
        details={"permission_key": permission_key, "effect": effect, "scope": row.scope},
    )
    return row.id


def archive_permission_override(uow: UnitOfWork, override_id: uuid.UUID, *, origin: str | None = None) -> bool:
    _require(uow, "identity.permission.manage")
    row = uow.session.get(UserPermissionOverride, override_id)
    if row is None or row.company_id != uow.actor.company_id:
        raise NotFound(code="not_found", resource_type="identity.permission_override")
    membership = _membership(uow, row.membership_id)
    _not_self(uow, membership)
    if row.archived_at is not None:
        return False
    was_holder = _holds_role_manage(uow, membership)
    row.archived_at = uow.now()
    row.archived_by = uow.actor.user_id
    uow.flush()
    _last_admin_guard(uow, membership, was_holder)
    _override_events(uow, membership, row.permission_key, row.effect, archived=True, origin=origin)
    uow.audit(
        "identity.permission_override.archived",
        resource_type="identity.membership",
        resource_id=membership.id,
        details={"permission_key": row.permission_key, "effect": row.effect},
    )
    return True


def _override_events(
    uow: UnitOfWork, membership: Membership, key: str, effect: str, *, archived: bool, origin: str | None
) -> None:
    payload: dict[str, object] = {
        "membership_id": str(membership.id),
        "permission_key": key,
        "effect": effect,
        "archived": archived,
    }
    if origin:
        payload["origin"] = origin
    uow.emit("identity.permission_override.changed", aggregate_id=membership.id, payload=payload)
    access_changed(uow, [membership.id], ["overrides"], origin=origin)


# ---- effective permissions from the database -------------------------------------------------------
def effective_permissions(uow: UnitOfWork, membership_id: uuid.UUID) -> dict[str, Scope]:
    """Resolve a membership's effective permissions now (no cache): empty for an inactive membership."""
    membership = uow.session.get(Membership, membership_id)
    if membership is None or membership.status != ACTIVE:
        return {}
    from app.platform.identity.actors import load_access

    return dict(load_access(uow.session, membership.company_id, membership.id, membership.user_id, now=uow.now()).permissions)


def _holds_role_manage(uow: UnitOfWork, membership: Membership) -> bool:
    from app.platform.identity.actors import load_access

    if membership.status != ACTIVE:
        return False
    perms = load_access(uow.session, membership.company_id, membership.id, membership.user_id, now=uow.now()).permissions
    return perms.get("identity.role.manage") == Scope.COMPANY


def _last_admin_guard(uow: UnitOfWork, changed: Membership, was_holder: bool) -> None:
    """Refuse a change that removes ``identity.role.manage@company`` from the last active member holding it."""
    if not was_holder or _holds_role_manage(uow, changed):
        return
    others = uow.session.scalars(
        select(Membership).where(
            Membership.company_id == changed.company_id, Membership.status == ACTIVE, Membership.id != changed.id
        )
    )
    if any(_holds_role_manage(uow, m) for m in others):
        return
    raise Conflict("At least one active member must keep role management", code="last_admin")


__all__ = [
    "ACTIVE",
    "INVITED",
    "CompanySpec",
    "Override",
    "TeamSeat",
    "access_changed",
    "activate_membership",
    "add_team_member",
    "archive_permission_override",
    "assign_roles",
    "bump_authz_epoch",
    "effective_permissions",
    "ensure_branch",
    "ensure_company",
    "ensure_team",
    "ensure_user",
    "membership_for_user",
    "provision_membership",
    "remove_team_member",
    "resolve_permissions",
    "roles_by_key",
    "set_membership_branches",
    "set_permission_override",
]
