"""``sales.lead_follow_up``: one open "Follow up with …" task per lead, for its owner, due on the follow-up date.

Triggered by ``parties.activity.logged``, ``parties.lead.stage_changed`` and ``parties.party.archived`` (registered in
``tasks.rules.consumer``). The issue is re-derived from the party's current facts, so replays change nothing. The task's
dedup key carries the date: a new date closes the old task (done) and opens the next one, so exactly one is ever open.
A won, lost or archived lead, or a cleared date, closes it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

from app.modules.tasks import responsibility
from app.modules.tasks.models import DueKind, IssueResolution, MemberRole, TaskState
from app.modules.tasks.rules.families import _closer, _closing_outcome
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

FAMILY = "sales.lead_follow_up"
PARTY = "parties.party"
READ = "parties.party.read"
OPEN_STAGES = ("new", "contacted", "qualified", "negotiating")


def issue_key(party_id: uuid.UUID) -> str:
    return f"lead:{party_id}"


def task_key(party_id: uuid.UUID, due_on: date) -> str:
    return f"lead:{party_id}:follow_up:{due_on.isoformat()}"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def on_lead_event(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    party_id = _uuid((event.payload or {}).get("party_id")) or event.aggregate_id
    if party_id is not None:
        yield derive_follow_up(uow, party_id, event=event, cache=cache)


def derive_follow_up(
    uow: UnitOfWork, party_id: uuid.UUID, *, event: DomainEvent | None = None, cache: SourceCache | None = None
) -> IssueOutcome | None:
    cache = cache or SourceCache()
    key = issue_key(party_id)
    p = cache.read(uow, PARTY, party_id)
    if p is None:
        return _closing_outcome(
            uow, key, Closure(TaskState.CANCELLED.value, {"reason": "lead_removed"}), IssueResolution.SOURCE_CLOSED.value
        )
    stage = p.facts.get("lead_stage")
    raw_due = p.facts.get("next_follow_up_on")
    due_on = date.fromisoformat(raw_due) if raw_due else None
    name = p.facts.get("display_name") or p.label
    tasks: list[TaskSpec] = []
    if stage in OPEN_STAGES and due_on is not None and not p.is_closed:
        named = responsibility.resolve(uow, FAMILY, [p.owner_user_id])
        cal = responsibility.company_calendar(uow)
        tasks.append(
            TaskSpec(
                dedup_key=task_key(party_id, due_on),
                kind="lead_follow_up",
                title=f"Follow up with {name}",
                completion_check="lead_followed_up",
                required_permission=READ,
                facts={"party_name": name, "party_number": p.facts.get("party_number"), "due_on": due_on.isoformat(),
                       "lead_stage": stage},
                primary_ref_type=PARTY,
                primary_ref_id=party_id,
                primary_ref_version=p.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value,
                due_at=cal.shift_bounds(due_on)[1],
                scope_owner_id=p.owner_user_id,
                scope_branch_id=p.branch_id,
                branch_id=p.branch_id,
            )
        )
    reason = "lead_closed" if stage not in OPEN_STAGES or p.is_closed else "followed_up"
    return IssueOutcome(
        issue_key=key,
        family=FAMILY,
        root_ref_type=PARTY,
        root_ref_id=party_id,
        title=f"Follow-ups with {name}",
        title_facts={"party_name": name},
        required_permission=READ,
        scope_owner_id=p.owner_user_id,
        scope_branch_id=p.branch_id,
        members=[
            MemberSpec(
                key=key,
                ref_type=PARTY,
                ref_id=party_id,
                ref_version=p.version,
                label=p.label,
                facts={"lead_stage": stage, "party_name": name},
                required_permission=READ,
                role=MemberRole.ROOT.value,
                scope_owner_id=p.owner_user_id,
                scope_branch_id=p.branch_id,
            )
        ],
        tasks=tasks,
        closure=Closure(
            TaskState.DONE.value if reason == "followed_up" else TaskState.CANCELLED.value,
            {"reason": reason},
            _closer(event),
        ),
        resolution=IssueResolution.COMPLETED.value,
        root_version=p.version,
    )
