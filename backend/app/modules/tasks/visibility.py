"""Visibility: who may see a task, an issue member or a source record.

Two layers (briefing design §12):
1. a SQL predicate over denormalised attributes (the ``tasks.task`` ResourcePolicy scope clause plus
   approval candidates) for lists and counts;
2. an authoritative re-check of every source record (``can_view_source``) through the owning module's
   ResourcePolicy (``visible_ids``) when one is registered, otherwise through the scope attributes the
   module's SourceReader reports (required permission, owner, branch) evaluated with the same scope
   rules as ``scope_clause``.
Records that fail are dropped before anything is grouped, counted or phrased (no aggregate leakage).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, exists, false, or_, select

from app.platform import sources
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.authz.policy import get_policy, scope_clause
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

#: administrative references (queues, dead-lettered jobs, failing briefings): queue managers only
ADMIN_REF_TYPES = frozenset({"tasks.queue", "system.job", "briefings.briefing"})
#: internal reference types that are not business records read through a SourceReader
INTERNAL_REF_TYPES = frozenset({"tasks.task", "identity.user"}) | ADMIN_REF_TYPES
TASK_READ = "tasks.task.read"


def view_as(uow: UnitOfWork, actor: ActorContext) -> UnitOfWork:
    """A unit of work for ``actor`` that shares ``uow``'s session, transaction and clock.

    Used by consumers and jobs (running as the system) to evaluate visibility, eligibility and briefing
    contents exactly as the member would see them, inside the same transaction.
    """
    view = UnitOfWork(actor, clock=uow.clock)
    view.session = uow.session
    return view


def scope_allows(
    actor: ActorContext,
    permission: str,
    *,
    owner_ids: Iterable[uuid.UUID | None] = (),
    branch_id: uuid.UUID | None = None,
) -> bool:
    """The record-scope rule of ``scope_clause`` evaluated on reported attributes."""
    if actor.is_system:
        return True
    owners = {o for o in owner_ids if o is not None}
    scope = actor.permissions.get(permission)
    delegators = actor.delegated.get(permission, frozenset())
    own = actor.user_id in owners or bool(owners & delegators)
    if scope == Scope.COMPANY:
        return True
    if scope == Scope.BRANCH:
        if branch_id is None:  # resources without a branch: branch scope behaves as company scope
            return True
        return branch_id in actor.branch_ids or own
    if scope == Scope.TEAM:
        peers = set(actor.team_peer_user_ids)
        if actor.user_id is not None:
            peers.add(actor.user_id)
        return bool(owners & peers) or own
    if scope == Scope.OWN:
        return own
    return bool(owners & delegators)


@dataclass
class SourceCache:
    """Per-build cache of source reads and visibility decisions."""

    facts: dict[tuple[str, uuid.UUID], SourceFacts | None] = field(default_factory=dict)
    visible: dict[tuple[str, uuid.UUID], bool] = field(default_factory=dict)

    def read(self, uow: UnitOfWork, source_type: str, source_id: uuid.UUID) -> SourceFacts | None:
        key = (source_type, source_id)
        if key not in self.facts:
            self.facts[key] = sources.read(uow, source_type, source_id)
        return self.facts[key]


def can_view_source(
    uow: UnitOfWork, source_type: str, source_id: uuid.UUID, *, cache: SourceCache | None = None
) -> bool:
    actor = uow.actor
    if actor.is_system:
        return True
    cache = cache or SourceCache()
    key = (source_type, source_id)
    if key in cache.visible:
        return cache.visible[key]
    result = _can_view(uow, source_type, source_id, cache)
    cache.visible[key] = result
    return result


def _can_view(uow: UnitOfWork, source_type: str, source_id: uuid.UUID, cache: SourceCache) -> bool:
    actor = uow.actor
    if source_type == "identity.user":
        return actor.user_id == source_id or actor.can("org.directory.read")
    if source_type == "tasks.task":
        return task_visible(uow, source_id)
    if source_type in ADMIN_REF_TYPES:
        return actor.can("tasks.queue.manage")
    if source_type == "approvals.proposal":
        from app.modules.approvals import service as approvals

        try:
            approvals.get(uow, source_id)
        except Exception:  # NotFound for non-viewers  # noqa: BLE001
            return False
        return True
    try:
        policy = get_policy(source_type)
    except KeyError:
        policy = None
    if policy is not None:
        model = policy.model
        return bool(
            uow.session.scalar(
                select(exists().where(model.id == source_id, scope_clause(actor, policy, "read")))  # type: ignore[attr-defined]
            )
        )
    facts = cache.read(uow, source_type, source_id)
    if facts is None:
        return False
    return scope_allows(
        actor, facts.required_permission, owner_ids=(facts.owner_user_id,), branch_id=facts.branch_id
    )


#: reference types decided by dedicated rules above (never by a bulk policy query)
_SPECIAL_TYPES = frozenset({"identity.user", "tasks.task", "approvals.proposal"}) | ADMIN_REF_TYPES


def prime_visibility(uow: UnitOfWork, refs: Iterable[tuple[str | None, uuid.UUID | None]], cache: SourceCache) -> None:
    """Decide many references at once where a ResourcePolicy exists: one query per source type instead
    of one per record (lists, counts and briefing builds). Other types are left to ``can_view_source``."""
    actor = uow.actor
    if actor.is_system:
        return
    by_type: dict[str, set[uuid.UUID]] = {}
    for source_type, source_id in refs:
        if source_type is None or source_id is None or source_type in _SPECIAL_TYPES:
            continue
        if (source_type, source_id) not in cache.visible:
            by_type.setdefault(source_type, set()).add(source_id)
    for source_type, ids in sorted(by_type.items()):
        try:
            policy = get_policy(source_type)
        except KeyError:
            continue
        if policy is None:
            continue
        model = policy.model
        seen = set(
            uow.session.scalars(
                select(model.id).where(model.id.in_(sorted(ids)), scope_clause(actor, policy, "read"))  # type: ignore[attr-defined]
            )
        )
        for source_id in ids:
            cache.visible[(source_type, source_id)] = source_id in seen


# ---- tasks ---------------------------------------------------------------------------------------
def task_scope_clause(actor: ActorContext, action: str = "read", *, cap: Scope | None = None) -> ColumnElement[bool]:
    """Tasks the actor may ``action`` by record scope (owner/assignee/branch), optionally capped."""
    policy = get_policy("tasks.task")
    if cap is not None:
        key = f"tasks.task.{action}"
        held = actor.permissions.get(key)
        if held is not None and held > cap:
            perms = dict(actor.permissions)
            perms[key] = cap
            actor = actor.with_(permissions=perms)
    return scope_clause(actor, policy, action)


def candidate_clause(actor: ActorContext) -> ColumnElement[bool]:
    from app.modules.tasks.models import Task, TaskCandidate

    if actor.user_id is None:
        return false()
    return Task.id.in_(select(TaskCandidate.task_id).where(TaskCandidate.user_id == actor.user_id))


def responsible_clause(actor: ActorContext) -> ColumnElement[bool]:
    """Tasks the actor is personally responsible for: assignee, owner or candidate approver."""
    from app.modules.tasks.models import Task

    if actor.user_id is None:
        return false()
    return or_(
        Task.assignee_user_id == actor.user_id,
        Task.owner_user_id == actor.user_id,
        candidate_clause(actor),
    )


def task_visible_clause(actor: ActorContext) -> ColumnElement[bool]:
    return or_(task_scope_clause(actor, "read"), candidate_clause(actor))


def task_visible(uow: UnitOfWork, task_id: uuid.UUID) -> bool:
    from app.modules.tasks.models import Task

    if uow.actor.is_system:
        return True
    return bool(
        uow.session.scalar(select(exists().where(Task.id == task_id, task_visible_clause(uow.actor))))
    )
