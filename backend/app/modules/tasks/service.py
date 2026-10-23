"""Tasks public service: the only entry point for routers, tools, jobs and other modules.

Reads for other modules return plain views (``schemas.*Info``); commands run inside the caller's unit
of work, re-check authority through the ``tasks.task`` ResourcePolicy (404 when not visible, 403 when
visible but forbidden) and emit ``tasks.*`` events in the same transaction.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, literal, or_, select, tuple_

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.modules.tasks import completion, responsibility
from app.modules.tasks import issue_keys as keys
from app.modules.tasks.errors import ActionNotAllowed, NotComplete, SnoozeBeyondDeadline
from app.modules.tasks.issues import (
    candidates_of,
    close_task,
    dependencies_of,
    emit_task_event,
    record_history,
    settle_issue,
)
from app.modules.tasks.models import (
    OPEN_STATES,
    TERMINAL_STATES,
    ChangeLog,
    DueKind,
    Issue,
    IssueMember,
    IssueState,
    MemberRole,
    Reminder,
    ReminderState,
    Snooze,
    Task,
    TaskCandidate,
    TaskOrigin,
    TaskState,
)
from app.modules.tasks.rules.outcome import Closure
from app.modules.tasks.schemas import (
    APPROVAL_KINDS,
    CONVERSATION_KINDS,
    UNDISMISSABLE_KINDS,
    AllowedTransition,
    Capability,
    ChangeInfo,
    HandledResult,
    InboxCounts,
    InboxItem,
    InboxPage,
    IssueInfo,
    MemberInfo,
    ReminderCreate,
    ReminderInfo,
    ReminderList,
    ReminderOut,
    ReminderUpdate,
    SnoozeInfo,
    SnoozeOut,
    SourceRef,
    TaskCreate,
    TaskDetail,
    TaskInfo,
)
from app.modules.tasks.visibility import (
    INTERNAL_REF_TYPES,
    SourceCache,
    can_view_source,
    responsible_clause,
    task_scope_clause,
    task_visible_clause,
    view_as,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.uow import UnitOfWork

#: snooze policy (mandatory controls; briefing design §9)
SNOOZE_DEADLINE_LEAD = timedelta(minutes=60)
MAX_SNOOZE_OVERDUE = timedelta(minutes=120)
MAX_SNOOZE_NO_DEADLINE = timedelta(days=7)
UNSNOOZABLE_KINDS: frozenset[str] = frozenset()


# ---- conversions -----------------------------------------------------------------------------------
def _task_info(task: Task, candidates: Sequence[uuid.UUID] = (), blocked_by: Sequence[uuid.UUID] = ()) -> TaskInfo:
    return TaskInfo(
        id=task.id, issue_id=task.issue_id, kind=task.kind, family=task.family, title=task.title, facts=dict(task.facts or {}),
        state=task.state, due_kind=task.due_kind, due_at=task.due_at, owner_user_id=task.owner_user_id,
        assignee_user_id=task.assignee_user_id, initiator_user_id=task.initiator_user_id, queue_code=task.queue_code,
        completion_check=task.completion_check, primary_ref_type=task.primary_ref_type, primary_ref_id=task.primary_ref_id,
        primary_ref_version=task.primary_ref_version, required_permission=task.required_permission,
        scope_owner_id=task.scope_owner_id, scope_branch_id=task.scope_branch_id, overdue_emitted_at=task.overdue_emitted_at,
        closed_at=task.closed_at, closed_by=task.closed_by, dismissal_reason_code=task.dismissal_reason_code,
        completion_evidence=task.completion_evidence, version=task.version, origin=task.origin, created_at=task.created_at,
        candidates=tuple(candidates), blocked_by=tuple(blocked_by),
    )


def _task_infos(uow: UnitOfWork, tasks: Sequence[Task]) -> list[TaskInfo]:
    ids = [t.id for t in tasks]
    cands = candidates_of(uow, ids)
    deps = dependencies_of(uow, ids)
    open_targets: set[uuid.UUID] = set()
    all_targets = {d for v in deps.values() for d in v}
    if all_targets:
        open_targets = set(
            uow.session.scalars(select(Issue.id).where(Issue.id.in_(all_targets), Issue.state == IssueState.OPEN.value))
        )
    return [_task_info(t, cands[t.id], [d for d in deps[t.id] if d in open_targets]) for t in tasks]


def _member_info(m: IssueMember) -> MemberInfo:
    return MemberInfo(
        key=m.member_key, role=m.role, ref_type=m.ref_type, ref_id=m.ref_id, ref_version=m.ref_version, label=m.label,
        facts=dict(m.facts or {}), required_permission=m.required_permission, scope_owner_id=m.scope_owner_id,
        scope_branch_id=m.scope_branch_id,
    )


def _issue_info(issue: Issue, members: Sequence[IssueMember]) -> IssueInfo:
    return IssueInfo(
        id=issue.id, issue_key=issue.issue_key, occurrence=issue.occurrence, family=issue.family, state=issue.state,
        root_ref_type=issue.root_ref_type, root_ref_id=issue.root_ref_id, title=issue.title,
        title_facts=dict(issue.title_facts or {}), fingerprint=issue.fingerprint,
        required_permission=issue.required_permission, scope_owner_id=issue.scope_owner_id,
        scope_branch_id=issue.scope_branch_id, sensitivity=issue.sensitivity, first_seen_at=issue.first_seen_at,
        last_changed_at=issue.last_changed_at, last_event_id=issue.last_event_id, resolved_at=issue.resolved_at,
        resolution=issue.resolution, members=tuple(_member_info(m) for m in members),
    )


# ---- reads for briefings ---------------------------------------------------------------------------
def issues_by_id(uow: UnitOfWork, issue_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, IssueInfo]:
    ids = sorted(set(issue_ids))
    if not ids:
        return {}
    issues = uow.session.scalars(select(Issue).where(Issue.company_id == uow.actor.company_id, Issue.id.in_(ids))).all()
    members: dict[uuid.UUID, list[IssueMember]] = {i.id: [] for i in issues}
    for m in uow.session.scalars(
        select(IssueMember)
        .where(IssueMember.issue_id.in_(ids), IssueMember.active.is_(True))
        .order_by(IssueMember.role != MemberRole.ROOT.value, IssueMember.member_key)
    ):
        members[m.issue_id].append(m)
    return {i.id: _issue_info(i, members[i.id]) for i in issues}


def open_tasks_for(uow: UnitOfWork, user_id: uuid.UUID, *, as_of: datetime | None = None) -> list[TaskInfo]:
    """Open obligations the user is responsible for (assignee, owner or candidate approver)."""
    actor = ActorContext(actor_type="user", company_id=uow.actor.company_id, user_id=user_id)
    stmt = select(Task).where(Task.company_id == uow.actor.company_id, Task.state.in_(OPEN_STATES), responsible_clause(actor))
    if as_of is not None:
        stmt = stmt.where(Task.created_at <= as_of)
    tasks = uow.session.scalars(stmt.order_by(Task.due_at.asc().nulls_last(), Task.id)).all()
    return _task_infos(uow, tasks)


def closed_tasks_for(uow: UnitOfWork, user_id: uuid.UUID, since: datetime, *, until: datetime | None = None) -> list[TaskInfo]:
    """Tasks closed after ``since`` by someone else where the user owns, does, decides or requested them."""
    actor = ActorContext(actor_type="user", company_id=uow.actor.company_id, user_id=user_id)
    tasks = uow.session.scalars(
        select(Task)
        .where(
            Task.company_id == uow.actor.company_id,
            Task.state.in_((TaskState.DONE.value, TaskState.EXPIRED.value)),
            Task.closed_at > since,
            or_(responsible_clause(actor), Task.initiator_user_id == user_id),
            or_(Task.closed_by.is_(None), Task.closed_by != user_id),
            Task.closed_at <= (until or datetime.max.replace(tzinfo=since.tzinfo)),
        )
        .order_by(Task.closed_at, Task.id)
    ).all()
    # a closure by the system is "handled for you" only when it came from someone else's action
    return [t for t in _task_infos(uow, tasks) if t.closed_by is not None]


def changes_for(uow: UnitOfWork, user_id: uuid.UUID, since: datetime, *, until: datetime | None = None) -> list[ChangeInfo]:
    """Change-log rows after ``since`` on issues the user watches or is responsible for (others' actions)."""
    actor = ActorContext(actor_type="user", company_id=uow.actor.company_id, user_id=user_id)
    responsible_issues = select(Task.issue_id).where(Task.company_id == uow.actor.company_id, responsible_clause(actor))
    stmt = (
        select(ChangeLog)
        .join(Issue, Issue.id == ChangeLog.issue_id)
        .where(
            ChangeLog.company_id == uow.actor.company_id,
            ChangeLog.fact_at > since,
            or_(Issue.scope_owner_id == user_id, ChangeLog.issue_id.in_(responsible_issues)),
            or_(ChangeLog.actor_user_id.is_(None), ChangeLog.actor_user_id != user_id),
        )
        .order_by(ChangeLog.fact_at, ChangeLog.id)
    )
    if until is not None:
        stmt = stmt.where(ChangeLog.fact_at <= until)
    return [
        ChangeInfo(
            id=c.id, issue_id=c.issue_id, event_id=c.event_id, event_type=c.event_type, fact_at=c.fact_at,
            ref_type=c.ref_type, ref_id=c.ref_id, ref_version=c.ref_version, change_code=c.change_code,
            before=c.before, after=c.after, actor_user_id=c.actor_user_id,
        )
        for c in uow.session.scalars(stmt)
    ]


def issue_states(uow: UnitOfWork, issue_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = sorted(set(issue_ids))
    if not ids:
        return {}
    return dict(uow.session.execute(select(Issue.id, Issue.state).where(Issue.id.in_(ids))).tuples().all())


def open_tasks_in(uow: UnitOfWork, issue_ids: Iterable[uuid.UUID]) -> list[TaskInfo]:
    ids = sorted(set(issue_ids))
    if not ids:
        return []
    tasks = uow.session.scalars(
        select(Task).where(Task.company_id == uow.actor.company_id, Task.issue_id.in_(ids), Task.state.in_(OPEN_STATES))
        .order_by(Task.due_at.asc().nulls_last(), Task.id)
    ).all()
    return _task_infos(uow, tasks)


def tasks_by_id(uow: UnitOfWork, task_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, TaskInfo]:
    ids = sorted(set(task_ids))
    if not ids:
        return {}
    tasks = uow.session.scalars(select(Task).where(Task.company_id == uow.actor.company_id, Task.id.in_(ids))).all()
    return {t.id: t for t in _task_infos(uow, tasks)}


def reminders_for(
    uow: UnitOfWork, user_id: uuid.UUID, *, states: Sequence[str] = ("pending", "fired"), as_of: datetime | None = None
) -> list[ReminderInfo]:
    stmt = select(Reminder).where(Reminder.company_id == uow.actor.company_id, Reminder.user_id == user_id, Reminder.state.in_(states))
    if as_of is not None:
        stmt = stmt.where(Reminder.created_at <= as_of)
    rows = uow.session.scalars(stmt.order_by(Reminder.remind_at, Reminder.id)).all()
    return [_reminder_info(r) for r in rows]


def _reminder_info(r: Reminder) -> ReminderInfo:
    return ReminderInfo(
        id=r.id, user_id=r.user_id, text=r.text, remind_at=r.remind_at, time_zone=r.time_zone,
        linked_ref_type=r.linked_ref_type, linked_ref_id=r.linked_ref_id, state=r.state, version=r.version,
        created_at=r.created_at,
    )


def activation_time(uow: UnitOfWork, user_id: uuid.UUID) -> datetime | None:
    from app.modules.tasks.rules.families import activation_time as _activation

    return _activation(uow, user_id)


def snoozes_for(uow: UnitOfWork, user_id: uuid.UUID) -> dict[uuid.UUID, SnoozeInfo]:
    rows = uow.session.scalars(
        select(Snooze).where(Snooze.company_id == uow.actor.company_id, Snooze.user_id == user_id)
    ).all()
    return {s.issue_id: SnoozeInfo(s.issue_id, s.snoozed_until, s.set_at, s.channel) for s in rows}


def effective_snoozes(uow: UnitOfWork, user_id: uuid.UUID, tasks: Sequence[TaskInfo], issues: dict[uuid.UUID, IssueInfo]) -> dict[uuid.UUID, SnoozeInfo]:
    """Snoozes still in force: not expired, not woken by an overdue fact or a material change."""
    now = uow.now()
    out: dict[uuid.UUID, SnoozeInfo] = {}
    by_issue: dict[uuid.UUID, list[TaskInfo]] = {}
    for t in tasks:
        by_issue.setdefault(t.issue_id, []).append(t)
    for issue_id, snooze in snoozes_for(uow, user_id).items():
        if snooze.snoozed_until <= now:
            continue
        issue = issues.get(issue_id)
        if issue is not None and issue.last_changed_at > snooze.set_at:
            continue  # a material change wakes the item
        if any(t.overdue_emitted_at is not None and t.overdue_emitted_at > snooze.set_at for t in by_issue.get(issue_id, [])):
            continue  # an overdue fact wakes the item
        out[issue_id] = snooze
    return out


# ---- inbox ------------------------------------------------------------------------------------------
def _tab_of(task: Task | TaskInfo, now: datetime) -> str:
    if task.kind in APPROVAL_KINDS:
        return "approvals"
    if task.kind in CONVERSATION_KINDS:
        return "conversations"
    return "tasks"


def _tab_clause(tab: str, now: datetime) -> Any:
    if tab == "approvals":
        return Task.kind.in_(sorted(APPROVAL_KINDS))
    if tab == "conversations":
        return Task.kind.in_(sorted(CONVERSATION_KINDS))
    if tab == "tasks":
        return Task.kind.not_in(sorted(APPROVAL_KINDS | CONVERSATION_KINDS))
    return or_(
        and_(Task.due_at.is_not(None), Task.due_at < now),
        and_(Task.queue_code.is_not(None), Task.owner_user_id.is_(None), Task.assignee_user_id.is_(None), ~exists().where(TaskCandidate.task_id == Task.id)),
    )


def _scope_clause(actor: ActorContext, scope: str) -> Any:
    if scope == "mine":
        return responsible_clause(actor)
    wanted = Scope.parse(scope)
    held = actor.scope_for("tasks.task.read")
    if held is None or held < wanted:
        raise Forbidden(code="permission_denied", permission="tasks.task.read", scope=scope)
    return or_(task_scope_clause(actor, "read", cap=wanted), responsible_clause(actor))


def _encode_cursor(sort_key: datetime | None, task_id: uuid.UUID) -> str:
    raw = json.dumps([sort_key.isoformat() if sort_key else None, str(task_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime | None, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        due, tid = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return (datetime.fromisoformat(due) if due else None), uuid.UUID(tid)
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationFailed("invalid cursor", code="invalid_cursor") from exc


def _sources_visible(uow: UnitOfWork, task: Task | TaskInfo, cache: SourceCache) -> bool:
    if task.primary_ref_type is None or task.primary_ref_id is None or task.primary_ref_type in INTERNAL_REF_TYPES:
        return True
    return can_view_source(uow, task.primary_ref_type, task.primary_ref_id, cache=cache)


def _source_refs(uow: UnitOfWork, task: Task | TaskInfo, cache: SourceCache) -> list[SourceRef]:
    if task.primary_ref_type is None or task.primary_ref_id is None:
        return []
    if task.primary_ref_type in INTERNAL_REF_TYPES:
        return []
    if task.primary_ref_type == "approvals.proposal":
        return [SourceRef(type=task.primary_ref_type, id=task.primary_ref_id, version=task.primary_ref_version,
                          label=task.title, path=f"/approvals/{task.primary_ref_id}")]
    facts = cache.read(uow, task.primary_ref_type, task.primary_ref_id)
    if facts is None:
        return []
    return [SourceRef(type=facts.source_type, id=facts.source_id, version=facts.version, label=facts.label, path=facts.canonical_path)]


def _capabilities(uow: UnitOfWork, task: Task) -> dict[str, Capability]:
    actor = uow.actor
    is_open = task.state in OPEN_STATES
    responsible = actor.user_id in (task.owner_user_id, task.assignee_user_id)
    out: dict[str, Capability] = {}
    if task.kind in APPROVAL_KINDS:
        out["complete"] = Capability(allowed=False, reason_code="decide_through_approvals")
        out["dismiss"] = Capability(allowed=False, reason_code="undismissable_kind")
        out["assign"] = Capability(allowed=False, reason_code="approvals_use_candidates")
    else:
        can_update = responsible or _in_scope(uow, task, "update")
        out["complete"] = Capability(allowed=is_open and can_update, reason_code=None if is_open and can_update else ("closed" if not is_open else "permission_denied"))
        can_dismiss = _in_scope(uow, task, "dismiss")
        out["dismiss"] = Capability(allowed=is_open and can_dismiss, reason_code=None if is_open and can_dismiss else ("closed" if not is_open else "permission_denied"))
        can_assign = actor.user_id == task.owner_user_id or _in_scope(uow, task, "assign")
        out["assign"] = Capability(allowed=is_open and can_assign, reason_code=None if is_open and can_assign else ("closed" if not is_open else "permission_denied"))
    out["snooze"] = Capability(
        allowed=is_open and task.kind not in UNSNOOZABLE_KINDS,
        reason_code=None if is_open and task.kind not in UNSNOOZABLE_KINDS else ("closed" if not is_open else "unsnoozable_kind"),
    )
    return out


def _in_scope(uow: UnitOfWork, task: Task, action: str) -> bool:
    return bool(uow.session.scalar(select(exists().where(Task.id == task.id, task_scope_clause(uow.actor, action)))))


def _inbox_item(uow: UnitOfWork, task: Task, snoozes: dict[uuid.UUID, SnoozeInfo], blocked: set[uuid.UUID], cache: SourceCache) -> InboxItem:
    now = uow.now()
    snooze = snoozes.get(task.issue_id)
    return InboxItem(
        id=task.id, issue_id=task.issue_id, kind=task.kind, family=task.family, tab=_tab_of(task, now),  # type: ignore[arg-type]
        title=task.title, state=task.state, due_at=task.due_at, due_kind=task.due_kind,
        overdue=task.due_at is not None and task.due_at < now and task.state in OPEN_STATES,
        blocked=task.id in blocked, owner_user_id=task.owner_user_id, assignee_user_id=task.assignee_user_id,
        queue_code=task.queue_code, snoozed_until=snooze.snoozed_until if snooze and snooze.snoozed_until > now else None,
        source_refs=_source_refs(uow, task, cache), capabilities=_capabilities(uow, task), version=task.version,
    )


def _blocked_ids(uow: UnitOfWork, task_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
    deps = dependencies_of(uow, task_ids)
    targets = {d for v in deps.values() for d in v}
    if not targets:
        return set()
    open_targets = set(uow.session.scalars(select(Issue.id).where(Issue.id.in_(targets), Issue.state == IssueState.OPEN.value)))
    return {t for t, v in deps.items() if any(d in open_targets for d in v)}


def _require_user(uow: UnitOfWork) -> uuid.UUID:
    if uow.actor.user_id is None:
        raise Forbidden(code="person_required")
    return uow.actor.user_id


def inbox(uow: UnitOfWork, *, tab: str = "tasks", scope: str = "mine", cursor: str | None = None, limit: int = 50) -> InboxPage:
    _require_user(uow)
    uow.actor.require("tasks.task.read")
    now = uow.now()
    limit = max(1, min(limit, 200))
    sort_key = func.coalesce(Task.due_at, literal(datetime(9999, 12, 31, tzinfo=now.tzinfo)))
    base = select(Task).where(
        Task.company_id == uow.actor.company_id,
        Task.state.in_(OPEN_STATES),
        _scope_clause(uow.actor, scope),
        _tab_clause(tab, now),
    )
    if cursor:
        after_due, after_id = _decode_cursor(cursor)
        after_key = after_due or datetime(9999, 12, 31, tzinfo=now.tzinfo)
        base = base.where(tuple_(sort_key, Task.id) > tuple_(literal(after_key), literal(after_id)))
    ordered = base.order_by(sort_key, Task.id)
    cache = SourceCache()
    snoozes = snoozes_for(uow, uow.actor.user_id)  # type: ignore[arg-type]
    items: list[Task] = []
    last: Task | None = None
    batch_offset = 0
    exhausted = False
    while len(items) < limit and not exhausted:
        batch = list(uow.session.scalars(ordered.offset(batch_offset).limit(limit * 2)))
        batch_offset += len(batch)
        exhausted = len(batch) < limit * 2
        for task in batch:
            last = task
            if _sources_visible(uow, task, cache):  # second pass: the source itself must be visible
                items.append(task)
                if len(items) == limit:
                    break
    blocked = _blocked_ids(uow, [t.id for t in items])
    more = len(items) == limit and not (exhausted and last is not None and last.id == items[-1].id)
    next_cursor = _encode_cursor(items[-1].due_at, items[-1].id) if items and more else None
    return InboxPage(items=[_inbox_item(uow, t, snoozes, blocked, cache) for t in items], next_cursor=next_cursor, limit=limit)


def inbox_counts(uow: UnitOfWork) -> InboxCounts:
    """Open obligations per tab for the current user (snoozed items still count: snooze never erases)."""
    _require_user(uow)
    now = uow.now()
    tasks = uow.session.scalars(
        select(Task).where(Task.company_id == uow.actor.company_id, Task.state.in_(OPEN_STATES), responsible_clause(uow.actor))
    ).all()
    cache = SourceCache()
    counts = {"tasks": 0, "approvals": 0, "conversations": 0, "exceptions": 0}
    for task in tasks:
        if not _sources_visible(uow, task, cache):
            continue
        counts[_tab_of(task, now)] += 1
        if task.due_at is not None and task.due_at < now:
            counts["exceptions"] += 1
    return InboxCounts(**counts)


# ---- single task --------------------------------------------------------------------------------
def _visible_task(uow: UnitOfWork, task_id: uuid.UUID, *, for_update: bool = False) -> Task:
    stmt = select(Task).where(Task.id == task_id, Task.company_id == uow.actor.company_id, task_visible_clause(uow.actor))
    if for_update:
        stmt = stmt.with_for_update()
    task = uow.session.scalars(stmt).first()
    if task is None or not _sources_visible(uow, task, SourceCache()):
        raise NotFound(code="not_found", resource_type="tasks.task")
    return task


def _transitions(uow: UnitOfWork, task: Task) -> list[AllowedTransition]:
    caps = _capabilities(uow, task)
    out: list[AllowedTransition] = []
    if task.state == TaskState.OPEN.value and actor_is_assignee(uow, task):
        out.append(AllowedTransition(action="start", to_status="in_progress"))
    if caps["complete"].allowed:
        out.append(AllowedTransition(action="complete", to_status="done"))
    if caps["dismiss"].allowed:
        out.append(AllowedTransition(action="dismiss", to_status="dismissed", requires_reason=True))
    return out


def actor_is_assignee(uow: UnitOfWork, task: Task) -> bool:
    return uow.actor.user_id is not None and uow.actor.user_id in (task.assignee_user_id, task.owner_user_id)


def get_task(uow: UnitOfWork, task_id: uuid.UUID) -> TaskDetail:
    uow.actor.require("tasks.task.read")
    task = _visible_task(uow, task_id)
    return _detail(uow, task)


def _detail(uow: UnitOfWork, task: Task) -> TaskDetail:
    cache = SourceCache()
    snoozes = snoozes_for(uow, uow.actor.user_id) if uow.actor.user_id else {}
    item = _inbox_item(uow, task, snoozes, _blocked_ids(uow, [task.id]), cache)
    return TaskDetail(
        **item.model_dump(),
        facts=dict(task.facts or {}),
        completion_check=task.completion_check,
        completion_evidence=task.completion_evidence,
        dismissal_reason_code=task.dismissal_reason_code,
        closed_at=task.closed_at,
        created_at=task.created_at,
        allowed_transitions=_transitions(uow, task),
    )


def _issue_for_update(uow: UnitOfWork, issue_id: uuid.UUID) -> Issue:
    issue = uow.session.scalars(select(Issue).where(Issue.id == issue_id).with_for_update()).one()
    return issue


def complete_task(uow: UnitOfWork, task: Task) -> dict[str, Any]:
    """Run the completion check; mark done with evidence or raise 409 not_complete."""
    if task.kind in APPROVAL_KINDS:
        raise ActionNotAllowed("Approvals are decided through the approval request", code="action_not_allowed")
    if task.state not in OPEN_STATES:
        raise ActionNotAllowed("This task is already closed", code="task_closed")
    result = completion.check(uow, task)
    if not result.complete:
        raise NotComplete(remaining=result.remaining)
    issue = _issue_for_update(uow, task.issue_id)
    close_task(uow, task, Closure(TaskState.DONE.value, dict(result.evidence), uow.actor.user_id))
    settle_issue(uow, issue, created=False, resolution="completed")
    return dict(result.evidence)


def dismiss_task(uow: UnitOfWork, task: Task, reason_code: str | None, note: str | None) -> None:
    """An authorised dismissal: reason required, ``tasks.task.dismiss`` covering the task, audited.

    The issue stays open while its root cause persists (the rule will not recreate a dismissed task)."""
    if task.kind in UNDISMISSABLE_KINDS:
        raise ActionNotAllowed("This kind of work cannot be dismissed", code="undismissable_kind")
    if task.state not in OPEN_STATES:
        raise ActionNotAllowed("This task is already closed", code="task_closed")
    if not reason_code:
        raise ValidationFailed("A dismissal needs a reason", code="reason_required")
    if not _in_scope(uow, task, "dismiss"):
        raise Forbidden(code="permission_denied", permission="tasks.task.dismiss")
    issue = _issue_for_update(uow, task.issue_id)
    close_task(
        uow, task, Closure(TaskState.DISMISSED.value, {"reason_code": reason_code}, uow.actor.user_id),
        dismissal_reason_code=reason_code, dismissal_note=note,
    )
    uow.audit("tasks.task.dismissed", resource_type="tasks.task", resource_id=task.id, resource_label=task.title,
              reason=note, details={"reason_code": reason_code, "issue_id": str(task.issue_id)})
    settle_issue(uow, issue, created=False, resolution=None)


def transition_task(uow: UnitOfWork, task_id: uuid.UUID, *, action: str, expected_version: int | None = None,
                    reason_code: str | None = None, note: str | None = None) -> TaskDetail:
    _require_user(uow)
    task = _visible_task(uow, task_id, for_update=True)
    uow.expect_version(task, expected_version)
    if action == "complete":
        responsible = uow.actor.user_id in (task.owner_user_id, task.assignee_user_id)
        if not responsible and not _in_scope(uow, task, "update"):
            raise Forbidden(code="permission_denied", permission="tasks.task.update")
        complete_task(uow, task)
    elif action == "dismiss":
        dismiss_task(uow, task, reason_code, note)
    elif action == "start":
        if not actor_is_assignee(uow, task) or task.state != TaskState.OPEN.value:
            raise ActionNotAllowed("Only the assignee can start an open task", code="action_not_allowed")
        task.state = TaskState.IN_PROGRESS.value
        uow.flush()
        record_history(uow, task, "started", from_state=TaskState.OPEN.value, to_state=task.state)
        emit_task_event(uow, "tasks.task.started", task, from_state=TaskState.OPEN.value)
    else:
        raise ValidationFailed("unknown action", code="invalid_action")
    return _detail(uow, task)


def assign_task(uow: UnitOfWork, task_id: uuid.UUID, *, assignee_user_id: uuid.UUID, expected_version: int | None = None) -> TaskDetail:
    _require_user(uow)
    task = _visible_task(uow, task_id, for_update=True)
    uow.expect_version(task, expected_version)
    if task.kind in APPROVAL_KINDS:
        raise ActionNotAllowed("Approvals go to eligible approvers", code="approvals_use_candidates")
    if task.state not in OPEN_STATES:
        raise ActionNotAllowed("This task is already closed", code="task_closed")
    if uow.actor.user_id != task.owner_user_id and not _in_scope(uow, task, "assign"):
        raise Forbidden(code="permission_denied", permission="tasks.task.assign")
    _check_assignee_can_view(uow, assignee_user_id, task.primary_ref_type, task.primary_ref_id)
    if task.assignee_user_id == assignee_user_id:
        return _detail(uow, task)
    previous = task.assignee_user_id
    task.assignee_user_id = assignee_user_id
    task.assigned_by = uow.actor.user_id
    task.queue_code = None
    uow.flush()
    record_history(uow, task, "assigned", from_state=task.state, to_state=task.state,
                   details={"from": str(previous) if previous else None, "to": str(assignee_user_id)})
    emit_task_event(uow, "tasks.task.assigned", task, from_state=task.state)
    settle_issue(uow, _issue_for_update(uow, task.issue_id), created=False, resolution=None)
    return _detail(uow, task)


def _check_assignee_can_view(uow: UnitOfWork, user_id: uuid.UUID, ref_type: str | None, ref_id: uuid.UUID | None) -> None:
    member = responsibility.member_actor(uow, user_id)
    if member is None:
        raise ValidationFailed("The assignee is not an active member", code="assignee_inactive")
    if not member.can("tasks.task.read"):
        raise ValidationFailed("The assignee cannot see tasks", code="assignee_cannot_view")
    if ref_type and ref_id and ref_type not in INTERNAL_REF_TYPES:
        if not can_view_source(view_as(uow, member), ref_type, ref_id):
            raise ValidationFailed("The assignee cannot open the linked record", code="assignee_cannot_view")


# ---- manual tasks -------------------------------------------------------------------------------
def create_task(uow: UnitOfWork, body: TaskCreate, *, origin: str = TaskOrigin.USER.value) -> TaskDetail:
    """A manual obligation. The creator owns it unless an owner is named (that needs ``tasks.task.assign``)."""
    from app.modules.tasks.models import Issue as IssueModel
    from app.modules.tasks.rules.outcome import TaskSpec

    creator = _require_user(uow)
    uow.actor.require("tasks.task.create")
    owner = body.owner_user_id or creator
    if owner != creator and not uow.actor.can("tasks.task.assign", Scope.TEAM):
        raise Forbidden(code="permission_denied", permission="tasks.task.assign")
    assignee = body.assignee_user_id or owner
    for user_id in {owner, assignee}:
        if not responsibility.is_active(uow, user_id):
            raise ValidationFailed("Owner and assignee must be active members", code="assignee_inactive")
    if (body.linked_ref_type is None) != (body.linked_ref_id is None):
        raise ValidationFailed("linked_ref_type and linked_ref_id go together", code="linked_ref_incomplete")
    if body.linked_ref_type and body.linked_ref_id:
        if not can_view_source(uow, body.linked_ref_type, body.linked_ref_id):
            raise NotFound(code="not_found", resource_type=body.linked_ref_type)
    if assignee != creator:
        _check_assignee_can_view(uow, assignee, body.linked_ref_type, body.linked_ref_id)
    if body.due_at is not None and body.due_at.tzinfo is None:
        raise ValidationFailed("due_at needs a time zone", code="naive_datetime")
    task_id = uuid.uuid7()
    company_id = uow.actor.company_id
    assert company_id is not None
    branch_id = responsibility.default_branch_of(uow, assignee) or responsibility.default_branch_of(uow, owner)
    key = keys.manual_key(task_id)
    now = uow.now()
    issue = IssueModel(
        id=keys.issue_id(company_id, key, 1), company_id=company_id, issue_key=key, occurrence=1, family="common.manual",
        state=IssueState.OPEN.value, root_ref_type="tasks.task", root_ref_id=task_id, title=body.title,
        title_facts={"title": body.title}, fingerprint="", required_permission="tasks.task.read",
        scope_owner_id=owner, scope_branch_id=branch_id, first_seen_at=now, last_changed_at=now,
    )
    uow.add(issue)
    if body.linked_ref_type and body.linked_ref_id:
        facts = SourceCache().read(uow, body.linked_ref_type, body.linked_ref_id)
        uow.add(IssueMember(
            company_id=company_id, issue_id=issue.id, member_key=f"linked:{body.linked_ref_id}", role=MemberRole.EVIDENCE.value,
            ref_type=body.linked_ref_type, ref_id=body.linked_ref_id, ref_version=facts.version if facts else None,
            label=facts.label if facts else "", facts={}, required_permission=facts.required_permission if facts else "tasks.task.read",
            scope_owner_id=facts.owner_user_id if facts else None, scope_branch_id=facts.branch_id if facts else None,
            active=True, added_at=now,
        ))
    uow.flush()
    spec = TaskSpec(
        dedup_key=key, kind="manual", title=body.title, completion_check="assertion",
        required_permission="tasks.task.read",
        facts={"note": body.note} if body.note else {},
        primary_ref_type=body.linked_ref_type, primary_ref_id=body.linked_ref_id,
        owner_user_id=owner, assignee_user_id=assignee,
        due_kind=body.due_kind if body.due_at else DueKind.NONE.value, due_at=body.due_at,
        scope_owner_id=owner, scope_branch_id=branch_id, branch_id=branch_id,
    )
    task = _new_manual(uow, issue, spec, task_id, origin)
    task.assigned_by = creator if assignee != creator else None
    uow.flush()
    settle_issue(uow, issue, created=True)
    return _detail(uow, task)


def _new_manual(uow: UnitOfWork, issue: Issue, spec: Any, task_id: uuid.UUID, origin: str) -> Task:
    task = Task(
        id=task_id, company_id=issue.company_id, branch_id=spec.branch_id, kind=spec.kind, family=issue.family,
        issue_id=issue.id, dedup_key=spec.dedup_key, title=spec.title[:300], facts=spec.facts,
        primary_ref_type=spec.primary_ref_type, primary_ref_id=spec.primary_ref_id, owner_user_id=spec.owner_user_id,
        assignee_user_id=spec.assignee_user_id, due_kind=spec.due_kind, due_at=spec.due_at, state=TaskState.OPEN.value,
        completion_check=spec.completion_check, required_permission=spec.required_permission,
        scope_owner_id=spec.scope_owner_id, scope_branch_id=spec.scope_branch_id, origin=origin,
    )
    uow.add(task)
    uow.flush()
    record_history(uow, task, "created", to_state=task.state)
    emit_task_event(uow, "tasks.task.created", task, from_state=None)
    return task


# ---- snooze (per-user overlay on an issue) ---------------------------------------------------------
def max_snooze_until(tasks: Sequence[TaskInfo], now: datetime) -> datetime:
    """Snooze may not erase an obligation: hard deadlines minus the lead, soft deadlines, overdue cap."""
    bounds: list[datetime] = []
    for t in tasks:
        if t.due_at is None:
            continue
        if t.overdue_emitted_at is not None or t.due_at <= now:
            bounds.append(now + MAX_SNOOZE_OVERDUE)
        elif t.due_kind == DueKind.HARD.value:
            bounds.append(t.due_at - SNOOZE_DEADLINE_LEAD)
        else:
            bounds.append(t.due_at)
    return min(bounds) if bounds else now + MAX_SNOOZE_NO_DEADLINE


def snooze_issue(uow: UnitOfWork, issue_id: uuid.UUID, until: datetime, *, channel: str = "web") -> SnoozeOut:
    user_id = _require_user(uow)
    if until.tzinfo is None:
        raise ValidationFailed("until needs a time zone", code="naive_datetime")
    now = uow.now()
    tasks = [t for t in open_tasks_for(uow, user_id) if t.issue_id == issue_id]
    visible = [t for t in tasks if _sources_visible(uow, t, SourceCache())]
    if not visible:
        raise NotFound(code="not_found", resource_type="tasks.issue")
    if any(t.kind in UNSNOOZABLE_KINDS for t in visible):
        raise ActionNotAllowed("This kind of work cannot be snoozed", code="unsnoozable_kind")
    limit = max_snooze_until(visible, now)
    if until <= now:
        raise ValidationFailed("Snooze until a future time", code="snooze_in_past")
    if until > limit:
        raise SnoozeBeyondDeadline(max_until=limit.isoformat())
    row = uow.session.scalars(
        select(Snooze).where(Snooze.company_id == uow.actor.company_id, Snooze.user_id == user_id, Snooze.issue_id == issue_id).with_for_update()
    ).first()
    if row is None:
        uow.add(Snooze(company_id=uow.actor.company_id, user_id=user_id, issue_id=issue_id, snoozed_until=until, set_at=now, channel=channel))
    else:
        row.snoozed_until = until
        row.set_at = now
        row.channel = channel
    uow.flush()
    return SnoozeOut(issue_id=issue_id, snoozed_until=until, max_until=limit)


def unsnooze_issue(uow: UnitOfWork, issue_id: uuid.UUID) -> SnoozeOut:
    user_id = _require_user(uow)
    row = uow.session.scalars(
        select(Snooze).where(Snooze.company_id == uow.actor.company_id, Snooze.user_id == user_id, Snooze.issue_id == issue_id).with_for_update()
    ).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="tasks.snooze")
    uow.session.delete(row)
    uow.flush()
    return SnoozeOut(issue_id=issue_id, snoozed_until=None, max_until=None)


def wake_snoozes(uow: UnitOfWork, issue_id: uuid.UUID) -> list[uuid.UUID]:
    """Overdue facts wake snoozed items (mandatory policy). Returns the users whose snooze ended."""
    rows = uow.session.scalars(
        select(Snooze).where(Snooze.company_id == uow.actor.company_id, Snooze.issue_id == issue_id, Snooze.snoozed_until > uow.now())
    ).all()
    users = [r.user_id for r in rows]
    for r in rows:
        uow.session.delete(r)
    uow.flush()
    return users


def snooze_task(uow: UnitOfWork, task_id: uuid.UUID, until: datetime) -> SnoozeOut:
    task = _visible_task(uow, task_id)
    if uow.actor.user_id not in (task.owner_user_id, task.assignee_user_id) and not uow.session.scalar(
        select(exists().where(TaskCandidate.task_id == task.id, TaskCandidate.user_id == uow.actor.user_id))
    ):
        raise Forbidden(code="permission_denied", reason="only_responsible_people_snooze")
    return snooze_issue(uow, task.issue_id, until)


def unsnooze_task(uow: UnitOfWork, task_id: uuid.UUID) -> SnoozeOut:
    task = _visible_task(uow, task_id)
    return unsnooze_issue(uow, task.issue_id)


# ---- mark handled for an issue (briefing action) ---------------------------------------------------
def mark_issue_handled(uow: UnitOfWork, issue_id: uuid.UUID, *, reason_code: str | None = None, note: str | None = None) -> HandledResult:
    """Verify every open obligation of the user on the issue against its source.

    Complete → tasks done with evidence. Not complete → an authorised dismissal when a reason is given
    (``tasks.task.dismiss`` covering the task; the issue stays open), otherwise 409 ``not_complete``.
    """
    user_id = _require_user(uow)
    tasks = uow.session.scalars(
        select(Task)
        .where(Task.company_id == uow.actor.company_id, Task.issue_id == issue_id, Task.state.in_(OPEN_STATES), responsible_clause(uow.actor))
        .order_by(Task.id)
        .with_for_update()
    ).all()
    cache = SourceCache()
    tasks = [t for t in tasks if _sources_visible(uow, t, cache)]
    if not tasks:
        raise NotFound(code="not_found", resource_type="tasks.issue")
    if any(t.kind in APPROVAL_KINDS for t in tasks):
        raise ActionNotAllowed("Approvals are decided through the approval request", code="action_not_allowed")
    results = {t.id: completion.check(uow, t) for t in tasks}
    if all(r.complete for r in results.values()):
        issue = _issue_for_update(uow, issue_id)
        for t in tasks:
            close_task(uow, t, Closure(TaskState.DONE.value, dict(results[t.id].evidence), user_id))
        settle_issue(uow, issue, created=False, resolution="completed")
        evidence = {str(k): v.evidence for k, v in results.items()}
        return HandledResult(issue_id=issue_id, outcome="completed", task_ids=tuple(t.id for t in tasks), evidence=evidence)
    if reason_code is None:
        remaining = sorted({r for v in results.values() for r in v.remaining})
        raise NotComplete(remaining=remaining)
    for t in tasks:
        if not results[t.id].complete:
            dismiss_task(uow, t, reason_code, note)
        else:
            close_task(uow, t, Closure(TaskState.DONE.value, dict(results[t.id].evidence), user_id))
    return HandledResult(issue_id=issue_id, outcome="dismissed", task_ids=tuple(t.id for t in tasks), evidence={"reason_code": reason_code})


def dismiss_issue(uow: UnitOfWork, issue_id: uuid.UUID, *, reason_code: str, note: str | None = None) -> HandledResult:
    _require_user(uow)
    tasks = uow.session.scalars(
        select(Task)
        .where(Task.company_id == uow.actor.company_id, Task.issue_id == issue_id, Task.state.in_(OPEN_STATES), task_visible_clause(uow.actor))
        .order_by(Task.id)
        .with_for_update()
    ).all()
    cache = SourceCache()
    tasks = [t for t in tasks if _sources_visible(uow, t, cache)]
    if not tasks:
        raise NotFound(code="not_found", resource_type="tasks.issue")
    for t in tasks:
        dismiss_task(uow, t, reason_code, note)
    return HandledResult(issue_id=issue_id, outcome="dismissed", task_ids=tuple(t.id for t in tasks), evidence={"reason_code": reason_code})


def can_dismiss(uow: UnitOfWork, task: TaskInfo) -> bool:
    if task.kind in UNDISMISSABLE_KINDS or not task.is_open:
        return False
    return bool(uow.session.scalar(select(exists().where(Task.id == task.id, task_scope_clause(uow.actor, "dismiss")))))


def can_assign(uow: UnitOfWork, task: TaskInfo) -> bool:
    if task.kind in APPROVAL_KINDS or not task.is_open:
        return False
    if uow.actor.user_id == task.owner_user_id:
        return True
    return bool(uow.session.scalar(select(exists().where(Task.id == task.id, task_scope_clause(uow.actor, "assign")))))


# ---- my open tasks (the fallback list) ---------------------------------------------------------------
def list_my_open_tasks(uow: UnitOfWork) -> list[InboxItem]:
    """An independent, simple, permission-filtered list ordered by due date (briefing fallback)."""
    user_id = _require_user(uow)
    tasks = uow.session.scalars(
        select(Task)
        .where(Task.company_id == uow.actor.company_id, Task.state.in_(OPEN_STATES), responsible_clause(uow.actor))
        .order_by(Task.due_at.asc().nulls_last(), Task.id)
    ).all()
    cache = SourceCache()
    visible = [t for t in tasks if _sources_visible(uow, t, cache)]
    snoozes = snoozes_for(uow, user_id)
    blocked = _blocked_ids(uow, [t.id for t in visible])
    return [_inbox_item(uow, t, snoozes, blocked, cache) for t in visible]


# ---- reminders (own only) ---------------------------------------------------------------------------
def _own_reminder(uow: UnitOfWork, reminder_id: uuid.UUID, *, for_update: bool = False) -> Reminder:
    user_id = _require_user(uow)
    stmt = select(Reminder).where(Reminder.id == reminder_id, Reminder.company_id == uow.actor.company_id, Reminder.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="tasks.reminder")
    return row


def _reminder_out(r: Reminder) -> ReminderOut:
    return ReminderOut(id=r.id, text=r.text, remind_at=r.remind_at, time_zone=r.time_zone, linked_ref_type=r.linked_ref_type,
                       linked_ref_id=r.linked_ref_id, state=r.state, version=r.version, created_at=r.created_at)


def create_reminder(uow: UnitOfWork, body: ReminderCreate) -> ReminderOut:
    user_id = _require_user(uow)
    if body.remind_at.tzinfo is None:
        raise ValidationFailed("remind_at needs a time zone", code="naive_datetime")
    if (body.linked_ref_type is None) != (body.linked_ref_id is None):
        raise ValidationFailed("linked_ref_type and linked_ref_id go together", code="linked_ref_incomplete")
    if body.linked_ref_type and body.linked_ref_id and not can_view_source(uow, body.linked_ref_type, body.linked_ref_id):
        raise NotFound(code="not_found", resource_type=body.linked_ref_type)
    zone = responsibility.user_calendar(uow, user_id).time_zone
    row = Reminder(
        company_id=uow.actor.company_id, user_id=user_id, text=body.text.strip(), remind_at=body.remind_at, time_zone=zone,
        linked_ref_type=body.linked_ref_type, linked_ref_id=body.linked_ref_id, state=ReminderState.PENDING.value,
    )
    uow.add(row)
    uow.flush()
    return _reminder_out(row)


def list_reminders(uow: UnitOfWork, *, include_closed: bool = False) -> ReminderList:
    user_id = _require_user(uow)
    states = ("pending", "fired", "done", "cancelled") if include_closed else ("pending", "fired")
    rows = uow.session.scalars(
        select(Reminder).where(Reminder.company_id == uow.actor.company_id, Reminder.user_id == user_id, Reminder.state.in_(states))
        .order_by(Reminder.remind_at, Reminder.id)
    ).all()
    return ReminderList(items=[_reminder_out(r) for r in rows])


def get_reminder(uow: UnitOfWork, reminder_id: uuid.UUID) -> ReminderOut:
    return _reminder_out(_own_reminder(uow, reminder_id))


def update_reminder(uow: UnitOfWork, reminder_id: uuid.UUID, body: ReminderUpdate) -> ReminderOut:
    row = _own_reminder(uow, reminder_id, for_update=True)
    uow.expect_version(row, body.expected_version)
    now = uow.now()
    if body.text is not None:
        row.text = body.text.strip()
    if body.remind_at is not None:
        if body.remind_at.tzinfo is None:
            raise ValidationFailed("remind_at needs a time zone", code="naive_datetime")
        row.remind_at = body.remind_at
        if row.state == ReminderState.FIRED.value:
            row.state = ReminderState.PENDING.value
            row.fired_at = None
    if body.state is not None and body.state != row.state:
        row.state = body.state
        row.done_at = now if body.state in ("done", "cancelled") else None
    uow.flush()
    return _reminder_out(row)


def cancel_reminder(uow: UnitOfWork, reminder_id: uuid.UUID) -> ReminderOut:
    row = _own_reminder(uow, reminder_id, for_update=True)
    if row.state not in ("done", "cancelled"):
        row.state = ReminderState.CANCELLED.value
        row.done_at = uow.now()
    uow.flush()
    return _reminder_out(row)


def complete_reminder(uow: UnitOfWork, reminder_id: uuid.UUID) -> ReminderOut:
    row = _own_reminder(uow, reminder_id, for_update=True)
    if row.state in ("pending", "fired"):
        row.state = ReminderState.DONE.value
        row.done_at = uow.now()
    uow.flush()
    return _reminder_out(row)


def reminder_for_issue_id(uow: UnitOfWork, user_id: uuid.UUID, issue_id: uuid.UUID) -> ReminderInfo | None:
    """Reminder items carry ``issue_id = uuid5(company|reminder:{id}|1)``; map it back for the owner."""
    company_id = uow.actor.company_id
    assert company_id is not None
    for r in reminders_for(uow, user_id, states=("pending", "fired")):
        if keys.issue_id(company_id, keys.reminder_key(r.id), 1) == issue_id:
            return r
    return None


# ---- jobs --------------------------------------------------------------------------------------------
def sweep_overdue(uow: UnitOfWork, *, limit: int = 500) -> int:
    """Emit ``tasks.task.became_overdue`` once per overdue task; lapse quote-expiry tasks (indexed query)."""
    now = uow.now()
    tasks = uow.session.scalars(
        select(Task)
        .where(Task.company_id == uow.actor.company_id, Task.state.in_(OPEN_STATES), Task.overdue_emitted_at.is_(None),
               Task.due_at.is_not(None), Task.due_at <= now)
        .order_by(Task.due_at, Task.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for task in tasks:
        if task.kind == "quote_expiry":
            issue = _issue_for_update(uow, task.issue_id)
            close_task(uow, task, Closure(TaskState.EXPIRED.value, {"reason": "quote_lapsed"}))
            settle_issue(uow, issue, created=False, resolution="source_closed")
            continue
        task.overdue_emitted_at = now
        uow.flush()
        record_history(uow, task, "became_overdue", from_state=task.state, to_state=task.state)
        uow.emit("tasks.task.became_overdue", aggregate_id=task.id, aggregate_version=task.version,
                 payload={"task_id": str(task.id), "issue_id": str(task.issue_id), "due_at": task.due_at.isoformat() if task.due_at else None})
        settle_issue(uow, _issue_for_update(uow, task.issue_id), created=False, resolution=None)
    return len(tasks)


def dispatch_reminders(uow: UnitOfWork, *, limit: int = 500) -> int:
    now = uow.now()
    rows = uow.session.scalars(
        select(Reminder)
        .where(Reminder.company_id == uow.actor.company_id, Reminder.state == ReminderState.PENDING.value, Reminder.remind_at <= now)
        .order_by(Reminder.remind_at, Reminder.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for r in rows:
        r.state = ReminderState.FIRED.value
        r.fired_at = now
        uow.flush()
        uow.emit("tasks.reminder.fired", aggregate_id=r.id, aggregate_version=r.version,
                 payload={"reminder_id": str(r.id), "user_id": str(r.user_id)})
    return len(rows)


def issue_audience(uow: UnitOfWork, issue_id: uuid.UUID) -> set[uuid.UUID]:
    """Users with a stake in an issue: responsible people, candidates, initiators and the watcher."""
    out: set[uuid.UUID] = set()
    issue = uow.session.get(Issue, issue_id)
    if issue is None:
        return out
    if issue.scope_owner_id is not None:
        out.add(issue.scope_owner_id)
    for owner, assignee, initiator in uow.session.execute(
        select(Task.owner_user_id, Task.assignee_user_id, Task.initiator_user_id).where(Task.issue_id == issue_id)
    ):
        out.update(u for u in (owner, assignee, initiator) if u is not None)
    out.update(uow.session.scalars(
        select(TaskCandidate.user_id).join(Task, Task.id == TaskCandidate.task_id).where(Task.issue_id == issue_id)
    ))
    return out


def tasks_closed_states() -> tuple[str, ...]:
    return TERMINAL_STATES


# ---- configuration and fixture support (idempotent on business keys) -----------------------------------
def ensure_onboarding_template(
    uow: UnitOfWork, *, role_key: str, name: str, steps: list[dict[str, str]], checkin_after_workdays: int = 2
) -> uuid.UUID:
    from app.modules.tasks.completion import known_checks
    from app.modules.tasks.models import OnboardingTemplate

    for step in steps:
        if step.get("completion_check") not in known_checks():
            raise ValidationFailed(f"unknown completion check {step.get('completion_check')}", code="unknown_completion_check")
    existing = uow.session.scalars(
        select(OnboardingTemplate).where(OnboardingTemplate.company_id == uow.actor.company_id,
                                         OnboardingTemplate.role_key == role_key, OnboardingTemplate.active.is_(True))
        .order_by(OnboardingTemplate.template_version.desc())
    ).first()
    if existing is not None and existing.steps == steps and existing.checkin_after_workdays == checkin_after_workdays:
        return existing.id
    version = (existing.template_version + 1) if existing is not None else 1
    if existing is not None:
        existing.active = False
    row = OnboardingTemplate(company_id=uow.actor.company_id, role_key=role_key, template_version=version, name=name,
                             steps=steps, checkin_after_workdays=checkin_after_workdays, active=True)
    uow.add(row)
    uow.flush()
    return row.id


def ensure_queue(uow: UnitOfWork, *, code: str, name: str, family_prefix: str) -> uuid.UUID:
    from app.modules.tasks.models import Queue

    existing = uow.session.scalars(select(Queue).where(Queue.company_id == uow.actor.company_id, Queue.code == code)).first()
    if existing is not None:
        return existing.id
    row = Queue(company_id=uow.actor.company_id, code=code, name=name, family_prefix=family_prefix, active=True)
    uow.add(row)
    uow.flush()
    return row.id


def apply_onboarding(uow: UnitOfWork, user_id: uuid.UUID, *, activated_at: datetime) -> int:
    """Re-derive a member's onboarding from the current template (idempotent; used when the template is
    configured after the activation event was processed)."""
    from app.modules.tasks.issues import apply_outcome
    from app.modules.tasks.rules.families import derive_onboarding
    from app.platform.identity.models import Membership

    membership = uow.session.scalars(
        select(Membership).where(Membership.company_id == uow.actor.company_id, Membership.user_id == user_id)
    ).first()
    if membership is None or membership.status != "active":
        return 0
    manager = responsibility.membership_user(uow, membership.manager_membership_id)
    count = 0
    for outcome in derive_onboarding(uow, user_id, membership_id=membership.id, manager_user_id=manager, activated_at=activated_at):
        if apply_outcome(uow, outcome, None) is not None:
            count += 1
    return count


def find_open_manual_task(uow: UnitOfWork, *, owner_user_id: uuid.UUID, title: str) -> uuid.UUID | None:
    return uow.session.scalar(
        select(Task.id).where(Task.company_id == uow.actor.company_id, Task.kind == "manual", Task.title == title,
                              Task.owner_user_id == owner_user_id).order_by(Task.created_at).limit(1)
    )


def find_reminder(uow: UnitOfWork, *, user_id: uuid.UUID, text: str) -> uuid.UUID | None:
    return uow.session.scalar(
        select(Reminder.id).where(Reminder.company_id == uow.actor.company_id, Reminder.user_id == user_id, Reminder.text == text)
        .order_by(Reminder.created_at).limit(1)
    )
