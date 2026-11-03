"""User administration: the member list and detail, profile edits, roles, branches, deactivation, reactivation.

Users are never hard-deleted. Deactivation revokes sessions and open links at once and keeps attribution
("Name (inactive)"); reactivation restores the membership with its roles. Every change is audited with a diff and
access changes bump the authz epoch (``identity.membership.access_changed``). Reads need ``identity.user.read``;
changes ``identity.user.manage`` (roles: ``identity.role.manage``), all MFA + recent auth (permissions.md §6).
Anti-escalation, the self-change ban and the last-admin guard are enforced by :mod:`provisioning`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.identity import credentials, mfa, provisioning
from app.platform.identity.credential_models import MfaFactor
from app.platform.identity.models import AppUser, Membership, MembershipBranch, MembershipRole, Role
from app.platform.identity.schemas import (
    BranchRef,
    CapabilityView,
    DeactivateBody,
    ManagerRef,
    RoleRef,
    TeamRef,
    UserDetail,
    UserList,
    UserListItem,
    UserUpdate,
)
from app.platform.org.models import Branch
from app.platform.org.teams import Team, TeamMember
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

USER_READ = "identity.user.read"
USER_MANAGE = "identity.user.manage"
ROLE_MANAGE = "identity.role.manage"
PERMISSION_MANAGE = "identity.permission.manage"
MFA_MANAGE = "identity.mfa.manage"
SESSION_MANAGE = "identity.session.manage"
STATUSES = ("invited", "active", "suspended", "deactivated")


def _require_read(actor: ActorContext) -> None:
    if not (actor.can(USER_READ, Scope.COMPANY) or actor.can(USER_MANAGE, Scope.COMPANY)):
        raise Forbidden(code="permission_denied", permission=USER_READ)


def display(name: str, status: str) -> str:
    return f"{name} (inactive)" if status == "deactivated" else name


def _roles_of(uow: UnitOfWork, membership_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[RoleRef]]:
    out: dict[uuid.UUID, list[RoleRef]] = {m: [] for m in membership_ids}
    if not membership_ids:
        return out
    rows = uow.session.execute(
        select(MembershipRole.membership_id, Role.role_key, Role.name)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(MembershipRole.membership_id.in_(membership_ids))
        .order_by(Role.name)
    ).all()
    for mid, key, name in rows:
        out[mid].append(RoleRef(key=key, name=name))
    return out


def _enrolled(uow: UnitOfWork, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    return set(
        uow.session.scalars(
            select(MfaFactor.user_id).where(
                MfaFactor.user_id.in_(user_ids), MfaFactor.disabled_at.is_(None), MfaFactor.confirmed_at.is_not(None)
            )
        )
    )


@query()
def list_users(
    uow: UnitOfWork,
    *,
    q: str | None = None,
    status: str | None = None,
    role_key: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> UserList:
    """Members of the company; filters (text, status, role) apply before paging."""
    _require_read(uow.actor)
    if status is not None and status not in STATUSES:
        raise ValidationFailed(errors=[{"loc": ["query", "status"], "msg": "unknown status", "code": "invalid_choice"}])
    stmt = (
        select(Membership, AppUser)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.company_id == uow.actor.company_id)
    )
    if status:
        stmt = stmt.where(Membership.status == status)
    if role_key:
        stmt = stmt.where(
            Membership.id.in_(
                select(MembershipRole.membership_id).join(Role, Role.id == MembershipRole.role_id).where(Role.role_key == role_key)
            )
        )
    for term in tokens(q or "", max_tokens=6):
        pattern = contains_pattern(term)
        stmt = stmt.where(
            or_(
                AppUser.display_name.ilike(pattern, escape=LIKE_ESCAPE),
                AppUser.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                AppUser.email_normalized.ilike(pattern, escape=LIKE_ESCAPE),
                Membership.job_title.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    total = uow.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    limit = max(1, min(limit, 200))
    rows = uow.session.execute(
        stmt.order_by(
            (Membership.status == "deactivated").asc(), func.lower(AppUser.display_name), Membership.id
        ).limit(limit).offset(max(0, offset))
    ).all()
    roles = _roles_of(uow, [m.id for m, _ in rows])
    enrolled = _enrolled(uow, [u.id for _, u in rows])
    return UserList(
        items=[
            UserListItem(
                user_id=u.id,
                membership_id=m.id,
                display_name=display(u.display_name, m.status),
                email=u.email,
                job_title=m.job_title,
                status=m.status,  # type: ignore[arg-type]
                roles=roles.get(m.id, []),
                mfa_enrolled=u.id in enrolled,
                last_login_at=u.last_login_at,
            )
            for m, u in rows
        ],
        total=int(total),
        limit=limit,
        offset=max(0, offset),
    )


def _membership(uow: UnitOfWork, user_id: uuid.UUID) -> Membership:
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    return membership


def _cap(allowed: bool, reason: str = "permission_denied") -> CapabilityView:
    return CapabilityView(allowed=allowed, reason_code=None if allowed else reason)


@query()
def get_user(uow: UnitOfWork, user_id: uuid.UUID) -> UserDetail:
    from app.platform.identity.service import _open_overrides

    actor = uow.actor
    _require_read(actor)
    membership = _membership(uow, user_id)
    user = uow.session.get(AppUser, user_id)
    assert user is not None  # noqa: S101 - referenced by the membership
    branches = uow.session.scalars(
        select(Branch)
        .join(MembershipBranch, MembershipBranch.branch_id == Branch.id)
        .where(MembershipBranch.membership_id == membership.id, Branch.archived_at.is_(None))
        .order_by(Branch.branch_code)
    ).all()
    teams = uow.session.execute(
        select(Team.id, Team.team_key, Team.name, TeamMember.team_role)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.membership_id == membership.id, Team.archived_at.is_(None))
        .order_by(Team.team_key)
    ).all()
    manager = None
    if membership.manager_membership_id is not None:
        row = uow.session.execute(
            select(AppUser.display_name, Membership.status)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.id == membership.manager_membership_id)
        ).first()
        if row is not None:
            manager = ManagerRef(membership_id=membership.manager_membership_id, display_name=display(row[0], row[1]))
    is_self = user_id == actor.user_id
    manage = actor.can(USER_MANAGE, Scope.COMPANY)
    active = membership.status == "active"
    deactivated = membership.status in ("deactivated", "suspended")
    self_reason = "self_access_change"
    return UserDetail(
        user_id=user.id,
        membership_id=membership.id,
        email=user.email,
        display_name=display(user.display_name, membership.status),
        full_name=user.full_name,
        job_title=membership.job_title,
        department=membership.department,
        status=membership.status,  # type: ignore[arg-type]
        roles=_roles_of(uow, [membership.id])[membership.id],
        branches=[BranchRef(id=b.id, code=b.branch_code, name=b.name, is_head_office=b.is_head_office) for b in branches],
        default_branch_id=membership.default_branch_id,
        teams=[TeamRef(id=i, key=k, name=n, team_role=r) for i, k, n, r in teams],
        manager=manager,
        mfa_enrolled=user.id in _enrolled(uow, [user.id]),
        mfa_required=active and mfa.member_requires_mfa(uow, membership.id, user.id),
        last_login_at=user.last_login_at,
        joined_on=membership.joined_on.isoformat() if membership.joined_on else None,
        deactivated_at=membership.deactivated_at,
        deactivation_reason=membership.deactivation_reason,
        invitations=credentials.invitations_of(uow, membership.id),
        overrides=_open_overrides(uow, membership.id),
        version=membership.version,
        is_self=is_self,
        capabilities={
            "update": _cap(manage),
            "assign_roles": _cap(actor.can(ROLE_MANAGE, Scope.COMPANY) and not is_self, self_reason if is_self else "permission_denied"),
            "manage_overrides": _cap(actor.can(PERMISSION_MANAGE, Scope.COMPANY) and not is_self, self_reason if is_self else "permission_denied"),
            "deactivate": _cap(manage and not is_self and not deactivated, self_reason if is_self else ("permission_denied" if not manage else "invalid_transition")),
            "reactivate": _cap(manage and not is_self and deactivated, "permission_denied" if not manage else "invalid_transition"),
            "reset_password": _cap(manage and not is_self and active, "permission_denied" if not manage else "invalid_transition"),
            "reset_mfa": _cap(actor.can(MFA_MANAGE, Scope.COMPANY) and not is_self, "permission_denied"),
            "end_sessions": _cap(actor.can(SESSION_MANAGE, Scope.COMPANY) and not is_self, "permission_denied"),
            "invite": _cap(manage and membership.status == "invited"),
        },
    )


@command(USER_MANAGE, at_least=Scope.COMPANY)
def update_user(uow: UnitOfWork, user_id: uuid.UUID, body: UserUpdate) -> UserDetail:
    """Profile fields of a member (optimistic: 409 with the current version when it moved)."""
    require_step_up(uow, USER_MANAGE)
    membership = _membership(uow, user_id)
    uow.session.refresh(membership, with_for_update=True)
    uow.expect_version(membership, body.expected_version)
    user = uow.session.get(AppUser, user_id, with_for_update=True)
    assert user is not None  # noqa: S101
    changes: dict[str, dict[str, object]] = {}

    def apply(obj: object, attr: str, value: object, label: str | None = None) -> None:
        current = getattr(obj, attr)
        if value != current:
            changes[label or attr] = {"from": str(current) if isinstance(current, uuid.UUID) else current, "to": str(value) if isinstance(value, uuid.UUID) else value}
            setattr(obj, attr, value)

    if body.display_name is not None:
        apply(user, "display_name", body.display_name.strip())
    if body.full_name is not None:
        apply(user, "full_name", body.full_name.strip() or None)
    if body.job_title is not None:
        apply(membership, "job_title", body.job_title.strip() or None)
    if body.department is not None:
        apply(membership, "department", body.department.strip() or None)
    if body.clear_manager:
        apply(membership, "manager_membership_id", None, "manager")
    elif body.manager_user_id is not None:
        manager = provisioning.membership_for_user(uow, body.manager_user_id)
        if manager is None or manager.id == membership.id:
            raise ValidationFailed(errors=[{"loc": ["body", "manager_user_id"], "msg": "Choose another member", "code": "invalid_manager"}])
        apply(membership, "manager_membership_id", manager.id, "manager")
    if body.default_branch_id is not None:
        held = set(uow.session.scalars(select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership.id)))
        if body.default_branch_id not in held:
            raise ValidationFailed(errors=[{"loc": ["body", "default_branch_id"], "msg": "Assign the branch first", "code": "branch_not_assigned"}])
        apply(membership, "default_branch_id", body.default_branch_id)
    if changes:
        membership.updated_at = uow.now()  # the membership version moves with any profile change
        uow.flush()
        uow.audit("identity.membership.updated", resource_type="identity.membership", resource_id=membership.id, changes=changes)
    return get_user(uow, user_id)


@command(ROLE_MANAGE, at_least=Scope.COMPANY)
def set_roles(uow: UnitOfWork, user_id: uuid.UUID, role_keys: list[str]) -> UserDetail:
    require_step_up(uow, ROLE_MANAGE)
    membership = _membership(uow, user_id)
    provisioning.assign_roles(uow, membership.id, role_keys)  # audited with a from/to diff
    return get_user(uow, user_id)


@command(USER_MANAGE, at_least=Scope.COMPANY)
def set_branches(uow: UnitOfWork, user_id: uuid.UUID, branch_ids: list[uuid.UUID]) -> UserDetail:
    require_step_up(uow, USER_MANAGE)
    membership = _membership(uow, user_id)
    before = sorted(str(b) for b in uow.session.scalars(select(MembershipBranch.branch_id).where(MembershipBranch.membership_id == membership.id)))
    if membership.default_branch_id is not None and membership.default_branch_id not in set(branch_ids):
        raise ValidationFailed(errors=[{"loc": ["body", "branch_ids"], "msg": "Keep the default branch or change it first", "code": "default_branch_removed"}])
    if provisioning.set_membership_branches(uow, membership.id, branch_ids):
        uow.audit(
            "identity.membership.branches_changed",
            resource_type="identity.membership",
            resource_id=membership.id,
            changes={"branches": {"from": before, "to": sorted(str(b) for b in branch_ids)}},
        )
    return get_user(uow, user_id)


@command(USER_MANAGE, at_least=Scope.COMPANY)
def deactivate(uow: UnitOfWork, user_id: uuid.UUID, body: DeactivateBody) -> UserDetail:
    require_step_up(uow, USER_MANAGE)
    membership = _membership(uow, user_id)
    reassign = None
    if body.reassign_to_user_id is not None:
        target = provisioning.membership_for_user(uow, body.reassign_to_user_id)
        if target is None:
            raise ValidationFailed(errors=[{"loc": ["body", "reassign_to_user_id"], "msg": "Unknown member", "code": "unknown_member"}])
        reassign = target.id
    provisioning.deactivate_membership(uow, membership.id, reason=body.reason, reassign_to_membership_id=reassign)
    from app.platform.identity.credential_models import Invitation

    for row in uow.session.scalars(
        select(Invitation).where(
            Invitation.membership_id == membership.id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None)
        )
    ):
        row.revoked_at = uow.now()
        row.revoked_by = uow.actor.user_id
        row.token_hash = None
    uow.flush()
    return get_user(uow, user_id)


@command(USER_MANAGE, at_least=Scope.COMPANY)
def reactivate(uow: UnitOfWork, user_id: uuid.UUID) -> UserDetail:
    require_step_up(uow, USER_MANAGE)
    membership = _membership(uow, user_id)
    provisioning.reactivate_membership(uow, membership.id)
    return get_user(uow, user_id)
