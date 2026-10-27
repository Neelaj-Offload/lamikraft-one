"""Snooze never erases an obligation: bounded by deadlines (briefing design §9)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.modules.tasks.schemas import TaskInfo
from app.modules.tasks.service import (
    MAX_SNOOZE_NO_DEADLINE,
    MAX_SNOOZE_OVERDUE,
    SNOOZE_DEADLINE_LEAD,
    max_snooze_until,
)

NOW = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)


def _task(**changes: object) -> TaskInfo:
    base = TaskInfo(
        id=uuid.uuid7(), issue_id=uuid.uuid7(), kind="manual", family="common.manual", title="t", facts={}, state="open",
        due_kind="hard", due_at=NOW + timedelta(hours=5), owner_user_id=None, assignee_user_id=None, initiator_user_id=None,
        queue_code=None, completion_check="assertion", primary_ref_type=None, primary_ref_id=None, primary_ref_version=None,
        required_permission="tasks.task.read", scope_owner_id=None, scope_branch_id=None, overdue_emitted_at=None,
        closed_at=None, closed_by=None, dismissal_reason_code=None, completion_evidence=None, version=1, origin="user",
        created_at=NOW,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_hard_deadline_keeps_a_lead() -> None:
    task = _task()
    assert max_snooze_until([task], NOW) == task.due_at - SNOOZE_DEADLINE_LEAD  # type: ignore[operator]


def test_soft_deadline_is_the_bound() -> None:
    task = _task(due_kind="soft")
    assert max_snooze_until([task], NOW) == task.due_at


def test_overdue_is_capped() -> None:
    assert max_snooze_until([_task(due_at=NOW - timedelta(hours=1))], NOW) == NOW + MAX_SNOOZE_OVERDUE
    swept = _task(due_at=NOW + timedelta(hours=1), overdue_emitted_at=NOW)
    assert max_snooze_until([swept], NOW) == NOW + MAX_SNOOZE_OVERDUE


def test_earliest_obligation_wins_and_no_deadline_has_a_ceiling() -> None:
    early = _task(due_at=NOW + timedelta(hours=2))
    late = _task(due_at=NOW + timedelta(days=2), due_kind="soft")
    assert max_snooze_until([late, early], NOW) == early.due_at - SNOOZE_DEADLINE_LEAD  # type: ignore[operator]
    assert max_snooze_until([_task(due_at=None, due_kind="none")], NOW) == NOW + MAX_SNOOZE_NO_DEADLINE
