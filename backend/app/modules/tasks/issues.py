"""Issue and task persistence: the single place that writes issues, members, tasks, candidates,
dependencies, history and change-log rows, and emits ``tasks.*`` events in the same transaction.

``apply_outcome`` reconciles one issue key with what a rule derived from current source state:
it is idempotent (the same facts give the same fingerprint, no events and no change rows), ignores
stale reads, never reopens a terminal task (a regression opens a new row; an authorised dismissal
stands), and opens ``occurrence + 1`` when a resolved root cause recurs.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.tasks.issue_keys import fingerprint, issue_id
from app.modules.tasks.models import (
    OPEN_STATES,
    ChangeLog,
    Issue,
    IssueMember,
    IssueState,
    Task,
    TaskCandidate,
    TaskDependency,
    TaskHistory,
    TaskOrigin,
    TaskState,
)
from app.modules.tasks.rules.outcome import ChangeSpec, Closure, IssueOutcome, TaskSpec
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

_EVENT_FOR_STATE = {
    TaskState.DONE.value: "tasks.task.completed",
    TaskState.DISMISSED.value: "tasks.task.dismissed",
    TaskState.CANCELLED.value: "tasks.task.cancelled",
    TaskState.EXPIRED.value: "tasks.task.expired",
    TaskState.IN_PROGRESS.value: "tasks.task.started",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sid(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


# ---- events and history ---------------------------------------------------------------------------
def emit_task_event(uow: UnitOfWork, name: str, task: Task, *, from_state: str | None, causation_id: uuid.UUID | None = None) -> None:
    uow.emit(
        name,
        aggregate_id=task.id,
        aggregate_version=task.version,
        causation_id=causation_id,
        payload={
            "task_id": str(task.id),
            "issue_id": str(task.issue_id),
            "kind": task.kind,
            "family": task.family,
            "owner_user_id": _sid(task.owner_user_id),
            "assignee_user_id": _sid(task.assignee_user_id),
            "due_at": _iso(task.due_at),
            "from_state": from_state,
            "to_state": task.state,
        },
    )


def emit_issue_event(uow: UnitOfWork, name: str, issue: Issue, *, causation_id: uuid.UUID | None = None) -> None:
    uow.emit(
        name,
        aggregate_id=issue.id,
        aggregate_version=issue.version,
        causation_id=causation_id,
        payload={
            "issue_id": str(issue.id),
            "issue_key": issue.issue_key,
            "family": issue.family,
            "occurrence": issue.occurrence,
            "fingerprint": issue.fingerprint,
        },
    )


def record_history(
    uow: UnitOfWork,
    task: Task,
    action: str,
    *,
    from_state: str | None = None,
    to_state: str | None = None,
    details: dict[str, Any] | None = None,
    event_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    actor = uow.actor
    kind = "system" if actor.is_system else ("agent" if actor.actor_type == "agent" else "user")
    uow.add(
        TaskHistory(
            company_id=task.company_id,
            task_id=task.id,
            at=uow.now(),
            actor_user_id=actor_user_id if actor_user_id is not None else actor.user_id,
            actor_kind=kind,
            on_behalf_of=actor.on_behalf_of_user_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            details=details,
            event_id=event_id,
            correlation_id=actor.correlation_id,
        )
    )


# ---- reads ---------------------------------------------------------------------------------------
def live_issue(uow: UnitOfWork, issue_key: str, *, for_update: bool = True) -> Issue | None:
    stmt = select(Issue).where(
        Issue.company_id == uow.actor.company_id,
        Issue.issue_key == issue_key,
        Issue.state.in_((IssueState.OPEN.value, IssueState.INFO.value)),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return uow.session.scalars(stmt).first()


def issue_tasks(uow: UnitOfWork, issue: Issue) -> list[Task]:
    return list(uow.session.scalars(select(Task).where(Task.issue_id == issue.id).order_by(Task.created_at, Task.id)))


def candidates_of(uow: UnitOfWork, task_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    ids = list(task_ids)
    out: dict[uuid.UUID, list[uuid.UUID]] = {t: [] for t in ids}
    if not ids:
        return out
    for task_id, user_id in uow.session.execute(
        select(TaskCandidate.task_id, TaskCandidate.user_id).where(TaskCandidate.task_id.in_(ids)).order_by(TaskCandidate.user_id)
    ):
        out[task_id].append(user_id)
    return out


def dependencies_of(uow: UnitOfWork, task_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    ids = list(task_ids)
    out: dict[uuid.UUID, list[uuid.UUID]] = {t: [] for t in ids}
    if not ids:
        return out
    for task_id, dep in uow.session.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_issue_id)
        .where(TaskDependency.task_id.in_(ids))
        .order_by(TaskDependency.depends_on_issue_id)
    ):
        out[task_id].append(dep)
    return out


# ---- fingerprint and state -------------------------------------------------------------------------
def issue_material(uow: UnitOfWork, issue: Issue) -> dict[str, Any]:
    members = uow.session.scalars(
        select(IssueMember).where(IssueMember.issue_id == issue.id, IssueMember.active.is_(True)).order_by(IssueMember.member_key)
    ).all()
    tasks = issue_tasks(uow, issue)
    cands = candidates_of(uow, [t.id for t in tasks])
    deps = dependencies_of(uow, [t.id for t in tasks])
    return {
        "state": issue.state,
        "title": issue.title,
        "title_facts": issue.title_facts,
        "members": [[m.member_key, m.role, m.ref_type, str(m.ref_id), m.facts] for m in members],
        "tasks": [
            [
                t.dedup_key,
                t.kind,
                t.state,
                t.due_kind,
                _iso(t.due_at),
                _sid(t.owner_user_id),
                _sid(t.assignee_user_id),
                [str(c) for c in cands[t.id]],
                [str(d) for d in deps[t.id]],
                t.overdue_emitted_at is not None,
            ]
            for t in sorted(tasks, key=lambda x: (x.dedup_key, x.created_at, str(x.id)))
        ],
    }


def settle_issue(
    uow: UnitOfWork,
    issue: Issue,
    *,
    created: bool,
    info: bool = False,
    resolution: str | None = None,
    cause_event_id: uuid.UUID | None = None,
) -> None:
    """Recompute state and fingerprint from stored rows; emit opened/changed/resolved as needed."""
    uow.flush()
    previous_state = issue.state
    open_left = uow.session.scalar(
        select(func.count()).select_from(Task).where(Task.issue_id == issue.id, Task.state.in_(OPEN_STATES))
    )
    now = uow.now()
    if info:
        issue.state = IssueState.INFO.value
    elif open_left:
        issue.state = IssueState.OPEN.value
    elif resolution is not None and issue.state != IssueState.RESOLVED.value:
        issue.state = IssueState.RESOLVED.value
        issue.resolved_at = now
        issue.resolution = resolution
    fp = fingerprint(issue_material(uow, issue))
    if created:
        issue.fingerprint = fp
        uow.flush()
        emit_issue_event(uow, "tasks.issue.opened", issue, causation_id=cause_event_id)
        return
    changed = fp != issue.fingerprint
    if changed:
        issue.fingerprint = fp
        issue.last_changed_at = now
        if cause_event_id is not None:
            issue.last_event_id = cause_event_id
    uow.flush()
    if issue.state == IssueState.RESOLVED.value and previous_state != IssueState.RESOLVED.value:
        emit_issue_event(uow, "tasks.issue.resolved", issue, causation_id=cause_event_id)
    elif changed:
        emit_issue_event(uow, "tasks.issue.changed", issue, causation_id=cause_event_id)


# ---- tasks ---------------------------------------------------------------------------------------
def close_task(
    uow: UnitOfWork,
    task: Task,
    closure: Closure,
    *,
    event_id: uuid.UUID | None = None,
    dismissal_reason_code: str | None = None,
    dismissal_note: str | None = None,
) -> None:
    if task.state not in OPEN_STATES:
        return
    from_state = task.state
    now = uow.now()
    task.state = closure.state
    task.closed_at = now
    task.closed_by = closure.closed_by
    task.completion_evidence = dict(closure.evidence) or None
    if closure.state == TaskState.DONE.value:
        task.completion_evidence = dict(closure.evidence) or {"reason": "completed"}
        task.completed_by = closure.closed_by
    if closure.state == TaskState.DISMISSED.value:
        task.dismissal_reason_code = dismissal_reason_code
        task.dismissal_note = dismissal_note
    uow.flush()
    record_history(
        uow, task, closure.state, from_state=from_state, to_state=task.state,
        details=task.completion_evidence, event_id=event_id, actor_user_id=closure.closed_by,
    )
    emit_task_event(uow, _EVENT_FOR_STATE[closure.state], task, from_state=from_state, causation_id=event_id)


def sync_candidates(uow: UnitOfWork, task: Task, wanted: Iterable[uuid.UUID]) -> bool:
    wanted_set = set(wanted)
    current = set(candidates_of(uow, [task.id])[task.id])
    if wanted_set == current:
        return False
    removed = current - wanted_set
    if removed:
        uow.session.execute(
            delete(TaskCandidate).where(TaskCandidate.task_id == task.id, TaskCandidate.user_id.in_(sorted(removed)))
        )
    for user_id in sorted(wanted_set - current):
        uow.add(TaskCandidate(company_id=task.company_id, task_id=task.id, user_id=user_id, added_at=uow.now()))
    return True


def sync_dependencies(uow: UnitOfWork, task: Task, depends_on: Iterable[tuple[str, str]]) -> None:
    wanted: dict[uuid.UUID, str] = {}
    for key, condition in depends_on:
        target = live_issue(uow, key, for_update=False)
        if target is not None and target.state == IssueState.OPEN.value and target.id != task.issue_id:
            wanted[target.id] = condition
    current = set(dependencies_of(uow, [task.id])[task.id])
    stale = current - set(wanted)
    if stale:
        uow.session.execute(
            delete(TaskDependency).where(TaskDependency.task_id == task.id, TaskDependency.depends_on_issue_id.in_(sorted(stale)))
        )
    for target_id, condition in sorted(wanted.items()):
        if target_id not in current:
            uow.add(
                TaskDependency(
                    company_id=task.company_id, task_id=task.id, depends_on_issue_id=target_id,
                    condition_code=condition, created_at=uow.now(),
                )
            )


def new_task(uow: UnitOfWork, issue: Issue, spec: TaskSpec, *, family: str, origin: str, event_id: uuid.UUID | None) -> Task:
    task = Task(
        company_id=issue.company_id,
        branch_id=spec.branch_id,
        kind=spec.kind,
        family=family,
        issue_id=issue.id,
        dedup_key=spec.dedup_key,
        title=spec.title[:300],
        facts=spec.facts,
        primary_ref_type=spec.primary_ref_type,
        primary_ref_id=spec.primary_ref_id,
        primary_ref_version=spec.primary_ref_version,
        owner_user_id=spec.owner_user_id,
        assignee_user_id=spec.assignee_user_id,
        initiator_user_id=spec.initiator_user_id,
        queue_code=spec.queue_code,
        due_kind=spec.due_kind if spec.due_at is not None else "none",
        due_at=spec.due_at,
        state=TaskState.OPEN.value,
        completion_check=spec.completion_check,
        required_permission=spec.required_permission,
        scope_owner_id=spec.scope_owner_id,
        scope_branch_id=spec.scope_branch_id,
        sensitivity=spec.sensitivity,
        origin=origin,
    )
    uow.add(task)
    uow.flush()
    sync_candidates(uow, task, spec.candidates)
    sync_dependencies(uow, task, spec.depends_on)
    record_history(uow, task, "created", to_state=task.state, event_id=event_id)
    emit_task_event(uow, "tasks.task.created", task, from_state=None, causation_id=event_id)
    return task


def assignment_holds(uow: UnitOfWork, task: Task, spec: TaskSpec) -> bool:
    """A person's (re)assignment (``assigned_by`` set) is an override of the rule's choice. It stands while
    the assignee is an active member who can see tasks and open the task's source record."""
    if task.assigned_by is None or task.assignee_user_id is None:
        return False
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import INTERNAL_REF_TYPES, can_view_source, view_as

    member = responsibility.member_actor(uow, task.assignee_user_id)
    if member is None or not member.can("tasks.task.read"):
        return False
    ref_type, ref_id = spec.primary_ref_type, spec.primary_ref_id
    if ref_type and ref_id and ref_type not in INTERNAL_REF_TYPES:
        return can_view_source(view_as(uow, member), ref_type, ref_id)
    return True


