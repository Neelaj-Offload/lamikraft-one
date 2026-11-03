"""Custom roles with inheritance and deny, the permission catalogue, and the role simulator.

- System templates are read-only (409 ``role_immutable``). A custom role may inherit one role of the same company
  (no cycles, at most 4 roles in a chain) and holds ``grant`` and ``deny`` entries; a deny removes a key the role
  inherited from its own ancestors only.
- Validation: every key exists and is not deprecated; a grant's scope is one the key allows. Anti-escalation: the
  role's effective grants (after inheritance) never exceed what the acting administrator holds.
- A role cannot be archived while it is assigned or inherited by a live role.
- Every change bumps the company authz epoch, emits ``identity.role.created|updated|archived`` and
  ``identity.membership.access_changed`` for every holder of the role or of a role inheriting it, and is audited
  with a diff of the entries.

Writes need ``identity.role.manage`` (MFA + recent auth); reads ``identity.role.read`` (or the manage key).
The simulator (``identity.user.read`` or ``identity.role.read``) explains a member's effective permissions with
their sources ("why"), what was removed ("why not") and delegated reach.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import delete, func, select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.identity import provisioning, role_resolution
from app.platform.identity.models import (
    AppUser,
    Membership,
    MembershipRole,
    Permission,
    Role,
    RoleKind,
    RolePermission,
    UserPermissionOverride,
)
from app.platform.identity.schemas import (
    AccessCheck,
    CapabilityView,
    EffectiveAccess,
    EffectiveKey,
    PermissionCatalogue,
    PermissionInfo,
    RoleCreate,
    RoleDetail,
    RoleEntryIn,
    RoleEntryView,
    RoleList,
    RoleRef,
    RoleSummary,
    RoleUpdate,
    SourceView,
)
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

ROLE_READ = "identity.role.read"
ROLE_MANAGE = "identity.role.manage"
USER_READ = "identity.user.read"


def _require_read(actor: ActorContext) -> None:
    if not (actor.can(ROLE_READ, Scope.COMPANY) or actor.can(ROLE_MANAGE, Scope.COMPANY)):
        raise Forbidden(code="permission_denied", permission=ROLE_READ)


# ---- catalogue ---------------------------------------------------------------------------------------------
@query()
def permission_catalogue(uow: UnitOfWork) -> PermissionCatalogue:
    _require_read(uow.actor)
    rows = uow.session.scalars(select(Permission).where(Permission.deprecated_at.is_(None)).order_by(Permission.key))
    return PermissionCatalogue(
        items=[
            PermissionInfo(
                key=p.key,
                module=p.module,
                resource=p.resource,
                action=p.action,
                description=p.description,
                allowed_scopes=list(p.allowed_scopes),  # type: ignore[arg-type]
                delegable=p.delegable,
                requires_mfa=p.requires_mfa,
                requires_recent_auth=p.requires_recent_auth,
                field_guard=p.field_guard,
                sensitive=p.sensitivity != "normal",
            )
            for p in rows
        ]
    )


# ---- views -------------------------------------------------------------------------------------------------
def _nodes(uow: UnitOfWork) -> dict[uuid.UUID, role_resolution.RoleNode]:
    assert uow.actor.company_id is not None  # noqa: S101
    return role_resolution.load_roles(uow.session, uow.actor.company_id)


def _member_counts(uow: UnitOfWork) -> dict[uuid.UUID, int]:
    rows = uow.session.execute(
        select(MembershipRole.role_id, func.count())
        .join(Membership, Membership.id == MembershipRole.membership_id)
        .where(MembershipRole.company_id == uow.actor.company_id, Membership.status.in_(("active", "invited")))
        .group_by(MembershipRole.role_id)
    ).all()
    return {rid: int(n) for rid, n in rows}


def _summary(role: Role, nodes: dict[uuid.UUID, role_resolution.RoleNode], counts: dict[uuid.UUID, int]) -> RoleSummary:
    node = nodes[role.id]
    parent = nodes.get(role.inherits_role_id) if role.inherits_role_id else None
    return RoleSummary(
        id=role.id,
        key=role.role_key,
        name=role.name,
        description=role.description,
        kind=role.kind,  # type: ignore[arg-type]
        inherits=RoleRef(key=parent.role_key, name=parent.name) if parent else None,
        is_assignable=role.is_assignable,
        archived=role.archived_at is not None,
        member_count=counts.get(role.id, 0),
        grant_count=sum(1 for e in node.entries if e.effect == "grant"),
        deny_count=sum(1 for e in node.entries if e.effect == "deny"),
        version=role.version,
    )


@query()
def list_roles(uow: UnitOfWork, *, include_archived: bool = False) -> RoleList:
    _require_read(uow.actor)
    nodes = _nodes(uow)
    counts = _member_counts(uow)
    stmt = select(Role).where(Role.company_id == uow.actor.company_id)
    if not include_archived:
        stmt = stmt.where(Role.archived_at.is_(None))
    roles = uow.session.scalars(stmt.order_by(Role.kind.desc(), Role.name)).all()
    return RoleList(items=[_summary(r, nodes, counts) for r in roles])


def _role(uow: UnitOfWork, role_id: uuid.UUID, *, for_update: bool = False) -> Role:
    stmt = select(Role).where(Role.id == role_id, Role.company_id == uow.actor.company_id)
    if for_update:
        stmt = stmt.with_for_update()
    role = uow.session.scalars(stmt).first()
    if role is None:
        raise NotFound(code="not_found", resource_type="identity.role")
    return role


def _scope_name(scope: Scope | None) -> Literal["own", "team", "branch", "company"] | None:
    return scope.label if scope is not None else None  # type: ignore[return-value]


def _role_effective_view(nodes: dict[uuid.UUID, role_resolution.RoleNode], role_id: uuid.UUID) -> list[EffectiveKey]:
    out = []
    for key, src in sorted(role_resolution.role_effective(nodes, role_id).items()):
        kind: Literal["role", "inherited"] = "inherited" if src.inherited else "role"
        out.append(
            EffectiveKey(
                key=key,
                scope=_scope_name(src.scope),
                sources=[SourceView(kind=kind, label=f"Role {src.role_key}", role_key=src.role_key, scope=_scope_name(src.scope))],
            )
        )
    return out


def _capabilities(uow: UnitOfWork, role: Role, counts: dict[uuid.UUID, int], nodes: dict[uuid.UUID, role_resolution.RoleNode]) -> dict[str, CapabilityView]:
    manage = uow.actor.can(ROLE_MANAGE, Scope.COMPANY)
    template = role.kind == RoleKind.SYSTEM_TEMPLATE.value
    in_use = counts.get(role.id, 0) > 0 or any(
        n.inherits_role_id == role.id and not n.archived for n in nodes.values()
    )

    def cap(allowed: bool, reason: str) -> CapabilityView:
        return CapabilityView(allowed=allowed, reason_code=None if allowed else reason)

    return {
        "update": cap(manage and not template and role.archived_at is None, "permission_denied" if not manage else "role_immutable"),
        "archive": cap(
            manage and not template and role.archived_at is None and not in_use,
            "permission_denied" if not manage else ("role_immutable" if template else "role_in_use"),
        ),
        "inherit": cap(manage and role.archived_at is None, "permission_denied"),
    }


@query()
def get_role(uow: UnitOfWork, role_id: uuid.UUID) -> RoleDetail:
    _require_read(uow.actor)
    role = _role(uow, role_id)
    nodes = _nodes(uow)
    counts = _member_counts(uow)
    node = nodes[role.id]
    entries = sorted(
        (RoleEntryView(key=e.key, effect=e.effect, scope=_scope_name(e.scope) if e.effect == "grant" else None) for e in node.entries),  # type: ignore[arg-type]
        key=lambda e: (e.effect, e.key),
    )
    chain = [RoleRef(key=n.role_key, name=n.name) for n in role_resolution.chain(nodes, role.id)]
    return RoleDetail(
        role=_summary(role, nodes, counts),
        entries=entries,
        chain=chain,
        effective=_role_effective_view(nodes, role.id),
        capabilities=_capabilities(uow, role, counts, nodes),
    )


# ---- validation ----------------------------------------------------------------------------------------------
def _entries(uow: UnitOfWork, entries: list[RoleEntryIn]) -> dict[str, tuple[str, Scope]]:
    keys = [e.key for e in entries]
    if len(keys) != len(set(keys)):
        raise ValidationFailed(errors=[{"loc": ["body", "entries"], "msg": "Each permission once", "code": "duplicate_key"}])
    catalogue = {
        p.key: p for p in uow.session.scalars(select(Permission).where(Permission.key.in_(keys), Permission.deprecated_at.is_(None)))
    }
    out: dict[str, tuple[str, Scope]] = {}
    errors = []
    for i, e in enumerate(entries):
        perm = catalogue.get(e.key)
        if perm is None:
            errors.append({"loc": ["body", "entries", i, "key"], "msg": "Unknown permission", "code": "unknown_permission"})
            continue
        if e.effect == "grant":
            if e.scope is None:
                errors.append({"loc": ["body", "entries", i, "scope"], "msg": "A grant needs a scope", "code": "missing"})
                continue
            if e.scope not in perm.allowed_scopes:
                errors.append({"loc": ["body", "entries", i, "scope"], "msg": f"{e.key} allows {', '.join(perm.allowed_scopes)}", "code": "scope_not_allowed"})
                continue
            out[e.key] = ("grant", Scope.parse(e.scope))
        else:
            out[e.key] = ("deny", Scope.COMPANY)
    if errors:
        raise ValidationFailed("Some permissions are not valid.", errors=errors)
    return out


def _check_parent(uow: UnitOfWork, nodes: dict[uuid.UUID, role_resolution.RoleNode], role_id: uuid.UUID | None, parent_id: uuid.UUID) -> None:
    parent = nodes.get(parent_id)
    if parent is None or parent.archived:
        raise ValidationFailed(errors=[{"loc": ["body", "inherits_role_id"], "msg": "Unknown role", "code": "unknown_role"}])
    if role_id is not None and (parent_id == role_id or parent_id in role_resolution.descendants(nodes, role_id)):
        raise ValidationFailed(errors=[{"loc": ["body", "inherits_role_id"], "msg": "That would make a cycle", "code": "inheritance_cycle"}])
    depth = len(role_resolution.chain(nodes, parent_id)) + 1
    below = _depth_below(nodes, role_id) if role_id is not None else 0
    if depth + below > role_resolution.MAX_CHAIN:
        raise ValidationFailed(
            errors=[{"loc": ["body", "inherits_role_id"], "msg": f"At most {role_resolution.MAX_CHAIN} roles in a chain", "code": "inheritance_too_deep"}]
        )


def _depth_below(nodes: dict[uuid.UUID, role_resolution.RoleNode], role_id: uuid.UUID) -> int:
    children = [n.id for n in nodes.values() if n.inherits_role_id == role_id and not n.archived]
    return 1 + max(_depth_below(nodes, c) for c in children) if children else 0


def _check_within_actor(uow: UnitOfWork, effective: dict[str, role_resolution.GrantSource]) -> None:
    actor = uow.actor
    if actor.is_system:
        return
    for key, src in sorted(effective.items()):
        held = actor.permissions.get(key)
        if held is None or held < src.scope:
            raise Forbidden(f"You cannot give {key} at {src.scope.label} scope.", code="permission_escalation", permission=key)


def _write_entries(uow: UnitOfWork, role: Role, wanted: dict[str, tuple[str, Scope]]) -> dict[str, dict[str, object]]:
    current = {rp.permission_key: rp for rp in uow.session.scalars(select(RolePermission).where(RolePermission.role_id == role.id))}
    diff: dict[str, dict[str, object]] = {}
    stale = [k for k in current if k not in wanted]
    if stale:
        uow.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_key.in_(stale)))
    for key in stale:
        diff[key] = {"from": f"{current[key].effect}:{current[key].scope}", "to": None}
    for key, (effect, scope) in wanted.items():
        row = current.get(key)
        label = scope.label
        if row is None:
            uow.add(RolePermission(role_id=role.id, company_id=role.company_id, permission_key=key, scope=label, effect=effect))
            diff[key] = {"from": None, "to": f"{effect}:{label}"}
        elif (row.effect, row.scope) != (effect, label):
            diff[key] = {"from": f"{row.effect}:{row.scope}", "to": f"{effect}:{label}"}
            row.effect, row.scope = effect, label
    uow.flush()
    return diff


def _affected_memberships(uow: UnitOfWork, role_id: uuid.UUID, nodes: dict[uuid.UUID, role_resolution.RoleNode]) -> list[uuid.UUID]:
    roles = {role_id} | role_resolution.descendants(nodes, role_id)
    return list(uow.session.scalars(select(MembershipRole.membership_id).where(MembershipRole.role_id.in_(roles)).distinct()))


def _role_event(uow: UnitOfWork, name: str, role: Role, changed: list[str]) -> None:
    uow.emit(
        name,
        aggregate_id=role.id,
        aggregate_version=role.version,
        payload={"role_id": str(role.id), "role_key": role.role_key, "changed_fields": sorted(changed)},
    )


# ---- commands --------------------------------------------------------------------------------------------------
@command(ROLE_MANAGE, at_least=Scope.COMPANY)
def create_role(uow: UnitOfWork, body: RoleCreate) -> RoleDetail:
    require_step_up(uow, ROLE_MANAGE)
    provisioning.lock_access(uow)
    exists = uow.session.scalar(select(Role.id).where(Role.company_id == uow.actor.company_id, Role.role_key == body.key))
    if exists is not None:
        raise Conflict("A role with this key exists.", code="duplicate_key", errors=[{"loc": ["body", "key"], "msg": "already used", "code": "duplicate"}])
    nodes = _nodes(uow)
    if body.inherits_role_id is not None:
        _check_parent(uow, nodes, None, body.inherits_role_id)
    wanted = _entries(uow, body.entries)
    role = Role(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        role_key=body.key,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        kind=RoleKind.CUSTOM.value,
        template_key=None,
        is_assignable=True,
        inherits_role_id=body.inherits_role_id,
    )
    uow.add(role)
    uow.flush()
    diff = _write_entries(uow, role, wanted)
    nodes = _nodes(uow)
    _check_within_actor(uow, role_resolution.role_effective(nodes, role.id))
    provisioning.bump_authz_epoch(uow)
    _role_event(uow, "identity.role.created", role, ["key", "name", "entries", *(["inherits"] if body.inherits_role_id else [])])
    uow.audit(
        "identity.role.created",
        resource_type="identity.role",
        resource_id=role.id,
        resource_label=role.role_key,
        changes={"entries": {"from": None, "to": {k: v["to"] for k, v in diff.items()}}, "inherits_role_id": {"from": None, "to": str(body.inherits_role_id) if body.inherits_role_id else None}},
    )
    return get_role(uow, role.id)


@command(ROLE_MANAGE, at_least=Scope.COMPANY)
def update_role(uow: UnitOfWork, role_id: uuid.UUID, body: RoleUpdate) -> RoleDetail:
    require_step_up(uow, ROLE_MANAGE)
    provisioning.lock_access(uow)
    role = _role(uow, role_id, for_update=True)
    if role.kind == RoleKind.SYSTEM_TEMPLATE.value:
        raise Conflict("System roles are read-only. Create a custom role that inherits this one instead.", code="role_immutable")
    if role.archived_at is not None:
        raise Conflict("This role is archived.", code="role_archived")
    uow.expect_version(role, body.expected_version)
    changes: dict[str, dict[str, object]] = {}
    changed: list[str] = []
    if body.name is not None and body.name.strip() != role.name:
        changes["name"] = {"from": role.name, "to": body.name.strip()}
        role.name = body.name.strip()
        changed.append("name")
    if body.description is not None and (body.description.strip() or None) != role.description:
        changes["description"] = {"from": role.description, "to": body.description.strip() or None}
        role.description = body.description.strip() or None
        changed.append("description")
    nodes = _nodes(uow)
    new_parent = None if body.clear_inherits else (body.inherits_role_id or role.inherits_role_id)
    access_relevant = False
    if new_parent != role.inherits_role_id:
        if new_parent is not None:
            _check_parent(uow, nodes, role.id, new_parent)
        changes["inherits_role_id"] = {"from": str(role.inherits_role_id) if role.inherits_role_id else None, "to": str(new_parent) if new_parent else None}
        role.inherits_role_id = new_parent
        changed.append("inherits")
        access_relevant = True
    if body.entries is not None:
        diff = _write_entries(uow, role, _entries(uow, body.entries))
        if diff:
            changes["entries"] = {"from": {k: v["from"] for k, v in diff.items()}, "to": {k: v["to"] for k, v in diff.items()}}
            changed.append("entries")
            access_relevant = True
    if not changed:
        return get_role(uow, role.id)
    role.updated_at = uow.now()  # the row is dirty, so its version moves even when only entries changed
    uow.flush()
    nodes = _nodes(uow)
    _check_within_actor(uow, role_resolution.role_effective(nodes, role.id))
    for child in role_resolution.descendants(nodes, role.id):
        _check_within_actor(uow, role_resolution.role_effective(nodes, child))
    if access_relevant:
        provisioning.access_changed(uow, _affected_memberships(uow, role.id, nodes), ["roles"])
    _role_event(uow, "identity.role.updated", role, changed)
    uow.audit("identity.role.updated", resource_type="identity.role", resource_id=role.id, resource_label=role.role_key, changes=changes)
    return get_role(uow, role.id)


@command(ROLE_MANAGE, at_least=Scope.COMPANY)
def archive_role(uow: UnitOfWork, role_id: uuid.UUID) -> RoleDetail:
    require_step_up(uow, ROLE_MANAGE)
    provisioning.lock_access(uow)
    role = _role(uow, role_id, for_update=True)
    if role.kind == RoleKind.SYSTEM_TEMPLATE.value:
        raise Conflict("System roles cannot be archived.", code="role_immutable")
    if role.archived_at is not None:
        return get_role(uow, role.id)
    nodes = _nodes(uow)
    assigned = uow.session.scalar(select(func.count()).select_from(MembershipRole).where(MembershipRole.role_id == role.id)) or 0
    inheritors = [n.role_key for n in nodes.values() if n.inherits_role_id == role.id and not n.archived]
    if assigned or inheritors:
        raise Conflict(
            "Unassign this role (and change the roles that inherit it) before archiving it.",
            code="role_in_use",
            members=int(assigned),
            inherited_by=inheritors,
        )
    role.archived_at = uow.now()
    role.archived_by = uow.actor.user_id
    uow.flush()
    provisioning.bump_authz_epoch(uow)
    _role_event(uow, "identity.role.archived", role, ["archived_at"])
    uow.audit("identity.role.archived", resource_type="identity.role", resource_id=role.id, resource_label=role.role_key)
    return get_role(uow, role.id)


# ---- simulator ----------------------------------------------------------------------------------------------------
def _require_simulator(actor: ActorContext) -> None:
    if not (actor.can(USER_READ, Scope.COMPANY) or actor.can(ROLE_READ, Scope.COMPANY) or actor.can(ROLE_MANAGE, Scope.COMPANY)):
        raise Forbidden(code="permission_denied", permission=USER_READ)


def _member_sources(uow: UnitOfWork, membership: Membership) -> tuple[dict[str, list[SourceView]], dict[str, list[SourceView]], dict[str, Scope], dict[str, set[uuid.UUID]]]:
    """(granting sources per key, removing sources per key, resolved permissions, delegated)."""
    from app.platform.identity.actors import load_access

    now = uow.now()
    nodes = _nodes(uow)
    assigned = [rid for rid in uow.session.scalars(select(MembershipRole.role_id).where(MembershipRole.membership_id == membership.id)) if rid in nodes]
    employee = role_resolution.employee_role_id(nodes)
    grants: dict[str, list[SourceView]] = {}
    removed: dict[str, list[SourceView]] = {}
    for rid in [*assigned, *([employee] if employee and employee not in assigned else [])]:
        base = rid == employee and rid not in assigned
        for key, src in role_resolution.role_effective(nodes, rid).items():
            kind: Literal["role", "inherited", "employee_base"] = "employee_base" if base else ("inherited" if src.inherited else "role")
            label = "Everyone (employee base)" if base else (f"Role {nodes[rid].name}" + (f", inherited from {src.role_key}" if src.inherited else ""))
            grants.setdefault(key, []).append(SourceView(kind=kind, label=label, role_key=nodes[rid].role_key, scope=_scope_name(src.scope)))
        for key, denier in role_resolution.denied_by(nodes, rid).items():
            removed.setdefault(key, []).append(SourceView(kind="role_deny", label=f"Denied in role {denier} (for {nodes[rid].name})", role_key=denier))
    overrides = uow.session.scalars(
        select(UserPermissionOverride).where(UserPermissionOverride.membership_id == membership.id, UserPermissionOverride.archived_at.is_(None))
    )
    for o in overrides:
        if o.expires_at is not None and o.expires_at <= now:
            continue
        if o.effect == "grant":
            grants.setdefault(o.permission_key, []).append(
                SourceView(kind="override_grant", label=f"Personal grant: {o.reason}", scope=o.scope, expires_at=o.expires_at)  # type: ignore[arg-type]
            )
        else:
            removed.setdefault(o.permission_key, []).append(
                SourceView(kind="override_revoke", label=f"Personal revoke: {o.reason}", expires_at=o.expires_at)
            )
    access = load_access(uow.session, membership.company_id, membership.id, membership.user_id, now=now)
    perms = dict(access.permissions) if membership.status == "active" else {}
    return grants, removed, perms, {k: set(v) for k, v in access.delegated.items()}


def _names_of(uow: UnitOfWork, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(user_ids))).all())  # type: ignore[arg-type]


@query()
def effective_access(uow: UnitOfWork, *, user_id: uuid.UUID | None = None, role_id: uuid.UUID | None = None) -> EffectiveAccess:
    _require_simulator(uow.actor)
    if (user_id is None) == (role_id is None):
        raise ValidationFailed(errors=[{"loc": ["query"], "msg": "Give user_id or role_id", "code": "one_of"}])
    if role_id is not None:
        role = _role(uow, role_id)
        nodes = _nodes(uow)
        removed = [
            EffectiveKey(key=k, scope=None, sources=[SourceView(kind="role_deny", label=f"Denied in role {r}", role_key=r)])
            for k, r in sorted(role_resolution.denied_by(nodes, role.id).items())
        ]
        return EffectiveAccess(
            subject="role", user_id=None, display_name=role.name, role_keys=[role.role_key], membership_status=None,
            granted=_role_effective_view(nodes, role.id), removed=removed, delegated=[],
        )
    assert user_id is not None  # noqa: S101
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    grants, removed, perms, delegated = _member_sources(uow, membership)
    user = uow.session.get(AppUser, user_id)
    nodes = _nodes(uow)
    role_keys = sorted(
        nodes[rid].role_key for rid in uow.session.scalars(select(MembershipRole.role_id).where(MembershipRole.membership_id == membership.id)) if rid in nodes
    )
    granted = [EffectiveKey(key=k, scope=_scope_name(s), sources=grants.get(k, [])) for k, s in sorted(perms.items())]
    removed_view = [
        EffectiveKey(key=k, scope=None, sources=[*grants.get(k, []), *srcs]) for k, srcs in sorted(removed.items()) if k not in perms
    ]
    names = _names_of(uow, {u for users in delegated.values() for u in users})
    delegated_view = [
        EffectiveKey(
            key=k,
            scope=_scope_name(perms.get(k)),
            sources=[SourceView(kind="delegation", label=f"Delegated by {names.get(u, 'someone')}") for u in sorted(users)],
        )
        for k, users in sorted(delegated.items())
    ]
    return EffectiveAccess(
        subject="member", user_id=user_id, display_name=user.display_name if user else None, role_keys=role_keys,
        membership_status=membership.status, granted=granted, removed=removed_view, delegated=delegated_view,
    )


@query()
def check_access(uow: UnitOfWork, *, user_id: uuid.UUID, permission_key: str, scope: str = "own") -> AccessCheck:
    """Can this member use ``permission_key`` at ``scope``? Every reason is listed (why / why not)."""
    _require_simulator(uow.actor)
    membership = provisioning.membership_for_user(uow, user_id)
    if membership is None:
        raise NotFound(code="not_found", resource_type="identity.membership")
    perm = uow.session.get(Permission, permission_key)
    if perm is None:
        raise ValidationFailed(errors=[{"loc": ["query", "permission_key"], "msg": "Unknown permission", "code": "unknown_permission"}])
    needed = Scope.parse(scope)
    grants, removed, perms, delegated = _member_sources(uow, membership)
    held = perms.get(permission_key)
    reasons: list[str] = []
    if membership.status != "active":
        reasons.append(f"The membership is {membership.status}: an inactive member has no permissions.")
    if held is not None:
        reasons.append(f"Held at {held.label} scope.")
        if held < needed:
            reasons.append(f"{needed.label.capitalize()} scope is needed, which is wider than {held.label}.")
    else:
        if permission_key in removed:
            reasons += [s.label for s in removed[permission_key]]
        elif not grants.get(permission_key):
            reasons.append("No role or personal grant includes this permission.")
    if permission_key in delegated:
        reasons.append("Delegation extends record reach for this key (it never adds the key).")
    if perm.requires_mfa:
        reasons.append("Using it also needs a two-step (authenticator) verified session.")
    if perm.requires_recent_auth:
        reasons.append("Using it also needs a sign-in within the last 10 minutes.")
    allowed = held is not None and held >= needed
    return AccessCheck(
        permission_key=permission_key,
        allowed=allowed,
        scope=_scope_name(held),
        needed_scope=needed.label,  # type: ignore[arg-type]
        reasons=reasons,
        sources=[*grants.get(permission_key, []), *removed.get(permission_key, [])],
    )
