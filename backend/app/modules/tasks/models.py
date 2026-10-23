"""Tasks tables: issues (stable root-cause ids), members, obligations, candidates, dependencies,
history, the change log, personal reminders, per-user snoozes, onboarding templates and queues.

Invariants (docs/design/source/briefing.md §2-§3, adapted to docs/architecture):
- ``tasks_issue.id`` is UUIDv5 of ``company_id|issue_key|occurrence`` (``issue_keys.issue_id``).
- At most one live occurrence per issue key (partial unique on open/info).
- At most one open task per dedup key; terminal tasks are never reopened (a regression opens a new row).
- ``tasks_change_log`` and ``tasks_task_history`` are append-only; the change log is the only source of
  "what changed" in briefings.
- Reminders are private to their owner and are never counted as obligations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ActorStampMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


class IssueState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    INFO = "info"


class IssueResolution(StrEnum):
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    SOURCE_CLOSED = "source_closed"
    SUPERSEDED = "superseded"


class TaskState(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DISMISSED = "dismissed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


OPEN_STATES = (TaskState.OPEN.value, TaskState.IN_PROGRESS.value)
TERMINAL_STATES = (
    TaskState.DONE.value,
    TaskState.DISMISSED.value,
    TaskState.CANCELLED.value,
    TaskState.EXPIRED.value,
)


class DueKind(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    NONE = "none"


class TaskOrigin(StrEnum):
    RULE = "rule"
    USER = "user"
    AUTOMATION = "automation"
    SEED = "seed"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    COSTING = "costing"
    FINANCE = "finance"


class MemberRole(StrEnum):
    ROOT = "root"
    EVIDENCE = "evidence"
    RELATED = "related"


class CandidateReason(StrEnum):
    APPROVER = "approver"
    DELEGATE = "delegate"
    QUEUE = "queue"


class ReminderState(StrEnum):
    PENDING = "pending"
    FIRED = "fired"
    DONE = "done"
    CANCELLED = "cancelled"


class DismissalReason(StrEnum):
    """Authorised dismissal reasons (enum + free note), recorded and audited."""

    HANDLED_OUTSIDE_SYSTEM = "handled_outside_system"
    NOT_APPLICABLE = "not_applicable"
    DUPLICATE = "duplicate"
    CUSTOMER_WITHDREW = "customer_withdrew"
    NO_ACTION_NEEDED = "no_action_needed"


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{e.value}'" for e in enum)


class Issue(TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "tasks_issue"

    #: UUIDv5(company|issue_key|occurrence) — never a UUIDv7, so regenerations keep the same id
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    family: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=IssueState.OPEN.value)
    root_ref_type: Mapped[str] = mapped_column(String(80), nullable=False)
    root_ref_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    title_facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    scope_branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default=Sensitivity.NORMAL.value)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: the domain event that last changed the fingerprint (recommendation invalidation cause)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index("uq_tasks_issue_key_occurrence", "company_id", "issue_key", "occurrence", unique=True),
        Index(
            "uq_tasks_issue_live_key",
            "company_id",
            "issue_key",
            unique=True,
            postgresql_where="state IN ('open','info')",
        ),
        Index("ix_tasks_issue_family_state", "company_id", "family", "state"),
        Index("ix_tasks_issue_root", "company_id", "root_ref_type", "root_ref_id"),
        Index("ix_tasks_issue_scope_owner", "company_id", "scope_owner_id", "state"),
        CheckConstraint(f"state IN ({_values(IssueState)})", name="state_values"),
        CheckConstraint(f"resolution IS NULL OR resolution IN ({_values(IssueResolution)})", name="resolution_values"),
        CheckConstraint(f"sensitivity IN ({_values(Sensitivity)})", name="sensitivity_values"),
        CheckConstraint("occurrence >= 1", name="occurrence_positive"),
        CheckConstraint("(state = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_at_matches_state"),
    )


class IssueMember(IdMixin, TenantMixin, Base):
    """A grouped symptom of an issue (source record, linked draft, evidence)."""

    __tablename__ = "tasks_issue_member"

    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_issue.id"), nullable=False)
    member_key: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=MemberRole.RELATED.value)
    ref_type: Mapped[str] = mapped_column(String(80), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ref_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    scope_branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_tasks_issue_member_key", "issue_id", "member_key", unique=True),
        Index("ix_tasks_issue_member_ref", "company_id", "ref_type", "ref_id"),
        CheckConstraint(f"role IN ({_values(MemberRole)})", name="role_values"),
    )


class Task(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    """An obligation. Terminal rows are immutable; a regressing source opens a new row."""

    __tablename__ = "tasks_task"

    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("branch.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    family: Mapped[str] = mapped_column(String(60), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_issue.id"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    primary_ref_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    primary_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    primary_ref_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    #: who requested the work (approval initiator) — receives "handled for you" when others close it
    initiator_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    queue_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    due_kind: Mapped[str] = mapped_column(String(10), nullable=False, default=DueKind.NONE.value)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskState.OPEN.value)
    completion_check: Mapped[str] = mapped_column(String(60), nullable=False)
    completion_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    dismissal_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dismissal_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: who closed it (user or None for the system); "handled for you" compares it with the viewer
    closed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=True)
    overdue_emitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    scope_branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default=Sensitivity.NORMAL.value)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskOrigin.RULE.value)

    __table_args__ = (
        Index(
            "uq_tasks_task_open_dedup",
            "company_id",
            "dedup_key",
            unique=True,
            postgresql_where="state IN ('open','in_progress')",
        ),
        Index("ix_tasks_task_assignee", "company_id", "assignee_user_id", "state", "due_at"),
        Index("ix_tasks_task_owner", "company_id", "owner_user_id", "state"),
        Index("ix_tasks_task_issue", "issue_id"),
        Index("ix_tasks_task_primary_ref", "company_id", "primary_ref_type", "primary_ref_id"),
        Index("ix_tasks_task_dedup", "company_id", "dedup_key"),
        Index(
            "ix_tasks_task_overdue_sweep",
            "due_at",
            postgresql_where="state IN ('open','in_progress') AND overdue_emitted_at IS NULL",
        ),
        CheckConstraint(f"state IN ({_values(TaskState)})", name="state_values"),
        CheckConstraint(f"due_kind IN ({_values(DueKind)})", name="due_kind_values"),
        CheckConstraint(f"origin IN ({_values(TaskOrigin)})", name="origin_values"),
        CheckConstraint(f"sensitivity IN ({_values(Sensitivity)})", name="sensitivity_values"),
        CheckConstraint("(due_kind = 'none') = (due_at IS NULL)", name="due_kind_matches_due_at"),
        CheckConstraint("state <> 'done' OR completion_evidence IS NOT NULL", name="done_requires_evidence"),
        CheckConstraint("state <> 'dismissed' OR dismissal_reason_code IS NOT NULL", name="dismissed_requires_reason"),
        CheckConstraint(
            "(state IN ('open','in_progress')) = (closed_at IS NULL)", name="terminal_requires_closed_at"
        ),
    )


class TaskCandidate(IdMixin, TenantMixin, Base):
    """Users who may act on a task without owning it (eligible approvers)."""

    __tablename__ = "tasks_task_candidate"

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_task.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default=CandidateReason.APPROVER.value)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_tasks_task_candidate", "task_id", "user_id", unique=True),
        Index("ix_tasks_task_candidate_user", "company_id", "user_id"),
        CheckConstraint(f"reason IN ({_values(CandidateReason)})", name="reason_values"),
    )


class TaskDependency(IdMixin, TenantMixin, Base):
    """A task waits for another issue (e.g. a reply waits for the review decision). Blocked is derived."""

    __tablename__ = "tasks_dependency"

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_task.id"), nullable=False)
    depends_on_issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_issue.id"), nullable=False)
    condition_code: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uq_tasks_dependency", "task_id", "depends_on_issue_id", unique=True),
        Index("ix_tasks_dependency_target", "depends_on_issue_id"),
        CheckConstraint("condition_code <> ''", name="condition_present"),
    )


class TaskHistory(IdMixin, TenantMixin, Base):
    __tablename__ = "tasks_task_history"
    __append_only__ = True

    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_task.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_tasks_task_history_task", "task_id", "at"),
        CheckConstraint("actor_kind IN ('user','system','automation','agent')", name="actor_kind_values"),
    )


class ChangeLog(IdMixin, TenantMixin, Base):
    """The only source of "changes since your last visit" and the delta view."""

    __tablename__ = "tasks_change_log"
    __append_only__ = True

    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_issue.id"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    fact_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(80), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ref_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_code: Mapped[str] = mapped_column(String(60), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    scope_branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default=Sensitivity.NORMAL.value)

    __table_args__ = (
        Index("uq_tasks_change_log_event_issue", "event_id", "issue_id", unique=True),
        Index("ix_tasks_change_log_issue_fact", "company_id", "issue_id", "fact_at"),
        Index("ix_tasks_change_log_fact", "company_id", "fact_at"),
        CheckConstraint(f"sensitivity IN ({_values(Sensitivity)})", name="sensitivity_values"),
    )


class Reminder(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    """A private personal reminder: visible only to ``user_id``, never counted, never delegated."""

    __tablename__ = "tasks_reminder"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    text: Mapped[str] = mapped_column(String(280), nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    linked_ref_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    linked_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    linked_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("tasks_task.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default=ReminderState.PENDING.value)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tasks_reminder_user", "company_id", "user_id", "state", "remind_at"),
        Index("ix_tasks_reminder_due", "remind_at", postgresql_where="state = 'pending'"),
        CheckConstraint(f"state IN ({_values(ReminderState)})", name="state_values"),
        CheckConstraint("length(btrim(text)) > 0", name="text_present"),
        CheckConstraint("(linked_ref_type IS NULL) = (linked_ref_id IS NULL)", name="linked_ref_pair"),
    )


class Snooze(IdMixin, TenantMixin, Base):
    """A per-user presentation overlay on an issue. Never changes due dates, task state or counts."""

    __tablename__ = "tasks_snooze"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snoozed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("uq_tasks_snooze_user_issue", "company_id", "user_id", "issue_id", unique=True),
        CheckConstraint("snoozed_until > set_at", name="until_after_set"),
    )


class OnboardingTemplate(IdMixin, TenantMixin, TimestampMixin, Base):
    """Onboarding steps per role template (``steps``: [{step_key, title, completion_check}])."""

    __tablename__ = "tasks_onboarding_template"

    role_key: Mapped[str] = mapped_column(String(40), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    steps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    checkin_after_workdays: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("uq_tasks_onboarding_template", "company_id", "role_key", "template_version", unique=True),
        CheckConstraint("checkin_after_workdays BETWEEN 0 AND 10", name="checkin_range"),
        CheckConstraint("jsonb_typeof(steps) = 'array'", name="steps_is_array"),
    )


class Queue(IdMixin, TenantMixin, TimestampMixin, Base):
    """Fallback destination when no responsible person can be resolved; work is never silently dropped."""

    __tablename__ = "tasks_queue"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    family_prefix: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("uq_tasks_queue_code", "company_id", "code", unique=True),)


__all__ = [
    "OPEN_STATES",
    "TERMINAL_STATES",
    "ChangeLog",
    "DismissalReason",
    "DueKind",
    "Issue",
    "IssueMember",
    "IssueResolution",
    "IssueState",
    "MemberRole",
    "OnboardingTemplate",
    "Queue",
    "Reminder",
    "ReminderState",
    "Sensitivity",
    "Snooze",
    "Task",
    "TaskCandidate",
    "TaskDependency",
    "TaskHistory",
    "TaskOrigin",
    "TaskState",
]