def update_task(uow: UnitOfWork, task: Task, spec: TaskSpec, *, event_id: uuid.UUID | None) -> None:
    override = assignment_holds(uow, task, spec)
    owner = spec.owner_user_id
    assignee = task.assignee_user_id if override else spec.assignee_user_id
    queue_code = None if override else spec.queue_code
    if task.assigned_by is not None and not override:
        task.assigned_by = None  # the assignee left or lost access: the rule's responsibility applies again
    reassigned = (task.owner_user_id, task.assignee_user_id) != (owner, assignee)
    new_due_kind = spec.due_kind if spec.due_at is not None else "none"
    due_changed = (task.due_at, task.due_kind) != (spec.due_at, new_due_kind)
    task.title = spec.title[:300]
    task.facts = spec.facts
    task.primary_ref_type = spec.primary_ref_type
    task.primary_ref_id = spec.primary_ref_id
    task.primary_ref_version = spec.primary_ref_version
    task.owner_user_id = owner
    task.assignee_user_id = assignee
    task.initiator_user_id = spec.initiator_user_id
    task.queue_code = queue_code
    if due_changed:
        task.due_at = spec.due_at
        task.due_kind = new_due_kind
        task.overdue_emitted_at = None
    task.required_permission = spec.required_permission
    task.scope_owner_id = spec.scope_owner_id
    task.scope_branch_id = spec.scope_branch_id
    task.branch_id = spec.branch_id
    task.sensitivity = spec.sensitivity
    candidates_changed = sync_candidates(uow, task, spec.candidates)
    sync_dependencies(uow, task, spec.depends_on)
    uow.flush()
    if reassigned or candidates_changed:
        record_history(uow, task, "assigned", from_state=task.state, to_state=task.state, event_id=event_id,
                       details={"candidates": [str(c) for c in spec.candidates]} if candidates_changed else None)
        emit_task_event(uow, "tasks.task.assigned", task, from_state=task.state, causation_id=event_id)


