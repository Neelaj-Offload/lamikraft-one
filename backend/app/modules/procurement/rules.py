"""Briefing rule family ``ops.receipts`` (events.md §4), fed through the ``tasks.rules`` consumer.

One issue per open purchase order, keyed ``po:{id}:receipts``:
- a **receive** task for operations (the receiving warehouse's branch; the operations queue unless someone is named),
  soft-due at the end of the shift on the next expected date (company calendar), done when nothing is outstanding;
- when lines are late, a **chase** task for the buyer (the PO owner), hard-due today, keyed by the earliest late date
  so moving the date and becoming late again opens a new obligation. This is the "PO overdue" briefing item; its
  evidence member carries the late lines (root cause ``po_line:{id}:late`` for the shortage grouping).
The rule re-reads the PO through the ``procurement.purchase_order`` reader: events are only triggers.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

from app.modules.tasks import completion, responsibility
from app.modules.tasks.models import DueKind, IssueResolution, MemberRole, TaskState
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

PO = "procurement.purchase_order"
READ = "procurement.purchase_order.read"
FAMILY = "ops.receipts"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def issue_key(po_id: uuid.UUID) -> str:
    return f"po:{po_id}:receipts"


def derive_po(uow: UnitOfWork, po_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    p = cache.read(uow, PO, po_id)
    if p is None:
        return None
    key = issue_key(po_id)
    f = p.facts
    cal = responsibility.company_calendar(uow)
    tasks: list[TaskSpec] = []
    if not p.is_closed and f.get("next_expected_date"):
        due_day = date.fromisoformat(f["next_expected_date"])
        named = responsibility.resolve(uow, FAMILY, [])
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:receive",
                kind="receive_goods",
                title=f"Receive {f['po_number']} from {f['vendor_name']}",
                completion_check="po_received",
                required_permission=READ,
                facts=dict(f),
                primary_ref_type=PO,
                primary_ref_id=p.source_id,
                primary_ref_version=p.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value,
                due_at=cal.end_of_day_due(due_day),
                scope_branch_id=p.branch_id,
                branch_id=p.branch_id,
            )
        )
        if f.get("late_line_count"):
            buyer = responsibility.resolve(uow, FAMILY, [p.owner_user_id])
            lines = ", ".join(str(n) for n in f["late_line_nos"])
            tasks.append(
                TaskSpec(
                    dedup_key=f"{key}:chase:{f['earliest_late_date']}",
                    kind="chase_vendor",
                    title=f"Chase {f['vendor_name']}: {f['po_number']} line {lines} is overdue",
                    completion_check="po_on_time",
                    required_permission=READ,
                    facts=dict(f),
                    primary_ref_type=PO,
                    primary_ref_id=p.source_id,
                    primary_ref_version=p.version,
                    owner_user_id=buyer.owner_user_id,
                    assignee_user_id=buyer.assignee_user_id,
                    queue_code=buyer.queue_code,
                    due_kind=DueKind.HARD.value,
                    due_at=cal.end_of_day_due(cal.work_date(uow.now())),
                    scope_owner_id=p.owner_user_id,
                    scope_branch_id=p.branch_id,
                    branch_id=p.branch_id,
                )
            )
    members = [
        MemberSpec(
            key=key,
            ref_type=PO,
            ref_id=p.source_id,
            ref_version=p.version,
            label=p.label,
            facts=dict(f),
            required_permission=READ,
            role=MemberRole.ROOT.value,
            scope_owner_id=p.owner_user_id,
            scope_branch_id=p.branch_id,
        )
    ]
    for line_id in f.get("late_line_ids") or []:
        members.append(
            MemberSpec(
                key=f"po_line:{line_id}:late",
                ref_type=PO,
                ref_id=p.source_id,
                ref_version=p.version,
                label=f"{f['po_number']} late line",
                facts={"po_line_id": line_id, "cause": "late_supply"},
                required_permission=READ,
                role=MemberRole.EVIDENCE.value,
                scope_owner_id=p.owner_user_id,
                scope_branch_id=p.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family=FAMILY,
        root_ref_type=PO,
        root_ref_id=p.source_id,
        title=f"{f['po_number']} from {f['vendor_name']}",
        title_facts={"po_number": f["po_number"], "vendor_name": f["vendor_name"]},
        required_permission=READ,
        scope_owner_id=p.owner_user_id,
        scope_branch_id=p.branch_id,
        members=members,
        tasks=tasks,
        closure=Closure(
            TaskState.CANCELLED.value if p.status == "cancelled" else TaskState.DONE.value,
            {"reason": f"po_{p.status}"},
        ),
        resolution=IssueResolution.COMPLETED.value,
        root_version=p.version,
    )


def on_po_event(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    po_id = _uuid((event.payload or {}).get("purchase_order_id"))
    if po_id is not None:
        yield derive_po(uow, po_id, cache=cache)


def _check_received(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    p = sources.read(uow, PO, task.primary_ref_id)
    if p is None or p.is_closed:
        return completion.CompletionResult(True, evidence={"purchase_order": p.status if p else "gone"})
    return completion.CompletionResult(False, remaining=["goods_outstanding"])


def _check_on_time(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    p = sources.read(uow, PO, task.primary_ref_id)
    if p is None or p.is_closed or not p.facts.get("late_line_count"):
        return completion.CompletionResult(True, evidence={"late_lines": 0})
    return completion.CompletionResult(False, remaining=["lines_late"])


def register_checks() -> None:
    completion.register("po_received")(_check_received)
    completion.register("po_on_time")(_check_on_time)
    completion.CHECK_SOURCES.setdefault("po_received", PO)
    completion.CHECK_SOURCES.setdefault("po_on_time", PO)
