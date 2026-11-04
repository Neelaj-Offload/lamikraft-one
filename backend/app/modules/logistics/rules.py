"""Briefing rule family ``ops.dispatch_cutoffs`` (events.md §4) through the ``tasks.rules`` consumer.

One issue per shipment, keyed ``shipment:{id}:dispatch``:
- while the shipment is planned or booked and has a cutoff, a **dispatch** task for operations (the branch's
  operations queue unless someone is named), **hard-due at the cutoff** (an instant entered in company time);
- while the shipment is in exception, a **resolve exception** task, soft-due at the end of today's shift.
Done when the shipment is dispatched (or delivered); cancelled shipments cancel the obligation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from app.modules.tasks import completion, responsibility
from app.modules.tasks.models import DueKind, IssueResolution, MemberRole, TaskState
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

SHIPMENT = "logistics.shipment"
READ = "logistics.shipment.read"
FAMILY = "ops.dispatch_cutoffs"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def derive_shipment(uow: UnitOfWork, shipment_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    s = cache.read(uow, SHIPMENT, shipment_id)
    if s is None:
        return None
    key = f"shipment:{shipment_id}:dispatch"
    f = s.facts
    tasks: list[TaskSpec] = []
    named = responsibility.resolve(uow, FAMILY, [])
    if s.status in ("planned", "booked") and s.deadlines.get("cutoff_at"):
        cutoff: datetime = s.deadlines["cutoff_at"]
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:dispatch:{cutoff.isoformat()}",
                kind="dispatch_by_cutoff",
                title=f"Dispatch {f['shipment_number']} to {f['party_name']} by {f['cutoff_local']}",
                completion_check="shipment_dispatched",
                required_permission=READ,
                facts=dict(f),
                primary_ref_type=SHIPMENT,
                primary_ref_id=s.source_id,
                primary_ref_version=s.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.HARD.value,
                due_at=cutoff,
                scope_owner_id=s.owner_user_id,
                scope_branch_id=s.branch_id,
                branch_id=s.branch_id,
            )
        )
    if s.status == "exception":
        cal = responsibility.company_calendar(uow)
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:exception:{f.get('exception_code')}",
                kind="resolve_shipment_exception",
                title=f"Resolve the {f.get('exception_code', 'shipment')} exception on {f['shipment_number']}",
                completion_check="shipment_exception_resolved",
                required_permission=READ,
                facts=dict(f),
                primary_ref_type=SHIPMENT,
                primary_ref_id=s.source_id,
                primary_ref_version=s.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value,
                due_at=cal.end_of_day_due(cal.work_date(uow.now())),
                scope_owner_id=s.owner_user_id,
                scope_branch_id=s.branch_id,
                branch_id=s.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family=FAMILY,
        root_ref_type=SHIPMENT,
        root_ref_id=s.source_id,
        title=s.label,
        title_facts={"shipment_number": f["shipment_number"], "party_name": f["party_name"]},
        required_permission=READ,
        scope_owner_id=s.owner_user_id,
        scope_branch_id=s.branch_id,
        members=[
            MemberSpec(
                key=key,
                ref_type=SHIPMENT,
                ref_id=s.source_id,
                ref_version=s.version,
                label=s.label,
                facts=dict(f),
                required_permission=READ,
                role=MemberRole.ROOT.value,
                scope_owner_id=s.owner_user_id,
                scope_branch_id=s.branch_id,
            )
        ],
        tasks=tasks,
        closure=Closure(
            TaskState.CANCELLED.value if s.status == "cancelled" else TaskState.DONE.value,
            {"reason": f"shipment_{s.status}"},
        ),
        resolution=IssueResolution.COMPLETED.value,
        root_version=s.version,
    )


def on_shipment(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    sid = _uuid((event.payload or {}).get("shipment_id")) or event.aggregate_id
    if sid is not None:
        yield derive_shipment(uow, sid, cache=cache)


def _check_dispatched(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    s = sources.read(uow, SHIPMENT, task.primary_ref_id)
    if s is None or s.status not in ("planned", "booked"):
        return completion.CompletionResult(True, evidence={"shipment": s.status if s else "gone"})
    return completion.CompletionResult(False, remaining=["not_dispatched"])


def _check_exception(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    s = sources.read(uow, SHIPMENT, task.primary_ref_id)
    if s is None or s.status != "exception":
        return completion.CompletionResult(True, evidence={"shipment": s.status if s else "gone"})
    return completion.CompletionResult(False, remaining=["exception_open"])


def register_checks() -> None:
    completion.register("shipment_dispatched")(_check_dispatched)
    completion.register("shipment_exception_resolved")(_check_exception)
    completion.CHECK_SOURCES.setdefault("shipment_dispatched", SHIPMENT)
    completion.CHECK_SOURCES.setdefault("shipment_exception_resolved", SHIPMENT)