# ---- change log ----------------------------------------------------------------------------------
def write_change(uow: UnitOfWork, issue: Issue, change: ChangeSpec, event: DomainEvent, *, task_id: uuid.UUID | None = None) -> bool:
    row = uow.session.execute(
        pg_insert(ChangeLog)
        .values(
            id=uuid.uuid7(),
            company_id=issue.company_id,
            issue_id=issue.id,
            task_id=task_id,
            event_id=event.id,
            event_type=event.event_type,
            fact_at=change.fact_at,
            recorded_at=uow.now(),
            ref_type=change.ref_type,
            ref_id=change.ref_id,
            ref_version=change.ref_version,
            change_code=change.change_code,
            before=change.before,
            after=change.after,
            actor_user_id=change.actor_user_id,
            required_permission=issue.required_permission,
            scope_owner_id=issue.scope_owner_id,
            scope_branch_id=issue.scope_branch_id,
            sensitivity=issue.sensitivity,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "issue_id"])
        .returning(ChangeLog.id)
    ).first()
    return row is not None


# ---- reconcile ---------------------------------------------------------------------------------------
def apply_outcome(uow: UnitOfWork, outcome: IssueOutcome, event: DomainEvent | None = None) -> Issue | None:
    company_id = uow.actor.company_id
    assert company_id is not None
    now = uow.now()
    event_id = event.id if event is not None else None
    issue = live_issue(uow, outcome.issue_key)
    created = False
    if issue is None:
        if not outcome.tasks and not outcome.info:
            return None  # nothing to open: no obligation and no informational stream
        last = uow.session.scalar(
            select(func.max(Issue.occurrence)).where(Issue.company_id == company_id, Issue.issue_key == outcome.issue_key)
        )
        occurrence = int(last or 0) + 1
        issue = Issue(
            id=issue_id(company_id, outcome.issue_key, occurrence),
            company_id=company_id,
            issue_key=outcome.issue_key,
            occurrence=occurrence,
            family=outcome.family,
            state=IssueState.INFO.value if outcome.info else IssueState.OPEN.value,
            root_ref_type=outcome.root_ref_type,
            root_ref_id=outcome.root_ref_id,
            title=outcome.title[:300],
            title_facts=outcome.title_facts,
            fingerprint="",
            required_permission=outcome.required_permission,
            scope_owner_id=outcome.scope_owner_id,
            scope_branch_id=outcome.scope_branch_id,
            sensitivity=outcome.sensitivity,
            first_seen_at=outcome.first_seen_at or (event.occurred_at if event is not None else now),
            last_changed_at=now,
            last_event_id=event_id,
        )
        uow.add(issue)
        uow.flush()
        created = True

    existing = {
        m.member_key: m for m in uow.session.scalars(select(IssueMember).where(IssueMember.issue_id == issue.id))
    }
    root_key = next((m.key for m in outcome.members if m.role == "root"), None)
    if not created and root_key and outcome.root_version is not None:
        stored = existing.get(root_key)
        if stored is not None and stored.ref_version is not None and stored.ref_version > outcome.root_version:
            return None  # a stale read: never move facts backwards

    issue.title = outcome.title[:300]
    issue.title_facts = outcome.title_facts
    issue.required_permission = outcome.required_permission
    issue.scope_owner_id = outcome.scope_owner_id
    issue.scope_branch_id = outcome.scope_branch_id
    issue.sensitivity = outcome.sensitivity

    material_changes: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
    wanted_keys = set()
    for spec in outcome.members:
        wanted_keys.add(spec.key)
        member = existing.get(spec.key)
        if member is None:
            uow.add(
                IssueMember(
                    company_id=company_id, issue_id=issue.id, member_key=spec.key, role=spec.role,
                    ref_type=spec.ref_type, ref_id=spec.ref_id, ref_version=spec.ref_version, label=spec.label[:300],
                    facts=spec.facts, required_permission=spec.required_permission,
                    scope_owner_id=spec.scope_owner_id, scope_branch_id=spec.scope_branch_id,
                    active=True, added_at=now,
                )
            )
            continue
        if member.active and member.facts != spec.facts:
            material_changes.append((spec, dict(member.facts), dict(spec.facts)))
        member.role = spec.role
        member.ref_version = spec.ref_version
        member.label = spec.label[:300]
        member.facts = spec.facts
        member.required_permission = spec.required_permission
        member.scope_owner_id = spec.scope_owner_id
        member.scope_branch_id = spec.scope_branch_id
        member.active = True
        member.removed_at = None
    for key, member in existing.items():
        if key not in wanted_keys and member.active:
            member.active = False
            member.removed_at = now
    uow.flush()

    tasks = issue_tasks(uow, issue)
    open_by_key = {t.dedup_key: t for t in tasks if t.state in OPEN_STATES}
    terminal_by_key: dict[str, Task] = {}
    for t in tasks:
        if t.state not in OPEN_STATES:
            terminal_by_key[t.dedup_key] = t  # ordered by created_at: the latest wins
    wanted_tasks = {spec.dedup_key: spec for spec in outcome.tasks}
    cause_persists = False
    for key, spec in wanted_tasks.items():
        task = open_by_key.get(key)
        if task is not None:
            update_task(uow, task, spec, event_id=event_id)
            continue
        previous = terminal_by_key.get(key)
        if previous is not None and previous.state in (TaskState.DISMISSED.value, TaskState.EXPIRED.value):
            # an authorised dismissal (or a lapse) stands while the same cause persists: no new row,
            # and the issue stays open
            cause_persists = True
            continue
        new_task(uow, issue, spec, family=outcome.family, origin=TaskOrigin.RULE.value, event_id=event_id)
    queues = {spec.queue_code for spec in outcome.tasks if spec.queue_code}
    for key, task in open_by_key.items():
        if key in wanted_tasks or task.origin != TaskOrigin.RULE.value:
            continue
        if task.queue_code:
            queues.add(task.queue_code)
        close_task(uow, task, outcome.closures.get(key, outcome.closure), event_id=event_id)

    if event is not None:
        changes = list(outcome.changes)
        if not changes and material_changes:
            changes.append(_generic_change(material_changes, event))
        for change in changes[:1]:  # one change row per event and issue
            write_change(uow, issue, change, event)

    settle_issue(
        uow, issue, created=created, info=outcome.info, resolution=None if cause_persists else outcome.resolution,
        cause_event_id=event_id,
    )
    if outcome.family != QUEUE_FAMILY:
        for queue_code in sorted(queues):
            sync_queue(uow, queue_code, event)
    return issue


