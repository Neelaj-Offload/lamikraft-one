"""Briefing rule family ``ops.qc`` (events.md §4) through the ``tasks.rules`` consumer: one issue per inspection,
keyed ``qc:{id}``, with an **inspect** task for operations (the warehouse's branch; the operations queue) soft-due at
the end of today's shift, closed when the inspection is decided. A decided goods-receipt inspection also re-derives
its purchase order's ``ops.receipts`` issue (accepted / rejected quantities change what is outstanding)."""

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

INSPECTION = "quality.inspection"
READ = "quality.inspection.read"
FAMILY = "ops.qc"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def derive_inspection(
    uow: UnitOfWork, inspection_id: uuid.UUID, *, cache: SourceCache
) -> IssueOutcome | None:
    s = cache.read(uow, INSPECTION, inspection_id)
    if s is None:
        return None
    key = f"qc:{inspection_id}"
    f = s.facts
    tasks: list[TaskSpec] = []
    if not s.is_closed:
        cal = responsibility.company_calendar(uow)
        named = responsibility.resolve(uow, FAMILY, [])
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:inspect",
                kind="inspect",
                title=f"Inspect {f['product_key']} from {f['subject_label']}",
                completion_check="inspection_decided",
                required_permission=READ,
                facts=dict(f),
                primary_ref_type=INSPECTION,
                primary_ref_id=s.source_id,
                primary_ref_version=s.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value,
                due_at=cal.end_of_day_due(cal.work_date(uow.now())),
                scope_branch_id=s.branch_id,
                branch_id=s.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family=FAMILY,
        root_ref_type=INSPECTION,
        root_ref_id=s.source_id,
        title=s.label,
        title_facts={"inspection_number": f["inspection_number"], "product_key": f["product_key"]},
        required_permission=READ,
        scope_branch_id=s.branch_id,
        members=[
            MemberSpec(
                key=key,
                ref_type=INSPECTION,
                ref_id=s.source_id,
                ref_version=s.version,
                label=s.label,
                facts=dict(f),
                required_permission=READ,
                role=MemberRole.ROOT.value,
                scope_branch_id=s.branch_id,
            )
        ],
        tasks=tasks,
        closure=Closure(TaskState.DONE.value, {"reason": f"inspection_{s.status}"}),
        resolution=IssueResolution.COMPLETED.value,
        root_version=s.version,
    )


def on_inspection(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    payload = event.payload or {}
    iid = _uuid(payload.get("inspection_id")) or event.aggregate_id
    if iid is None:
        return
    yield derive_inspection(uow, iid, cache=cache)
    if (
        payload.get("subject_type") == "procurement.goods_receipt_line"
        and event.event_type != "quality.inspection.requested"
    ):
        from app.modules.procurement.models import GoodsReceipt, GoodsReceiptLine
        from app.modules.procurement.rules import derive_po

        gl = uow.session.get(GoodsReceiptLine, _uuid(payload.get("subject_id")))
        grn = uow.session.get(GoodsReceipt, gl.goods_receipt_id) if gl is not None else None
        if grn is not None:
            yield derive_po(uow, grn.purchase_order_id, cache=cache)


def _check_decided(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    s = sources.read(uow, INSPECTION, task.primary_ref_id)
    if s is None or s.is_closed:
        return completion.CompletionResult(True, evidence={"inspection": s.status if s else "gone"})
    return completion.CompletionResult(False, remaining=["not_inspected"])


def register_checks() -> None:
    completion.register("inspection_decided")(_check_decided)
    completion.CHECK_SOURCES.setdefault("inspection_decided", INSPECTION)
