"""Resource policies and the record-scope clause.

Every tenant resource registers a :class:`ResourcePolicy`. Reads, lists, counts, searches,
exports, child lines, revisions, notes, attachments and activity are all filtered by
:func:`scope_clause`, so a sales user can never reach another owner's quote by guessing an id.
Child resources are authorised only through their parent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope


@dataclass(frozen=True)
class ParentRef:
    resource_type: str
    fk_column: str
    #: child action -> parent action (default: same name, with create/update/delete -> update)
    action_map: Mapping[str, str] = field(default_factory=dict)

    def parent_action(self, action: str) -> str:
        if action in self.action_map:
            return self.action_map[action]
        return "update" if action in {"create", "update", "delete", "archive"} else action


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class ResourcePolicy:
    resource_type: str
    model: type
    permission_prefix: str
    owner_columns: tuple[str, ...] = ()
    branch_column: str | None = None
    parent: ParentRef | None = None
    business_key_column: str | None = None
    label: Callable[[Any], str] | None = None
    canonical_path: Callable[[Any], str] | None = None
    #: extra, object-level action rules (e.g. "delete only while draft")
    rules: Callable[[ActorContext, Any], Mapping[str, Decision]] | None = None
    archived_column: str | None = "archived_at"

    def permission(self, action: str) -> str:
        return f"{self.permission_prefix}.{action}"


_POLICIES: dict[str, ResourcePolicy] = {}
_BY_MODEL: dict[type, ResourcePolicy] = {}


def register_policy(policy: ResourcePolicy) -> None:
    existing = _POLICIES.get(policy.resource_type)
    if existing is not None and existing is not policy:
        raise ValueError(f"duplicate resource policy {policy.resource_type}")
    _POLICIES[policy.resource_type] = policy
    _BY_MODEL[policy.model] = policy


def get_policy(resource_type: str) -> ResourcePolicy:
    try:
        return _POLICIES[resource_type]
    except KeyError as exc:
        raise KeyError(f"no resource policy registered for {resource_type!r}") from exc


def policy_for_model(model: type) -> ResourcePolicy:
    try:
        return _BY_MODEL[model]
    except KeyError as exc:
        raise KeyError(f"no resource policy registered for model {model.__name__}") from exc


def all_policies() -> dict[str, ResourcePolicy]:
    return dict(_POLICIES)


def scope_clause(ctx: ActorContext, policy: ResourcePolicy, action: str = "read") -> ColumnElement[bool]:
    """SQL predicate limiting ``policy.model`` rows to those ``ctx`` may perform ``action`` on."""
    model = policy.model
    company_filter = model.company_id == ctx.company_id  # type: ignore[attr-defined]

    if policy.parent is not None:
        parent_policy = get_policy(policy.parent.resource_type)
        parent_model = parent_policy.model
        parent_ids = select(parent_model.id).where(  # type: ignore[attr-defined]
            scope_clause(ctx, parent_policy, policy.parent.parent_action(action))
        )
        return company_filter & getattr(model, policy.parent.fk_column).in_(parent_ids)

    if ctx.is_system:
        return company_filter

    key = policy.permission(action)
    scope = ctx.permissions.get(key)
    delegators = ctx.delegated.get(key, frozenset())
    owner_cols = [getattr(model, c) for c in policy.owner_columns]

    if scope == Scope.COMPANY:
        return company_filter & true()

    own_terms: list[ColumnElement[bool]] = []
    if ctx.user_id is not None:
        own_terms += [col == ctx.user_id for col in owner_cols]
    if delegators:
        own_terms += [col.in_(delegators) for col in owner_cols]

    terms: list[ColumnElement[bool]] = []
    if scope == Scope.BRANCH and policy.branch_column:
        if ctx.branch_ids:
            terms.append(getattr(model, policy.branch_column).in_(ctx.branch_ids))
        terms += own_terms
    elif scope == Scope.BRANCH:  # resource without a branch: branch scope behaves as company scope
        return company_filter & true()
    elif scope == Scope.TEAM:
        peers = set(ctx.team_peer_user_ids)
        if ctx.user_id is not None:
            peers.add(ctx.user_id)
        terms += [col.in_(peers) for col in owner_cols]
        terms += own_terms
    elif scope == Scope.OWN:
        terms += own_terms
    else:  # no scope: only delegated records, if any
        terms += [col.in_(delegators) for col in owner_cols] if delegators else []

    if not terms:
        return company_filter & false()
    return company_filter & or_(*terms)


def object_decisions(ctx: ActorContext, policy: ResourcePolicy, obj: Any) -> dict[str, Decision]:
    """Object-level rules (state guards) contributed by the owning module."""
    if policy.rules is None:
        return {}
    return dict(policy.rules(ctx, obj))