# ---- queues: work is never silently dropped ---------------------------------------------------------------
QUEUE_FAMILY = "admin.responsibility"


def queued_count(uow: UnitOfWork, queue_code: str) -> int:
    """Open obligations waiting in a queue with nobody responsible (no owner, assignee or candidate)."""
    from sqlalchemy import exists

    return int(
        uow.session.scalar(
            select(func.count()).select_from(Task).where(
                Task.company_id == uow.actor.company_id,
                Task.queue_code == queue_code,
                Task.state.in_(OPEN_STATES),
                Task.owner_user_id.is_(None),
                Task.assignee_user_id.is_(None),
                Task.kind != "queue_triage",
                ~exists().where(TaskCandidate.task_id == Task.id),
            )
        )
        or 0
    )


def sync_queue(uow: UnitOfWork, queue_code: str, event: DomainEvent | None = None) -> None:
    """Keep one ``responsibility:{queue}`` issue open (a triage task for queue managers) while work waits."""
    from app.modules.tasks import responsibility
    from app.modules.tasks.issue_keys import responsibility_key
    from app.modules.tasks.models import DueKind, IssueResolution

    company_id = uow.actor.company_id
    assert company_id is not None
    key = responsibility_key(queue_code)
    count = queued_count(uow, queue_code)
    existing = live_issue(uow, key, for_update=False)
    tasks: list[TaskSpec] = []
    if count:
        managers = responsibility.queue_managers(uow)
        due = None
        if existing is not None:
            due = uow.session.scalar(
                select(Task.due_at).where(Task.issue_id == existing.id, Task.dedup_key == key, Task.state.in_(OPEN_STATES))
            )
        if due is None:
            due = responsibility.company_calendar(uow).end_of_day_due(responsibility.company_calendar(uow).work_date(uow.now()))
        title = f"Assign {count} unassigned {queue_code} item{'s' if count != 1 else ''}"
        tasks.append(
            TaskSpec(
                dedup_key=key, kind="queue_triage", title=title, completion_check="queue_empty",
                required_permission="tasks.queue.manage", facts={"queue": queue_code, "count": count},
                primary_ref_type="tasks.queue", primary_ref_id=issue_id(company_id, f"queue:{queue_code}", 1),
                due_kind=DueKind.SOFT.value, due_at=due, candidates=tuple(managers),
            )
        )
    elif existing is None:
        return
    apply_outcome(
        uow,
        IssueOutcome(
            issue_key=key, family=QUEUE_FAMILY, root_ref_type="tasks.queue",
            root_ref_id=issue_id(company_id, f"queue:{queue_code}", 1),
            title=tasks[0].title if tasks else f"Unassigned {queue_code} work", title_facts={"queue": queue_code, "count": count},
            required_permission="tasks.queue.manage", tasks=tasks,
            closure=Closure(TaskState.DONE.value, {"reason": "queue_empty"}), resolution=IssueResolution.COMPLETED.value,
        ),
        event,
    )


def _generic_change(material: list[tuple[Any, dict[str, Any], dict[str, Any]]], event: DomainEvent) -> ChangeSpec:
    def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        keys = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}

    spec, before, after = material[0]
    if len(material) == 1:
        b, a = diff(before, after)
    else:
        b, a = {}, {}
        for s, bf, af in material:
            b[s.key], a[s.key] = diff(bf, af)
    return ChangeSpec(
        change_code=f"{spec.ref_type}.changed",
        ref_type=spec.ref_type,
        ref_id=spec.ref_id,
        ref_version=spec.ref_version,
        fact_at=event.occurred_at,
        before=b,
        after=a,
        actor_user_id=event.actor_user_id,
    )
