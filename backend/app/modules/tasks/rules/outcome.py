"""What a rule derives for one issue key from current source state (events are only triggers)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.tasks.models import IssueResolution, MemberRole, Sensitivity, TaskState


@dataclass(frozen=True)
class MemberSpec:
    key: str
    ref_type: str
    ref_id: uuid.UUID
    ref_version: int | None
    label: str
    facts: dict[str, Any]
    required_permission: str
    role: str = MemberRole.RELATED.value
    scope_owner_id: uuid.UUID | None = None
    scope_branch_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TaskSpec:
    dedup_key: str
    kind: str
    title: str
    completion_check: str
    required_permission: str
    facts: dict[str, Any] = field(default_factory=dict)
    primary_ref_type: str | None = None
    primary_ref_id: uuid.UUID | None = None
    primary_ref_version: int | None = None
    owner_user_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    initiator_user_id: uuid.UUID | None = None
    queue_code: str | None = None
    due_kind: str = "none"
    due_at: datetime | None = None
    scope_owner_id: uuid.UUID | None = None
    scope_branch_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    candidates: tuple[uuid.UUID, ...] = ()
    #: (issue key, condition code): this task waits while that issue is open
    depends_on: tuple[tuple[str, str], ...] = ()
    sensitivity: str = Sensitivity.NORMAL.value


@dataclass(frozen=True)
class Closure:
    state: str = TaskState.DONE.value
    evidence: dict[str, Any] = field(default_factory=dict)
    closed_by: uuid.UUID | None = None


@dataclass(frozen=True)
class ChangeSpec:
    change_code: str
    ref_type: str
    ref_id: uuid.UUID
    ref_version: int | None
    fact_at: datetime
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    actor_user_id: uuid.UUID | None = None


@dataclass
class IssueOutcome:
    issue_key: str
    family: str
    root_ref_type: str
    root_ref_id: uuid.UUID
    title: str
    required_permission: str
    title_facts: dict[str, Any] = field(default_factory=dict)
    scope_owner_id: uuid.UUID | None = None
    scope_branch_id: uuid.UUID | None = None
    sensitivity: str = Sensitivity.NORMAL.value
    #: an informational stream (state ``info``; no obligation)
    info: bool = False
    members: list[MemberSpec] = field(default_factory=list)
    #: the open obligations that should exist now; open rule tasks not listed are closed
    tasks: list[TaskSpec] = field(default_factory=list)
    closure: Closure = field(default_factory=Closure)
    closures: dict[str, Closure] = field(default_factory=dict)
    changes: list[ChangeSpec] = field(default_factory=list)
    #: resolve the issue when no open obligation remains (None keeps it open while the cause persists)
    resolution: str | None = IssueResolution.COMPLETED.value
    first_seen_at: datetime | None = None
    #: version of the root source read now (stale reads are ignored)
    root_version: int | None = None
