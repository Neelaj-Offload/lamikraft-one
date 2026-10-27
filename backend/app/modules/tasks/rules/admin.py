"""Slice-1 administrative rule families.

- ``common.offboarding`` (``identity.membership.deactivated``): cancel the member's private reminders,
  re-resolve their rule-derived work, cancel their onboarding, and open "Reassign N open tasks" for the
  named successor, their manager or the admin queue (work is never silently dropped).
- ``admin.failed_jobs`` (``system.job.dead_lettered``, ``briefings.briefing.generation_failed``): an admin
  obligation per dead-lettered job (its rule families are reported as partial in briefings until it is
  closed) and one per briefing whose generation keeps failing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

from app.modules.tasks import issue_keys as keys
from app.modules.tasks import responsibility
from app.modules.tasks.models import (
    OPEN_STATES,
    DueKind,
    Issue,
    IssueResolution,
    IssueState,
    MemberRole,
    Reminder,
    ReminderState,
    Task,
    TaskCandidate,
    TaskState,
)
from app.modules.tasks.rules.families import _closer, _closing_outcome
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

OFFBOARDING_FAMILY = "common.offboarding"
FAILED_JOBS_FAMILY = "admin.failed_jobs"
BRIEFING_FAILURE_THRESHOLD = 3


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# ---- common.offboarding (offboarding:{user}:reassign) ------------------------------------------------------
def cancel_member_reminders(uow: UnitOfWork, user_id: uuid.UUID) -> int:
    """A departed member's private reminders are cancelled (nobody else may ever see them)."""
    now = uow.now()
    rows = uow.session.scalars(
        select(Reminder)
        .where(Reminder.company_id == uow.actor.company_id, Reminder.user_id == user_id,
               Reminder.state.in_((ReminderState.PENDING.value, ReminderState.FIRED.value)))
        .order_by(Reminder.id)
        .with_for_update()
    ).all()
    for row in rows:
        row.state = ReminderState.CANCELLED.value
        row.done_at = now
    uow.flush()
    return len(rows)


def member_open_work(uow: UnitOfWork, user_id: uuid.UUID) -> list[Task]:
    """Open obligations the member owns or does (approval candidacies follow eligibility instead)."""
    return list(
        uow.session.scalars(
            select(Task)
            .where(Task.company_id == uow.actor.company_id, Task.state.in_(OPEN_STATES),
                   or_(Task.owner_user_id == user_id, Task.assignee_user_id == user_id))
            .order_by(Task.id)
        )
    )


def member_rule_issues(uow: UnitOfWork, user_id: uuid.UUID, families: tuple[str, ...]) -> list[tuple[str, uuid.UUID]]:
    """(family, root id) of live rule issues where the member is owner, assignee or candidate."""
    responsible = or_(
        Task.owner_user_id == user_id,
        Task.assignee_user_id == user_id,
        Task.id.in_(select(TaskCandidate.task_id).where(TaskCandidate.user_id == user_id)),
    )
    rows = uow.session.execute(
        select(Issue.family, Issue.root_ref_id)
        .join(Task, Task.issue_id == Issue.id)
        .where(Issue.company_id == uow.actor.company_id, Issue.state == IssueState.OPEN.value, Issue.family.in_(families),
               Task.state.in_(OPEN_STATES), responsible)
        .distinct()
        .order_by(Issue.family, Issue.root_ref_id)
    ).all()
    return [(family, root_id) for family, root_id in rows]


def member_onboarding_keys(uow: UnitOfWork, user_id: uuid.UUID) -> list[str]:
    """Live onboarding issues about the member (their steps and their manager's check-in)."""
    return list(
        uow.session.scalars(
            select(Issue.issue_key)
            .where(Issue.company_id == uow.actor.company_id, Issue.family == "common.onboarding",
                   Issue.root_ref_type == "identity.user", Issue.root_ref_id == user_id,
                   Issue.state.in_((IssueState.OPEN.value, IssueState.INFO.value)))
            .order_by(Issue.issue_key)
        )
    )


def close_onboarding(uow: UnitOfWork, issue_key: str, event: DomainEvent | None) -> IssueOutcome | None:
    return _closing_outcome(uow, issue_key, Closure(TaskState.CANCELLED.value, {"reason": "member_deactivated"}, _closer(event)),
                            IssueResolution.SOURCE_CLOSED.value)


