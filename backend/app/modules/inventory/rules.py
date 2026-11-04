"""Slice-4 briefing rule families fed through the ``tasks.rules`` consumer (events.md §4):

- ``ops.shortages``: one issue per (product, warehouse) shortage, keyed ``shortage:{product}:{warehouse}``, grouping
  every cause from ``caused_by`` as members (root-cause grouping: the briefing shows one item per short product with
  the demands behind it). A task for operations (the warehouse's branch) until the shortage resolves.
- ``ops.picking``: a picking task per released pick list for its assignee (else the operations queue), closed when
  the list is picked or cancelled.
- ``admin.stock_integrity``: a projection mismatch found by the nightly check becomes an issue for the admin queue.

Rules re-read the sources through the readers (``inventory.shortage``, ``inventory.pick_list``,
``inventory.warehouse``); events are only triggers, so replays and out-of-order deliveries change nothing.
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

SHORTAGE = "inventory.shortage"
PICK_LIST = "inventory.pick_list"
WAREHOUSE = "inventory.warehouse"
READ = "inventory.stock.read"


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# ---- ops.shortages ----------------------------------------------------------------------------------------------
def shortage_key(product_id: uuid.UUID, warehouse_id: uuid.UUID) -> str:
    return f"shortage:{product_id}:{warehouse_id}"


def derive_shortage(uow: UnitOfWork, shortage_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    s = cache.read(uow, SHORTAGE, shortage_id)
    if s is None:
        return None
    from app.modules.inventory.models import ShortageState

    row = uow.session.get(ShortageState, shortage_id)
    assert row is not None
    key = shortage_key(row.product_id, row.warehouse_id)
    title = f"Short of {s.facts['product_key']} at {s.facts['warehouse_code']}"
    members = [
        MemberSpec(
            key=f"shortage:{s.source_id}",
            ref_type=SHORTAGE,
            ref_id=s.source_id,
            ref_version=s.version,
            label=s.label,
            facts=dict(s.facts),
            required_permission=READ,
            role=MemberRole.ROOT.value,
            scope_branch_id=s.branch_id,
        )
    ]
    for cause in s.facts.get("caused_by") or []:
        if cause["type"] == "orders.sales_order_line":
            from app.modules.orders.models import SalesOrderLine

            line = uow.session.get(SalesOrderLine, uuid.UUID(cause["id"]))
            if line is None:
                continue
            order = cache.read(uow, "orders.sales_order", line.order_id)
            if order is None:
                continue
            members.append(
                MemberSpec(
                    key=f"cause:{cause['type']}:{cause['id']}",
                    ref_type="orders.sales_order",
                    ref_id=order.source_id,
                    ref_version=order.version,
                    label=cause.get("label") or order.label,
                    facts={"order_number": order.facts.get("order_number"), "cause": cause["type"]},
                    required_permission="orders.sales_order.read",
                    role=MemberRole.EVIDENCE.value,
                    scope_owner_id=order.owner_user_id,
                    scope_branch_id=order.branch_id,
                )
            )
        elif cause["type"] == "production.wo_material":
            # the work order whose material is short (Slice-4 merge, production request 5)
            from app.modules.production.models import WoMaterial

            material = uow.session.get(WoMaterial, uuid.UUID(cause["id"]))
            if material is None:
                continue
            wo = cache.read(uow, "production.work_order", material.work_order_id)
            if wo is None:
                continue
            members.append(
                MemberSpec(
                    key=f"cause:{cause['type']}:{cause['id']}",
                    ref_type="production.work_order",
                    ref_id=wo.source_id,
                    ref_version=wo.version,
                    label=cause.get("label") or wo.label,
                    facts={"wo_number": wo.facts.get("wo_number"), "cause": cause["type"]},
                    required_permission="production.work_order.read",
                    role=MemberRole.EVIDENCE.value,
                    scope_owner_id=wo.owner_user_id,
                    scope_branch_id=wo.branch_id,
                )
            )
    tasks: list[TaskSpec] = []
    if not s.is_closed:
        named = responsibility.resolve(uow, "ops.shortages", [])
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:resolve",
                kind="resolve_shortage",
                title=f"Resolve the shortage of {s.facts['product_key']} at {s.facts['warehouse_code']}",
                completion_check="shortage_resolved",
                required_permission=READ,
                facts=dict(s.facts),
                primary_ref_type=SHORTAGE,
                primary_ref_id=s.source_id,
                primary_ref_version=s.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.NONE.value,
                scope_branch_id=s.branch_id,
                branch_id=s.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family="ops.shortages",
        root_ref_type=SHORTAGE,
        root_ref_id=s.source_id,
        title=title,
        title_facts={"product_key": s.facts["product_key"], "warehouse_code": s.facts["warehouse_code"]},
        required_permission=READ,
        scope_branch_id=s.branch_id,
        members=members,
        tasks=tasks,
        closure=Closure(TaskState.DONE.value, {"reason": "shortage_resolved"}),
        resolution=IssueResolution.COMPLETED.value,
        root_version=s.version,
    )


def on_shortage(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    sid = _uuid((event.payload or {}).get("shortage_id")) or event.aggregate_id
    if sid is not None:
        yield derive_shortage(uow, sid, cache=cache)


# ---- ops.picking ------------------------------------------------------------------------------------------------
def derive_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    p = cache.read(uow, PICK_LIST, pick_list_id)
    if p is None:
        return None
    key = f"pick_list:{pick_list_id}"
    tasks: list[TaskSpec] = []
    if p.status == "released":
        named = responsibility.resolve(uow, "ops.picking", [p.owner_user_id])
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:pick",
                kind="pick",
                title=f"Pick {p.facts['pick_list_number']} for {p.facts['order_number']}",
                completion_check="pick_list_picked",
                required_permission=READ,
                facts=dict(p.facts),
                primary_ref_type=PICK_LIST,
                primary_ref_id=p.source_id,
                primary_ref_version=p.version,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value,
                due_at=uow.now(),
                scope_owner_id=p.owner_user_id,
                scope_branch_id=p.branch_id,
                branch_id=p.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family="ops.picking",
        root_ref_type=PICK_LIST,
        root_ref_id=p.source_id,
        title=p.label,
        title_facts={
            "pick_list_number": p.facts["pick_list_number"],
            "order_number": p.facts["order_number"],
        },
        required_permission=READ,
        scope_owner_id=p.owner_user_id,
        scope_branch_id=p.branch_id,
        members=[
            MemberSpec(
                key=key,
                ref_type=PICK_LIST,
                ref_id=p.source_id,
                ref_version=p.version,
                label=p.label,
                facts=dict(p.facts),
                required_permission=READ,
                role=MemberRole.ROOT.value,
                scope_owner_id=p.owner_user_id,
                scope_branch_id=p.branch_id,
            )
        ],
        tasks=tasks,
        closure=Closure(
            TaskState.DONE.value if p.status == "picked" else TaskState.CANCELLED.value,
            {"reason": f"pick_list_{p.status}"},
        ),
        resolution=IssueResolution.COMPLETED.value,
        root_version=p.version,
    )


def on_pick_list(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    pid = _uuid((event.payload or {}).get("pick_list_id")) or event.aggregate_id
    if pid is not None:
        yield derive_pick_list(uow, pid, cache=cache)


# ---- admin.stock_integrity --------------------------------------------------------------------------------------
def on_mismatch(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    payload = event.payload or {}
    product_id, warehouse_id = _uuid(payload.get("product_id")), _uuid(payload.get("warehouse_id"))
    if product_id is None:
        return
    from app.modules.inventory.integrity import check

    still = [m for m in check(uow) if m.product_id == product_id and m.warehouse_id == warehouse_id]
    wh = cache.read(uow, WAREHOUSE, warehouse_id) if warehouse_id else None
    key = f"integrity:{product_id}:{warehouse_id}"
    from app.modules.inventory.reads import product_refs

    product = product_refs(uow, [product_id]).get(product_id)
    label = f"{product.product_key if product else product_id} at {wh.facts.get('code') if wh else 'a company location'}"
    tasks = []
    if still:
        named = responsibility.resolve(uow, "admin.stock_integrity", [])
        tasks.append(
            TaskSpec(
                dedup_key=f"{key}:investigate",
                kind="investigate_integrity",
                title=f"Stock projection mismatch: {label}",
                completion_check="assertion",
                required_permission="inventory.warehouse.manage",
                facts={"kinds": sorted({m.kind for m in still})},
                primary_ref_type=WAREHOUSE if wh else None,
                primary_ref_id=warehouse_id if wh else None,
                owner_user_id=named.owner_user_id,
                assignee_user_id=named.assignee_user_id,
                queue_code=named.queue_code,
                due_kind=DueKind.NONE.value,
            )
        )
    yield IssueOutcome(
        issue_key=key,
        family="admin.stock_integrity",
        root_ref_type=WAREHOUSE,
        root_ref_id=warehouse_id or product_id,
        title=f"Stock projection mismatch: {label}",
        required_permission="inventory.warehouse.manage",
        tasks=tasks,
        closure=Closure(TaskState.DONE.value, {"reason": "projection_consistent"}),
        resolution=IssueResolution.COMPLETED.value,
    )


# ---- completion checks ----------------------------------------------------------------------------------------------
def _check_shortage(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    s = sources.read(uow, SHORTAGE, task.primary_ref_id)
    if s is None or s.is_closed:
        return completion.CompletionResult(True, evidence={"shortage": "resolved"})
    return completion.CompletionResult(False, remaining=["shortage_open"])


def _check_pick(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    from app.platform import sources

    p = sources.read(uow, PICK_LIST, task.primary_ref_id)
    if p is not None and p.status in ("picked", "cancelled"):
        return completion.CompletionResult(True, evidence={"pick_list": p.status})
    return completion.CompletionResult(False, remaining=["not_picked"])


def register_checks() -> None:
    completion.register("shortage_resolved")(_check_shortage)
    completion.register("pick_list_picked")(_check_pick)
    completion.CHECK_SOURCES.setdefault("shortage_resolved", SHORTAGE)
    completion.CHECK_SOURCES.setdefault("pick_list_picked", PICK_LIST)
