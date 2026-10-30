"""Tasks DTOs: API request/response models and the read views other modules (briefings) consume."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.http.capabilities import Capability
from app.modules.tasks.models import DismissalReason


def non_blank(value: str) -> str:
    """Free text is stored stripped and must keep at least one visible character (422 otherwise)."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("must contain a non-space character")
    return stripped


NonBlankStr = Annotated[str, AfterValidator(non_blank)]

InboxTab = Literal["tasks", "approvals", "conversations", "exceptions"]
InboxScope = Literal["mine", "team", "branch", "company"]
TaskAction = Literal["complete", "dismiss", "start"]
DismissalReasonCode = Literal[
    "handled_outside_system", "not_applicable", "duplicate", "customer_withdrew", "no_action_needed"
]
assert set(DismissalReasonCode.__args__) == {r.value for r in DismissalReason}  # type: ignore[attr-defined]

APPROVAL_KINDS = frozenset({"approval_decision"})
CONVERSATION_KINDS = frozenset({"reply_needed", "enquiry_reply"})
UNDISMISSABLE_KINDS = frozenset({"approval_decision"})


# ---- read views (plain data; no ORM objects cross the module boundary) --------------------------------
@dataclass(frozen=True)
class MemberInfo:
    key: str
    role: str
    ref_type: str
    ref_id: uuid.UUID
    ref_version: int | None
    label: str
    facts: dict[str, Any]
    required_permission: str
    scope_owner_id: uuid.UUID | None
    scope_branch_id: uuid.UUID | None


@dataclass(frozen=True)
class IssueInfo:
    id: uuid.UUID
    issue_key: str
    occurrence: int
    family: str
    state: str
    root_ref_type: str
    root_ref_id: uuid.UUID
    title: str
    title_facts: dict[str, Any]
    fingerprint: str
    required_permission: str
    scope_owner_id: uuid.UUID | None
    scope_branch_id: uuid.UUID | None
    sensitivity: str
    first_seen_at: datetime
    last_changed_at: datetime
    last_event_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution: str | None
    members: tuple[MemberInfo, ...] = ()


@dataclass(frozen=True)
class TaskInfo:
    id: uuid.UUID
    issue_id: uuid.UUID
    kind: str
    family: str
    title: str
    facts: dict[str, Any]
    state: str
    due_kind: str
    due_at: datetime | None
    owner_user_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    initiator_user_id: uuid.UUID | None
    queue_code: str | None
    completion_check: str
    primary_ref_type: str | None
    primary_ref_id: uuid.UUID | None
    primary_ref_version: int | None
    required_permission: str
    scope_owner_id: uuid.UUID | None
    scope_branch_id: uuid.UUID | None
    overdue_emitted_at: datetime | None
    closed_at: datetime | None
    closed_by: uuid.UUID | None
    dismissal_reason_code: str | None
    completion_evidence: dict[str, Any] | None
    version: int
    origin: str
    created_at: datetime
    candidates: tuple[uuid.UUID, ...] = ()
    #: open issues this task waits for
    blocked_by: tuple[uuid.UUID, ...] = ()

    @property
    def is_open(self) -> bool:
        return self.state in ("open", "in_progress")


@dataclass(frozen=True)
class ChangeInfo:
    id: uuid.UUID
    issue_id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    fact_at: datetime
    ref_type: str
    ref_id: uuid.UUID
    ref_version: int | None
    change_code: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    actor_user_id: uuid.UUID | None


@dataclass(frozen=True)
class ReminderInfo:
    id: uuid.UUID
    user_id: uuid.UUID
    text: str
    remind_at: datetime
    time_zone: str
    linked_ref_type: str | None
    linked_ref_id: uuid.UUID | None
    state: str
    version: int
    created_at: datetime


@dataclass(frozen=True)
class SnoozeInfo:
    issue_id: uuid.UUID
    snoozed_until: datetime
    set_at: datetime
    channel: str


@dataclass(frozen=True)
class HandledResult:
    issue_id: uuid.UUID
    outcome: Literal["completed", "dismissed"]
    task_ids: tuple[uuid.UUID, ...]
    evidence: dict[str, Any] = field(default_factory=dict)


# ---- API models --------------------------------------------------------------------------------------
class AllowedTransition(BaseModel):
    action: str
    to_status: str
    requires_reason: bool = False


class SourceRef(BaseModel):
    type: str
    id: uuid.UUID
    version: int | None = None
    label: str
    path: str | None = None


class InboxItem(BaseModel):
    id: uuid.UUID
    issue_id: uuid.UUID
    kind: str
    family: str
    tab: InboxTab
    title: str
    state: str
    due_at: datetime | None
    due_kind: str
    overdue: bool
    blocked: bool
    owner_user_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    queue_code: str | None
    snoozed_until: datetime | None
    source_refs: list[SourceRef]
    capabilities: dict[str, Capability]
    version: int


class InboxPage(BaseModel):
    items: list[InboxItem]
    next_cursor: str | None
    limit: int


class InboxCounts(BaseModel):
    tasks: int
    approvals: int
    conversations: int
    exceptions: int


class TaskDetail(InboxItem):
    facts: dict[str, Any]
    completion_check: str
    completion_evidence: dict[str, Any] | None
    dismissal_reason_code: str | None
    closed_at: datetime | None
    created_at: datetime
    allowed_transitions: list[AllowedTransition]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonBlankStr = Field(min_length=1, max_length=300)
    assignee_user_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    due_kind: Literal["hard", "soft"] = "hard"
    linked_ref_type: str | None = Field(default=None, max_length=80)
    linked_ref_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class TaskTransition(BaseModel):
    """``expected_version`` is the task version the client acted on (api-conventions §6: 409 on mismatch)."""

    model_config = ConfigDict(extra="forbid")

    action: TaskAction
    expected_version: int = Field(ge=1)
    reason_code: DismissalReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)


class TaskAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: uuid.UUID
    expected_version: int = Field(ge=1)


class SnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: datetime


class SnoozeOut(BaseModel):
    issue_id: uuid.UUID
    snoozed_until: datetime | None
    max_until: datetime | None


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: NonBlankStr = Field(min_length=1, max_length=280)
    remind_at: datetime
    linked_ref_type: str | None = Field(default=None, max_length=80)
    linked_ref_id: uuid.UUID | None = None


class ReminderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    text: NonBlankStr | None = Field(default=None, min_length=1, max_length=280)
    remind_at: datetime | None = None
    state: Literal["pending", "done", "cancelled"] | None = None


class ReminderOut(BaseModel):
    id: uuid.UUID
    text: str
    remind_at: datetime
    time_zone: str
    linked_ref_type: str | None
    linked_ref_id: uuid.UUID | None
    state: str
    version: int
    created_at: datetime


class ReminderList(BaseModel):
    """Offset page of the caller's reminders (api-conventions §9: ``Page{items, total, limit, offset}``)."""

    items: list[ReminderOut]
    total: int
    limit: int
    offset: int
