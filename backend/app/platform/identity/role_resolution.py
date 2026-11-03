"""Role resolution with inheritance and deny (permissions.md §10 step 2), plus the provenance the simulator shows.

A custom role inherits at most one parent role of the same company (chains up to 4 roles). For each assigned
role, the chain is walked root → leaf: a ``grant`` raises a key to the higher scope; a ``deny`` removes a key the
role inherited from its own ancestors (it never affects other roles of the member). The member's role grants are
the union across their roles (and the ``employee`` base) at the maximum scope.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.authz.permissions import Scope
from app.platform.identity.models import Role, RolePermission

MAX_CHAIN = 4


@dataclass(frozen=True)
class RoleEntry:
    key: str
    scope: Scope
    effect: str  # grant | deny


@dataclass
class RoleNode:
    id: uuid.UUID
    role_key: str
    name: str
    kind: str
    inherits_role_id: uuid.UUID | None
    archived: bool
    entries: list[RoleEntry] = field(default_factory=list)


@dataclass(frozen=True)
class GrantSource:
    """Why a role grants a key: ``role_key`` holds the grant itself (``inherited`` when it is an ancestor of the
    assigned role)."""

    role_key: str
    scope: Scope
    inherited: bool


def load_roles(session: Session, company_id: uuid.UUID) -> dict[uuid.UUID, RoleNode]:
    """Every role of the company (archived included, marked) with its grant and deny entries."""
    nodes = {
        r.id: RoleNode(r.id, r.role_key, r.name, r.kind, r.inherits_role_id, r.archived_at is not None)
        for r in session.scalars(select(Role).where(Role.company_id == company_id))
    }
    rows = session.execute(
        select(RolePermission.role_id, RolePermission.permission_key, RolePermission.scope, RolePermission.effect).where(
            RolePermission.company_id == company_id
        )
    ).all()
    for role_id, key, label, effect in rows:
        node = nodes.get(role_id)
        if node is not None:
            node.entries.append(RoleEntry(key, Scope.parse(label), effect))
    return nodes


def chain(nodes: Mapping[uuid.UUID, RoleNode], role_id: uuid.UUID) -> list[RoleNode]:
    """Root → leaf ancestry of ``role_id`` (archived ancestors are skipped; a cycle or overlong chain is cut)."""
    out: list[RoleNode] = []
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = role_id
    while current is not None and current not in seen and len(out) < MAX_CHAIN:
        node = nodes.get(current)
        if node is None:
            break
        seen.add(current)
        if not node.archived:
            out.append(node)
        current = node.inherits_role_id
    return list(reversed(out))


def role_effective(nodes: Mapping[uuid.UUID, RoleNode], role_id: uuid.UUID) -> dict[str, GrantSource]:
    """What one role grants after inheritance and deny, with the role that holds each grant."""
    leaf = nodes.get(role_id)
    if leaf is None or leaf.archived:
        return {}
    effective: dict[str, GrantSource] = {}
    for node in chain(nodes, role_id):
        for entry in node.entries:
            if entry.effect == "deny":
                effective.pop(entry.key, None)
                continue
            current = effective.get(entry.key)
            if current is None or entry.scope > current.scope:
                effective[entry.key] = GrantSource(node.role_key, entry.scope, inherited=node.id != role_id)
    return effective


def denied_by(nodes: Mapping[uuid.UUID, RoleNode], role_id: uuid.UUID) -> dict[str, str]:
    """Keys a role's chain denies (key -> role key holding the deny), for "why not" explanations."""
    out: dict[str, str] = {}
    for node in chain(nodes, role_id):
        for entry in node.entries:
            if entry.effect == "deny":
                out[entry.key] = node.role_key
    return out


def union(nodes: Mapping[uuid.UUID, RoleNode], role_ids: Iterable[uuid.UUID]) -> dict[str, Scope]:
    perms: dict[str, Scope] = {}
    for role_id in role_ids:
        for key, source in role_effective(nodes, role_id).items():
            current = perms.get(key)
            perms[key] = source.scope if current is None else max(current, source.scope)
    return perms


def employee_role_id(nodes: Mapping[uuid.UUID, RoleNode]) -> uuid.UUID | None:
    return next((n.id for n in nodes.values() if n.role_key == "employee" and not n.archived), None)


def descendants(nodes: Mapping[uuid.UUID, RoleNode], role_id: uuid.UUID) -> set[uuid.UUID]:
    """Roles that inherit ``role_id`` directly or indirectly."""
    out: set[uuid.UUID] = set()
    frontier = {role_id}
    while frontier:
        nxt = {n.id for n in nodes.values() if n.inherits_role_id in frontier and n.id not in out}
        out |= nxt
        frontier = nxt
    return out