def derive_offboarding(
    uow: UnitOfWork, user_id: uuid.UUID, *, reassign_to_user_id: uuid.UUID | None, event: DomainEvent | None = None
) -> IssueOutcome | None:
    """"Reassign N open tasks" for the departed member's remaining work.

    Derived after rule work was re-resolved, so N counts what no rule can move by itself (manual tasks,
    check-ins the member owned). It goes to the named successor, else their manager, else the admin
    queue, and completes when the tasks table shows no open work left on the member."""
    key = keys.offboarding_key(user_id)
    remaining = member_open_work(uow, user_id)
    if not remaining:
        return _closing_outcome(uow, key, Closure(TaskState.DONE.value, {"reason": "no_open_work"}, _closer(event)),
                                IssueResolution.COMPLETED.value)
    name = responsibility.display_names(uow, [user_id]).get(user_id) or "a former member"
    count = len(remaining)
    title = f"Reassign {count} open task{'s' if count != 1 else ''} of {name}"
    named = responsibility.resolve(uow, OFFBOARDING_FAMILY, [reassign_to_user_id, responsibility.manager_of(uow, user_id)])
    cal = responsibility.company_calendar(uow)
    at = event.occurred_at if event is not None else uow.now()
    branch_id = responsibility.default_branch_of(uow, user_id)
    return IssueOutcome(
        issue_key=key,
        family=OFFBOARDING_FAMILY,
        root_ref_type="identity.user",
        root_ref_id=user_id,
        title=title,
        title_facts={"member": name, "count": count},
        required_permission="tasks.task.assign",
        scope_owner_id=named.owner_user_id,
        scope_branch_id=branch_id,
        members=[
            MemberSpec(key=f"user:{user_id}", ref_type="identity.user", ref_id=user_id, ref_version=None, label=name,
                       facts={}, required_permission="org.directory.read", role=MemberRole.ROOT.value, scope_owner_id=user_id)
        ],
        tasks=[
            TaskSpec(
                dedup_key=key, kind="reassign_work", title=title, completion_check="member_work_reassigned",
                required_permission="tasks.task.assign",
                facts={"member_user_id": str(user_id), "member": name, "count": count},
                primary_ref_type="identity.user", primary_ref_id=user_id,
                owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value, due_at=cal.end_of_day_due(cal.work_date(at)),
                scope_owner_id=named.owner_user_id, scope_branch_id=branch_id, branch_id=branch_id,
            )
        ],
        closure=Closure(TaskState.DONE.value, {"reason": "no_open_work"}, _closer(event)),
        resolution=IssueResolution.COMPLETED.value,
        first_seen_at=at,
    )


# ---- admin.failed_jobs (failed_job:{job}, briefing_failed:{briefing}) ----------------------------------------
def _admin_outcome(
    uow: UnitOfWork, *, issue_key: str, root_type: str, root_id: uuid.UUID, title: str, facts: dict[str, Any],
    completion_check: str, at: datetime,
) -> IssueOutcome:
    """One administrative obligation for the queue managers (candidates), else the admin queue."""
    managers = tuple(responsibility.queue_managers(uow))
    cal = responsibility.company_calendar(uow)
    return IssueOutcome(
        issue_key=issue_key,
        family=FAILED_JOBS_FAMILY,
        root_ref_type=root_type,
        root_ref_id=root_id,
        title=title,
        title_facts=facts,
        required_permission="tasks.queue.manage",
        tasks=[
            TaskSpec(
                dedup_key=issue_key, kind="failed_job", title=title, completion_check=completion_check,
                required_permission="tasks.queue.manage", facts=facts, primary_ref_type=root_type, primary_ref_id=root_id,
                queue_code=None if managers else "admin", candidates=managers,
                due_kind=DueKind.SOFT.value, due_at=cal.end_of_day_due(cal.work_date(at)),
            )
        ],
        closure=Closure(TaskState.DONE.value, {"reason": "recovered"}),
        resolution=IssueResolution.COMPLETED.value,
        first_seen_at=at,
    )


def derive_failed_job(uow: UnitOfWork, event: DomainEvent, families: tuple[str, ...]) -> IssueOutcome | None:
    """A dead-lettered job becomes an admin obligation; ``families`` (the rule families its handler
    serves) are reported as partial in briefings until the obligation is closed."""
    payload = event.payload or {}
    job_id = _uuid(payload.get("job_id")) or event.aggregate_id
    if job_id is None:
        return None
    kind = str(payload.get("kind") or "job")
    handler = payload.get("handler_key")
    return _admin_outcome(
        uow, issue_key=keys.failed_job_key(job_id), root_type="system.job", root_id=job_id,
        title=f"Background job failed: {handler or kind}",
        facts={"job_kind": kind, "handler_key": handler, "families": list(families), "since": event.occurred_at.isoformat()},
        completion_check="assertion", at=event.occurred_at,
    )


def partial_families(uow: UnitOfWork) -> list[dict[str, Any]]:
    """Rule families with a dead-lettered trigger still unresolved: [{family, since}] (earliest first)."""
    rows = uow.session.scalars(
        select(Issue)
        .where(Issue.company_id == uow.actor.company_id, Issue.family == FAILED_JOBS_FAMILY,
               Issue.state == IssueState.OPEN.value, Issue.root_ref_type == "system.job")
        .order_by(Issue.first_seen_at, Issue.id)
    ).all()
    since: dict[str, str] = {}
    for issue in rows:
        for family in (issue.title_facts or {}).get("families") or []:
            since.setdefault(str(family), issue.first_seen_at.isoformat())
    return [{"family": f, "since": s} for f, s in sorted(since.items(), key=lambda kv: (kv[1], kv[0]))]


def derive_briefing_failures(uow: UnitOfWork, event: DomainEvent) -> IssueOutcome | None:
    """Repeated generation failures of one member's briefing become an admin obligation (the member keeps
    the deterministic fallback meanwhile). Below the threshold nothing is opened."""
    from app.modules.briefings import service as briefings  # briefings builds on tasks: imported lazily

    briefing_id = _uuid((event.payload or {}).get("briefing_id")) or event.aggregate_id
    if briefing_id is None:
        return None
    info = briefings.failure_info(uow, briefing_id)
    if info is None or info.failures < BRIEFING_FAILURE_THRESHOLD:
        return None
    name = responsibility.display_names(uow, [info.user_id]).get(info.user_id) or "a member"
    return _admin_outcome(
        uow, issue_key=keys.briefing_failure_key(briefing_id), root_type="briefings.briefing", root_id=briefing_id,
        title=f"Briefing generation keeps failing for {name}",
        facts={"user_id": str(info.user_id), "work_date": info.work_date.isoformat(), "failures": info.failures,
               "error_code": info.error_code},
        completion_check="briefing_recovered", at=event.occurred_at,
    )
