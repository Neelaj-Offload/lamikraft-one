"""Briefing API models. Money travels as ``Money`` (DecimalStr strings); identity is never a field."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import Money
from app.modules.tasks.schemas import DismissalReasonCode, InboxItem

ItemActionName = Literal["snooze", "unsnooze", "mark_handled", "dismiss", "explain"]


class PersonRef(BaseModel):
    user_id: uuid.UUID
    name: str


class SourceRefView(BaseModel):
    type: str
    id: uuid.UUID
    version: int | None = None
    label: str
    path: str | None = None


class RecommendationView(BaseModel):
    id: uuid.UUID | None = None
    action_code: str
    label: str
    reason_code: str
    reason: str
    effect_code: str
    effect: str
    alternatives: list[str]


class ActionView(BaseModel):
    action: str
    via: str = "briefings"
    path: str | None = None
    requires_reason: bool = False
    max_until: datetime | None = None
    proposal_id: uuid.UUID | None = None
    proposal_version: int | None = None


class ItemStateView(BaseModel):
    acknowledged: bool = False
    snoozed_until: datetime | None = None
    handled: bool = False
    dismissed: bool = False
    task_states: dict[str, str] = Field(default_factory=dict)
    issue_state: str | None = None
    blocked_now: bool | None = None


class ItemView(BaseModel):
    issue_id: uuid.UUID
    ordinal: int
    section: str
    band: str
    score: int
    reason_codes: list[str]
    reasons: list[str]
    kind: str
    family: str
    title: str
    summary: str
    facts: dict[str, Any]
    money: list[Money]
    source_refs: list[SourceRefView]
    fact_at: datetime
    owner: PersonRef | None
    assignee: PersonRef | None
    due_at: datetime | None
    due_local: str | None
    due_label: str | None
    due_kind: str
    overdue: bool
    recommendation: RecommendationView | None
    uncertainty_flags: list[str]
    allowed_actions: list[ActionView]
    proposal_ref: dict[str, Any] | None
    member_count: int
    members: list[dict[str, Any]]
    fingerprint: str
    change_kind: str
    changed_since_last_visit: bool
    is_reminder: bool
    blocked: bool
    blocked_by: list[dict[str, Any]]
    state: ItemStateView


class SectionView(BaseModel):
    code: str
    title: str
    total: int
    issue_ids: list[uuid.UUID]


class OverviewView(BaseModel):
    greeting: str
    sentence: str
    text_source: Literal["template"] = "template"
    template_code: str
    #: counts, plus booleans such as ``rest_moving`` (fixtures 9.2)
    facts: dict[str, bool | int]


class AckView(BaseModel):
    briefing_id: uuid.UUID
    version: int
    method: str
    channel: str
    acknowledged_at: datetime
    accepted: bool = True


class PinView(BaseModel):
    id: uuid.UUID
    briefing_id: uuid.UUID
    kind: str
    pinned_version: int
    state: str
    position: int
    ordinal_map: list[dict[str, Any]]
    expires_at: datetime
    pending_updates: int = 0
    #: row version for ``PinUpdate.expected_version``
    version: int = 1


class LastSuccessfulView(BaseModel):
    briefing_id: uuid.UUID
    work_date: date
    version: int
    generated_at: datetime
    data_as_of: datetime
    overview: OverviewView | None
    items: list[ItemView]


class FallbackView(BaseModel):
    error_code: str
    failed_at: datetime
    tasks: list[InboxItem]
    last_successful: LastSuccessfulView | None


class BriefingView(BaseModel):
    briefing_id: uuid.UUID | None
    work_date: date
    day_type: str
    time_zone: str
    status: Literal["ready", "fallback"]
    fallback: bool
    ai_status: Literal["not_used"] = "not_used"
    version: int | None
    latest_version: int | None
    generated_at: datetime | None
    data_as_of: datetime | None
    trigger: str | None
    first_opened_at: datetime | None
    overview: OverviewView | None
    sections: list[SectionView]
    items: list[ItemView]
    initial_view: list[uuid.UUID]
    snoozed: list[ItemView]
    updates_available: int
    up_to_date: bool
    last_ack: AckView | None
    pin: PinView | None
    fallback_detail: FallbackView | None = None


class AcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    method: Literal["viewed", "explicit", "voice", "whatsapp"] = "explicit"
    channel_message_id: str | None = Field(default=None, max_length=120)


class ItemActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ItemActionName
    until: datetime | None = None
    reason_code: DismissalReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)
    briefing_version: int | None = None
    item_fingerprint: str | None = Field(default=None, max_length=64)


class ExplainView(BaseModel):
    issue_id: uuid.UUID
    band: str
    score: int
    rule_version: str
    reasons: list[dict[str, Any]]
    recommendation: RecommendationView | None
    sources: list[SourceRefView]
    text: str


class ItemActionResult(BaseModel):
    action: str
    issue_id: uuid.UUID
    outcome: str
    snoozed_until: datetime | None = None
    max_until: datetime | None = None
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    explanation: ExplainView | None = None


class DeltaChange(BaseModel):
    fact_at: datetime
    change_code: str
    actor: PersonRef | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    source: SourceRefView | None
    event_type: str


class DeltaGroup(BaseModel):
    issue_id: uuid.UUID
    title: str
    family: str
    changes: list[DeltaChange]


class DeltaView(BaseModel):
    since: str
    since_instant: datetime
    until_instant: datetime
    groups: list[DeltaGroup]
    limit: int = 100
    #: keyset cursor for the next page of change rows (None on the last page)
    next_cursor: str | None = None


class PinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["voice", "chat"] = "voice"
    detail: Literal["initial", "full"] = "initial"


class PinUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: the pin version the client acted on (409 on mismatch). Optional: ordinal resolution keeps the pin
    #: alive and so bumps its version between a voice client's reads.
    expected_version: int | None = Field(default=None, ge=1)
    state: Literal["active", "paused", "stopped", "completed"] | None = None
    position: int | None = Field(default=None, ge=0)


class PinResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int = Field(ge=1)


class PinResolution(BaseModel):
    ordinal: int
    issue_id: uuid.UUID
    resolved_since: bool
    item: ItemView | None
