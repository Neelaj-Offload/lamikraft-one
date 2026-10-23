"""Engine data: what collection produces (``Candidate``) and what assembly returns (``Item``)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Category = Literal["obligation", "change", "handled", "reminder", "recommendation"]
Responsibility = Literal["YOUR_DECISION", "ASSIGNED_TO_YOU", "DELEGATED_TO_YOU", "YOU_OWN", "FYI"]


@dataclass(frozen=True)
class Candidate:
    issue_id: uuid.UUID
    category: Category
    kind: str
    family: str
    title: str
    fact_at: datetime
    issue_fingerprint: str
    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    money: tuple[dict[str, str], ...] = ()
    source_refs: tuple[dict[str, Any], ...] = ()
    responsibility: Responsibility = "FYI"
    owner_user_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    due_at: datetime | None = None
    due_kind: str = "none"
    #: the overdue sweep has recorded this obligation as overdue (a real fact, never "now")
    overdue_fact: bool = False
    blocked: bool = False
    blocked_by: tuple[dict[str, Any], ...] = ()
    unblock_expected_today: bool = False
    impact: tuple[str, ...] = ()
    actionable: bool = False
    is_decision: bool = False
    changed_since_last_visit: bool = False
    members: tuple[dict[str, Any], ...] = ()
    task_ids: tuple[uuid.UUID, ...] = ()
    proposal_ref: dict[str, Any] | None = None
    uncertainty_flags: tuple[str, ...] = ()
    #: counting class for the overview sentence (customer_reply, quote_expiry, decision, onboarding_step, task)
    overview_class: str | None = None


@dataclass(frozen=True)
class Context:
    """Everything time-related is fixed by the briefing's work date, never by "now"."""

    work_date: date
    day_type: str
    window_start: datetime
    window_end: datetime
    next_window_start: datetime
    next_window_end: datetime
    horizon_end: datetime
    initial_cap: int = 5


@dataclass(frozen=True)
class Item:
    candidate: Candidate
    section: str
    band: str
    score: int
    reason_codes: tuple[str, ...]
    ordinal: int = 0

    @property
    def issue_id(self) -> uuid.UUID:
        return self.candidate.issue_id


@dataclass(frozen=True)
class Assembly:
    items: tuple[Item, ...]
    sections: tuple[tuple[str, tuple[uuid.UUID, ...]], ...]
    initial_issue_ids: tuple[uuid.UUID, ...]
