"""The ``ops.production_dependencies`` briefing family (events.md §4), fed through the ``tasks.rules`` consumer:

- a **blocked work order** is one issue keyed ``wo:{id}:blocked`` with the work order as root and every ``caused_by``
  shortage as an evidence member (root-cause grouping with ``ops.shortages``: the same shortage id), and a task for
  the work order's owner (else the operations queue) to clear the dependency; it closes when the work order is
  unblocked, completed or cancelled (``work_order_unblocked``);
- an **overloaded work-centre day** (``production.capacity.overloaded``) is an issue keyed ``capacity:{wc}:{date}``
  with a rescheduling task for the operations queue, closed when the day is no longer overloaded;
- an **incomplete cost rollup** (``production.cost_rollup.computed`` with status incomplete) is an informational issue
  for production naming how many inputs are missing (never a figure).
Rules re-read sources through the readers; events are triggers only, so replays change nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from app.modules.tasks import completion, responsibility
from app.modules.tasks.models import DueKind, IssueResolution, MemberRole, TaskState
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

FAMILY = "ops.production_dependencies"
WORK_ORDER = "production.work_order"
OVERLOAD = "production.capacity_overload"
SHORTAGE = "inventory.shortage"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def derive_work_order(uow: UnitOfWork, work_order_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    w = cache.read(uow, WORK_ORDER, work_order_id)
    if w is None:
        return None
    key = f"wo:{w.source_id}:blocked"
    number = w.facts["wo_number"]
    members = [MemberSpec(key=f"wo:{w.source_id}", ref_type=WORK_ORDER, ref_id=w.source_id, ref_version=w.version,
                          label=w.label, facts={"wo_number": number, "status": w.status},
                          required_permission="production.work_order.read", role=MemberRole.ROOT.value,
                          scope_owner_id=w.owner_user_id, scope_branch_id=w.branch_id)]
    for cause in w.facts.get("caused_by") or []:
        if cause.get("type") != SHORTAGE:
            continue
        s = cache.read(uow, SHORTAGE, uuid.UUID(cause["id"]))
        if s is None:
            continue
        members.append(MemberSpec(key=f"cause:{SHORTAGE}:{s.source_id}", ref_type=SHORTAGE, ref_id=s.source_id,
                                  ref_version=s.version, label=s.label, facts={"product_key": s.facts.get("product_key")},
                                  required_permission="inventory.stock.read", role=MemberRole.EVIDENCE.value,
                                  scope_branch_id=s.branch_id))
    tasks: list[TaskSpec] = []
    if not w.is_closed:
        named = responsibility.resolve(uow, FAMILY, [w.owner_user_id])
        tasks.append(TaskSpec(
            dedup_key=f"{key}:clear", kind="clear_production_dependency",
            title=f"{number} is waiting for material", completion_check="work_order_unblocked",
            required_permission="production.work_order.read", facts={"wo_number": number},
            primary_ref_type=WORK_ORDER, primary_ref_id=w.source_id, primary_ref_version=w.version,
            owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
            due_kind=DueKind.NONE.value, scope_owner_id=w.owner_user_id, scope_branch_id=w.branch_id,
            branch_id=w.branch_id))
    return IssueOutcome(
        issue_key=key, family=FAMILY, root_ref_type=WORK_ORDER, root_ref_id=w.source_id,
        title=f"{number} is blocked by a material shortage", title_facts={"wo_number": number},
        required_permission="production.work_order.read", scope_owner_id=w.owner_user_id, scope_branch_id=w.branch_id,
        members=members, tasks=tasks, closure=Closure(TaskState.DONE.value, {"reason": "work_order_unblocked"}),
        resolution=IssueResolution.COMPLETED.value, root_version=w.version,
    )


def on_work_order(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    wid = _uuid((event.payload or {}).get("work_order_id")) or event.aggregate_id
    if wid is not None:
        yield derive_work_order(uow, wid, cache=cache)


def derive_overload(uow: UnitOfWork, overload_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    o = cache.read(uow, OVERLOAD, overload_id)
    if o is None:
        return None
    from app.modules.production.models import CapacityOverload

    row = uow.session.get(CapacityOverload, overload_id)
    assert row is not None
    key = f"capacity:{row.work_center_id}:{row.load_date.isoformat()}"
    tasks: list[TaskSpec] = []
    if not o.is_closed:
        named = responsibility.resolve(uow, FAMILY, [])
        tasks.append(TaskSpec(
            dedup_key=f"{key}:reschedule", kind="reschedule_capacity", title=f"Reschedule: {o.label}",
            completion_check="capacity_not_overloaded", required_permission="production.capacity.read",
            facts=dict(o.facts), primary_ref_type=OVERLOAD, primary_ref_id=o.source_id, primary_ref_version=o.version,
            owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
            due_kind=DueKind.NONE.value))
    return IssueOutcome(
        issue_key=key, family=FAMILY, root_ref_type=OVERLOAD, root_ref_id=o.source_id, title=o.label,
        title_facts=dict(o.facts), required_permission="production.capacity.read",
        members=[MemberSpec(key=f"overload:{o.source_id}", ref_type=OVERLOAD, ref_id=o.source_id, ref_version=o.version,
                            label=o.label, facts=dict(o.facts), required_permission="production.capacity.read",
                            role=MemberRole.ROOT.value)],
        tasks=tasks, closure=Closure(TaskState.DONE.value, {"reason": "capacity_not_overloaded"}),
        resolution=IssueResolution.COMPLETED.value, root_version=o.version,
    )


def on_overload(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    if event.aggregate_id is not None:
        yield derive_overload(uow, event.aggregate_id, cache=cache)


def on_rollup(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    payload = event.payload or {}
    rid, pid = _uuid(payload.get("rollup_id")), _uuid(payload.get("product_id"))
    if rid is None or pid is None or payload.get("status") != "incomplete":
        return
    from app.modules.production.common import product_refs
    from app.modules.production.models import CostRollup

    row = uow.session.get(CostRollup, rid)
    if row is None:
        return
    p = product_refs(uow, [pid]).get(pid)
    label = p.product_key if p else str(pid)
    yield IssueOutcome(
        issue_key=f"cost_rollup:{pid}:incomplete", family=FAMILY, root_ref_type="catalogue.product", root_ref_id=pid,
        title=f"Cost rollup of {label} is incomplete", title_facts={"product_key": label, "missing": len(row.missing_inputs)},
        required_permission="production.cost_rollup.run", info=True, resolution=None,
    )


# ---- completion checks ------------------------------------------------------------------------------------------------
def _check_unblocked(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    w = sources.read(uow, WORK_ORDER, task.primary_ref_id)
    if w is None or w.is_closed:
        return completion.CompletionResult(True, evidence={"work_order": w.status if w else "gone"})
    return completion.CompletionResult(False, remaining=["work_order_blocked"])


def _check_overload(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    o = sources.read(uow, OVERLOAD, task.primary_ref_id)
    if o is None or o.is_closed:
        return completion.CompletionResult(True, evidence={"capacity": "within_capacity"})
    return completion.CompletionResult(False, remaining=["still_overloaded"])


def register_checks() -> None:
    completion.register("work_order_unblocked")(_check_unblocked)
    completion.register("capacity_not_overloaded")(_check_overload)
    completion.CHECK_SOURCES.setdefault("work_order_unblocked", WORK_ORDER)
    completion.CHECK_SOURCES.setdefault("capacity_not_overloaded", OVERLOAD)
