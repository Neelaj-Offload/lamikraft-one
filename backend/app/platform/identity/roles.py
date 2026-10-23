"""Synchronising the code-defined access vocabulary into the database (idempotent).

- ``permission``: every registered ``PermissionDef`` (keys that disappear from code get ``deprecated_at``);
- ``legacy_permission_alias``: the 14 legacy permissions (permissions.md §8);
- ``role`` / ``role_permission``: one read-only system template per key in the merged ``TEMPLATE_GRANTS`` for each
  company (``employee`` is the implicit base of every member; ``admin`` holds every key at its maximum scope).

A template change that alters a company's grants increments ``company.authz_epoch`` and emits
``identity.membership.access_changed`` for every membership holding the changed role.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.authz.permissions import Scope
from app.platform.identity.access import LEGACY_ALIASES
from app.platform.identity.models import (
    LegacyPermissionAlias,
    MembershipRole,
    Permission,
    Role,
    RoleKind,
    RolePermission,
)

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

EMPLOYEE = "employee"
ADMIN = "admin"

#: name and purpose of each system template (permissions.md §9)
TEMPLATES: dict[str, tuple[str, str]] = {
    "employee": ("Employee", "Base for every member: company, directory, settings and calendar read, own tasks and briefing."),
    "admin": ("Admin", "Administration: every permission at its maximum scope."),
    "management": ("Management", "Legacy management rights plus non-destructive approvals and company-wide reads."),
    "sales": ("Sales", "Legacy sales rights: own quotes, enquiries, customers and samples."),
    "operations": ("Operations", "Operations lead: company-wide quote read, challans, cut plans and stock at branch scope."),
    "finance": ("Finance", "Finance keys, FX, costing, bank accounts and company-wide commercial reads."),
    "production": ("Production", "Production planning, cut plans, costing and branch inventory."),
    "procurement": ("Procurement", "Purchasing, vendor parties, inventory read and reorder rules."),
    "warehouse": ("Warehouse", "Restricted warehouse assistant: product read and branch stock tasks."),
    "catalogue": ("Catalogue", "Catalogue data steward: products, media, taxonomy, imports and price lists."),
}


def scope_label(scope: Scope) -> str:
    return scope.label


def sync_permission_catalogue(uow: UnitOfWork) -> int:
    """Upsert the registered permissions and the legacy alias table. Returns the number of permissions."""
    from app.registry import get_registry

    registry = get_registry()
    uow.advisory_xact_lock("identity.permission_catalogue", "sync")
    now = uow.now()
    rows = []
    for perm in registry.permissions.values():
        module, resource, action = perm.key.split(".")
        rows.append(
            {
                "key": perm.key,
                "module": module,
                "resource": resource,
                "action": action,
                "description": perm.description[:300],
                "allowed_scopes": [s.label for s in sorted(perm.scopes)],
                "delegable": perm.delegable,
                "requires_mfa": perm.requires_mfa,
                "requires_recent_auth": perm.requires_recent_auth,
                "field_guard": perm.field_guard,
                "sensitivity": perm.sensitivity,
                "slice_no": _slice_of(perm.key),
                "deprecated_at": None,
                "synced_at": now,
            }
        )
    if rows:
        stmt = pg_insert(Permission).values(rows)
        excluded = stmt.excluded
        uow.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Permission.key],
                set_={c: excluded[c] for c in rows[0] if c != "key"},
            )
        )
    uow.session.execute(
        update(Permission)
        .where(Permission.key.not_in(list(registry.permissions)), Permission.deprecated_at.is_(None))
        .values(deprecated_at=now)
    )
    _sync_legacy_aliases(uow, set(registry.permissions))
    return len(rows)


def _slice_of(key: str) -> int:
    from app.platform.authz.catalogue import catalogue_slice

    try:
        return catalogue_slice(key)
    except KeyError:
        return 1


def _sync_legacy_aliases(uow: UnitOfWork, known: set[str]) -> None:
    wanted = {(a.legacy_key, a.permission_key): a for a in LEGACY_ALIASES if a.permission_key in known}
    existing = {
        (r.legacy_key, r.permission_key): r for r in uow.session.scalars(select(LegacyPermissionAlias))
    }
    for pk, row in existing.items():
        if pk not in wanted:
            uow.session.delete(row)
    for pk, alias in wanted.items():
        values = {
            "scope": alias.scope.label if alias.scope else None,
            "scope_from_key": alias.scope_from_key,
            "fallback_scope": alias.fallback_scope.label if alias.fallback_scope else None,
            "note": alias.note,
        }
        row = existing.get(pk)
        if row is None:
            uow.session.add(LegacyPermissionAlias(legacy_key=pk[0], permission_key=pk[1], **values))
        else:
            for k, v in values.items():
                if getattr(row, k) != v:
                    setattr(row, k, v)
    uow.session.flush()


def template_grants() -> dict[str, dict[str, Scope]]:
    from app.registry import get_registry

    grants = {k: dict(v) for k, v in get_registry().template_grants.items()}
    for key in TEMPLATES:
        grants.setdefault(key, {})
    return grants


def ensure_system_roles(uow: UnitOfWork, company_id: uuid.UUID, *, origin: str = "system") -> dict[str, uuid.UUID]:
    """Create or update the system templates of a company. Returns role_key -> role id.

    Runs as the company (RLS); the permission catalogue must be synced first.
    """
    from app.platform.identity import provisioning

    uow.advisory_xact_lock("identity.system_roles", str(company_id))
    roles = {r.role_key: r for r in uow.session.scalars(select(Role).where(Role.company_id == company_id))}
    changed_roles: set[uuid.UUID] = set()
    out: dict[str, uuid.UUID] = {}
    for template_key, grants in sorted(template_grants().items()):
        name, description = TEMPLATES.get(template_key, (template_key.replace("_", " ").title(), None))
        role = roles.get(template_key)
        if role is None:
            role = Role(
                id=uuid.uuid7(),
                company_id=company_id,
                role_key=template_key,
                name=name,
                description=description,
                kind=RoleKind.SYSTEM_TEMPLATE.value,
                template_key=template_key,
                is_assignable=template_key != EMPLOYEE,
            )
            uow.add(role)
            uow.flush()
        elif role.kind == RoleKind.SYSTEM_TEMPLATE.value and (role.name, role.description) != (name, description):
            role.name, role.description = name, description
        out[template_key] = role.id
        current = {
            rp.permission_key: rp
            for rp in uow.session.scalars(select(RolePermission).where(RolePermission.role_id == role.id))
        }
        wanted = {key: scope.label for key, scope in grants.items()}
        stale = [k for k in current if k not in wanted]
        if stale:
            uow.session.execute(
                delete(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_key.in_(stale))
            )
            changed_roles.add(role.id)
        for key, label in wanted.items():
            row = current.get(key)
            if row is None:
                uow.add(RolePermission(role_id=role.id, company_id=company_id, permission_key=key, scope=label))
                changed_roles.add(role.id)
            elif row.scope != label or row.effect != "grant":
                row.scope, row.effect = label, "grant"
                changed_roles.add(role.id)
    uow.flush()
    if changed_roles and roles:  # a company that already had roles: holders' access changed
        holders = list(
            uow.session.scalars(
                select(MembershipRole.membership_id).where(MembershipRole.role_id.in_(changed_roles)).distinct()
            )
        )
        employee_changed = out.get(EMPLOYEE) in changed_roles
        provisioning.access_changed(uow, holders, ["roles"], origin=origin, all_members=employee_changed)
    return out
