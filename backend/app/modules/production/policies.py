"""Production record scope (permissions.md §7.7).

- ``production.bom`` / ``production.routing`` / work centres: company configuration (read by production, operations
  and management; managed by production; approved by production or management, never by the version's author).
- ``production.work_order``: own/team/branch/company on ``owner_user_id`` and ``branch_id`` (the branch of the work
  order's warehouse): production company, operations branch, management company. Materials, operations and stock
  transactions are children authorised only through their work order, so a work order of another branch is a 404
  on every child path. Object rules: ``update`` only while draft; ``transition`` while open; ``post`` (issue,
  consume, return, output, offcut) only while released or in progress.
- Cost rollups have no record scope: readable with ``production.bom.read`` or ``production.cost_rollup.run``; their
  figures are guarded fields (``pricing.cost.read``, never model-exposed).
- Warehouse scope is checked separately with ``inventory.policies.require_warehouse`` on every entry point that
  takes a warehouse (creation) or posts stock (``inventory.stock.post`` over the work order's warehouse).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.production.enums import MasterStatus, WorkOrderStatus
from app.modules.production.models import (
    Bom,
    BomLine,
    CapacityException,
    Routing,
    RoutingOperation,
    WoMaterial,
    WoOperation,
    WorkCenter,
    WorkOrder,
    WoTransaction,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

S = WorkOrderStatus
OPEN = frozenset({S.DRAFT.value, S.RELEASED.value, S.IN_PROGRESS.value, S.COMPLETED.value})
POSTABLE = frozenset({S.RELEASED.value, S.IN_PROGRESS.value})


def master_rules(_ctx: ActorContext, m: Any) -> Mapping[str, Decision]:
    draft = m.status == MasterStatus.DRAFT.value
    return {
        "manage": Decision(draft, None if draft else f"version_{m.status}"),
        "approve": Decision(draft, None if draft else f"version_{m.status}"),
    }


def work_order_rules(_ctx: ActorContext, w: Any) -> Mapping[str, Decision]:
    draft = w.status == S.DRAFT.value
    is_open = w.status in OPEN
    postable = w.status in POSTABLE
    return {
        "update": Decision(draft, None if draft else f"work_order_{w.status}"),
        "transition": Decision(is_open, None if is_open else f"work_order_{w.status}"),
        "post": Decision(postable, None if postable else f"work_order_{w.status}"),
    }


WORK_CENTER_POLICY = ResourcePolicy(
    resource_type="production.work_center",
    model=WorkCenter,
    permission_prefix="production.capacity",
    business_key_column="code",
    label=lambda c: f"{c.code} · {c.name}",
    canonical_path=lambda c: f"/operations/production/work-centres/{c.id}",
    archived_column=None,
)
CAPACITY_EXCEPTION_POLICY = ResourcePolicy(
    resource_type="production.capacity_exception",
    model=CapacityException,
    permission_prefix="production.capacity",
    parent=ParentRef("production.work_center", "work_center_id"),
    archived_column=None,
)
BOM_POLICY = ResourcePolicy(
    resource_type="production.bom",
    model=Bom,
    permission_prefix="production.bom",
    label=lambda b: f"BOM v{b.version_no}",
    canonical_path=lambda b: f"/operations/production/boms/{b.id}",
    rules=master_rules,
    archived_column=None,
)
BOM_LINE_POLICY = ResourcePolicy(
    resource_type="production.bom_line",
    model=BomLine,
    permission_prefix="production.bom",
    parent=ParentRef("production.bom", "bom_id"),
    archived_column=None,
)
ROUTING_POLICY = ResourcePolicy(
    resource_type="production.routing",
    model=Routing,
    permission_prefix="production.routing",
    label=lambda r: f"Routing v{r.version_no}",
    canonical_path=lambda r: f"/operations/production/routings/{r.id}",
    rules=master_rules,
    archived_column=None,
)
ROUTING_OPERATION_POLICY = ResourcePolicy(
    resource_type="production.routing_operation",
    model=RoutingOperation,
    permission_prefix="production.routing",
    parent=ParentRef("production.routing", "routing_id"),
    archived_column=None,
)
WORK_ORDER_POLICY = ResourcePolicy(
    resource_type="production.work_order",
    model=WorkOrder,
    permission_prefix="production.work_order",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="wo_number",
    label=lambda w: w.wo_number,
    canonical_path=lambda w: f"/operations/production/work-orders/{w.id}",
    rules=work_order_rules,
    archived_column=None,
)


def _child(resource_type: str, model: type) -> ResourcePolicy:
    return ResourcePolicy(
        resource_type=resource_type,
        model=model,
        permission_prefix="production.work_order",
        parent=ParentRef("production.work_order", "work_order_id"),
        archived_column=None,
    )


WO_MATERIAL_POLICY = _child("production.wo_material", WoMaterial)
WO_OPERATION_POLICY = _child("production.wo_operation", WoOperation)
WO_TRANSACTION_POLICY = _child("production.wo_transaction", WoTransaction)

POLICIES = [
    WORK_CENTER_POLICY,
    CAPACITY_EXCEPTION_POLICY,
    BOM_POLICY,
    BOM_LINE_POLICY,
    ROUTING_POLICY,
    ROUTING_OPERATION_POLICY,
    WORK_ORDER_POLICY,
    WO_MATERIAL_POLICY,
    WO_OPERATION_POLICY,
    WO_TRANSACTION_POLICY,
]
