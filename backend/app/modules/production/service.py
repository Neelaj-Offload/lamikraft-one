"""Production public service: the only entry point for routers, tools, jobs, seeds and other modules.

Reads (``@query``) and commands return read models; restricted fields (work-centre rates, rollup figures) are
redacted for the calling actor by the service decorator and again on the HTTP path (idempotency replays).

Masters: ``list_work_centers`` / ``work_center`` / ``create_work_center`` / ``update_work_center`` /
``set_capacity_exception`` / ``delete_capacity_exception``; ``list_boms`` / ``bom`` / ``create_bom`` / ``update_bom``
/ ``approve_bom`` / ``retire_bom``; the same for routings.
Work orders: ``list_work_orders`` / ``work_order`` / ``create_work_order`` / ``update_work_order`` /
``transition_work_order`` (release, complete, close, cancel) / ``recheck_materials`` / ``issue_materials`` /
``consume_materials`` / ``return_materials`` / ``report_output`` / ``complete_operation`` / ``schedule_operation`` /
``link_cut_plan`` / ``record_offcut``.
Planning: ``capacity`` / ``run_cost_rollup`` / ``cost_rollups`` / ``cost_rollup`` / ``assess_feasibility`` /
``assess_order_line`` / ``simulate`` (read-only).
Extension point: ``register_supply_provider(name, fn)`` (procurement: open purchase-order supply for feasibility).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.core.http.pagination import Page
from app.modules.production import capacity as _capacity
from app.modules.production import costing, feasibility, masters, wip, wo_reads, work_orders
from app.modules.production.common import business_date
from app.modules.production.feasibility import Supply, register_supply_provider
from app.modules.production.schemas import (
    BomCreate,
    BomRead,
    BomUpdate,
    CapacityExceptionIn,
    CapacityRead,
    CostRollupRead,
    CostRollupRequest,
    CutPlanLink,
    FeasibilityRead,
    FeasibilityRequest,
    IssueRequest,
    MasterCommand,
    MasterSummary,
    OffcutRecord,
    OperationComplete,
    OperationSchedule,
    OutputRequest,
    RoutingCreate,
    RoutingRead,
    RoutingUpdate,
    SimulationRead,
    SimulationRequest,
    WipRequest,
    WorkCenterCreate,
    WorkCenterRead,
    WorkCenterSummary,
    WorkCenterUpdate,
    WorkOrderCreate,
    WorkOrderFilters,
    WorkOrderRead,
    WorkOrderSummary,
    WorkOrderTransition,
    WorkOrderUpdate,
)
from app.platform.service import query
from app.platform.uow import UnitOfWork

__all__ = ["Supply", "register_supply_provider"]

READ = work_orders.READ


# ---- work centres -------------------------------------------------------------------------------------------------------
@query(masters.CAPACITY_READ)
def list_work_centers(uow: UnitOfWork, *, include_inactive: bool = False) -> list[WorkCenterSummary]:
    return masters.list_work_centers(uow, include_inactive=include_inactive)


@query(masters.CAPACITY_READ)
def work_center(uow: UnitOfWork, work_center_id: uuid.UUID) -> WorkCenterRead:
    return masters.work_center_read(uow, masters.get_work_center(uow, work_center_id))


@query(None)
def create_work_center(uow: UnitOfWork, data: WorkCenterCreate) -> WorkCenterRead:
    return masters.work_center_read(uow, masters.create_work_center(uow, data))


@query(None)
def update_work_center(uow: UnitOfWork, work_center_id: uuid.UUID, data: WorkCenterUpdate) -> WorkCenterRead:
    return masters.work_center_read(uow, masters.update_work_center(uow, work_center_id, data))


@query(None)
def set_capacity_exception(uow: UnitOfWork, work_center_id: uuid.UUID, data: CapacityExceptionIn) -> WorkCenterRead:
    return masters.work_center_read(uow, masters.upsert_capacity_exception(uow, work_center_id, data))


@query(None)
def delete_capacity_exception(uow: UnitOfWork, work_center_id: uuid.UUID, exception_id: uuid.UUID) -> WorkCenterRead:
    return masters.work_center_read(uow, masters.delete_capacity_exception(uow, work_center_id, exception_id))


# ---- BOMs -------------------------------------------------------------------------------------------------------------------
@query(masters.BOM_READ)
def list_boms(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, status: list[str] | None = None,
              q: str | None = None, limit: int = 50, offset: int = 0) -> Page[MasterSummary]:
    items, total = masters.list_boms(uow, product_id=product_id, status=status, q=q, limit=limit, offset=offset)
    return Page[MasterSummary](items=items, total=total, limit=limit, offset=offset)


@query(masters.BOM_READ)
def bom(uow: UnitOfWork, bom_id: uuid.UUID) -> BomRead:
    return masters.bom_read(uow, masters.get_bom(uow, bom_id))


@query(None)
def create_bom(uow: UnitOfWork, data: BomCreate) -> BomRead:
    return masters.bom_read(uow, masters.create_bom(uow, data))


@query(None)
def update_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: BomUpdate) -> BomRead:
    return masters.bom_read(uow, masters.update_bom(uow, bom_id, data))


@query(None)
def approve_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: MasterCommand) -> BomRead:
    return masters.bom_read(uow, masters.approve_bom(uow, bom_id, data))


@query(None)
def retire_bom(uow: UnitOfWork, bom_id: uuid.UUID, data: MasterCommand) -> BomRead:
    return masters.bom_read(uow, masters.retire_bom(uow, bom_id, data))


# ---- routings ---------------------------------------------------------------------------------------------------------------
@query(masters.ROUTING_READ)
def list_routings(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, status: list[str] | None = None,
                  q: str | None = None, limit: int = 50, offset: int = 0) -> Page[MasterSummary]:
    items, total = masters.list_routings(uow, product_id=product_id, status=status, q=q, limit=limit, offset=offset)
    return Page[MasterSummary](items=items, total=total, limit=limit, offset=offset)


@query(masters.ROUTING_READ)
def routing(uow: UnitOfWork, routing_id: uuid.UUID) -> RoutingRead:
    return masters.routing_read(uow, masters.get_routing(uow, routing_id))


@query(None)
def create_routing(uow: UnitOfWork, data: RoutingCreate) -> RoutingRead:
    return masters.routing_read(uow, masters.create_routing(uow, data))


@query(None)
def update_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: RoutingUpdate) -> RoutingRead:
    return masters.routing_read(uow, masters.update_routing(uow, routing_id, data))


@query(None)
def approve_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: MasterCommand) -> RoutingRead:
    return masters.routing_read(uow, masters.approve_routing(uow, routing_id, data))


@query(None)
def retire_routing(uow: UnitOfWork, routing_id: uuid.UUID, data: MasterCommand) -> RoutingRead:
    return masters.routing_read(uow, masters.retire_routing(uow, routing_id, data))


# ---- work orders ----------------------------------------------------------------------------------------------------------
@query(READ)
def list_work_orders(uow: UnitOfWork, filters: WorkOrderFilters, *, limit: int = 50, offset: int = 0) -> Page[WorkOrderSummary]:
    return wo_reads.list_work_orders(uow, filters, limit=limit, offset=offset)


@query(READ)
def work_order(uow: UnitOfWork, work_order_id: uuid.UUID) -> WorkOrderRead:
    return wo_reads.work_order_read(uow, work_orders.get_work_order(uow, work_order_id))


@query(READ)
def work_order_by_number(uow: UnitOfWork, wo_number: str) -> WorkOrderRead:
    from app.modules.production.models import WorkOrder

    return wo_reads.work_order_read(uow, uow.repo(WorkOrder).get_by_key(wo_number))


def _detail(uow: UnitOfWork, work_order_id: uuid.UUID) -> WorkOrderRead:
    return wo_reads.work_order_read(uow, work_orders.get_work_order(uow, work_order_id))


@query(None)
def create_work_order(uow: UnitOfWork, data: WorkOrderCreate) -> WorkOrderRead:
    return _detail(uow, work_orders.create_work_order(uow, data).id)


@query(None)
def update_work_order(uow: UnitOfWork, work_order_id: uuid.UUID, data: WorkOrderUpdate) -> WorkOrderRead:
    return _detail(uow, work_orders.update_work_order(uow, work_order_id, data).id)


@query(None)
def transition_work_order(uow: UnitOfWork, work_order_id: uuid.UUID, data: WorkOrderTransition) -> WorkOrderRead:
    return _detail(uow, work_orders.transition(uow, work_order_id, data).id)


@query(None)
def recheck_materials(uow: UnitOfWork, work_order_id: uuid.UUID) -> WorkOrderRead:
    return _detail(uow, work_orders.recheck(uow, work_order_id).id)


@query(None)
def issue_materials(uow: UnitOfWork, work_order_id: uuid.UUID, data: IssueRequest) -> WorkOrderRead:
    return _detail(uow, wip.issue(uow, work_order_id, data).id)


@query(None)
def consume_materials(uow: UnitOfWork, work_order_id: uuid.UUID, data: WipRequest) -> WorkOrderRead:
    return _detail(uow, wip.consume(uow, work_order_id, data).id)


@query(None)
def return_materials(uow: UnitOfWork, work_order_id: uuid.UUID, data: WipRequest) -> WorkOrderRead:
    return _detail(uow, wip.return_material(uow, work_order_id, data).id)


@query(None)
def report_output(uow: UnitOfWork, work_order_id: uuid.UUID, data: OutputRequest) -> WorkOrderRead:
    return _detail(uow, wip.output(uow, work_order_id, data).id)


@query(None)
def complete_operation(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: OperationComplete) -> WorkOrderRead:
    return _detail(uow, wip.complete_operation(uow, work_order_id, operation_id, data).id)


@query(None)
def schedule_operation(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: OperationSchedule) -> WorkOrderRead:
    return _detail(uow, wip.schedule_operation(uow, work_order_id, operation_id, data).id)


@query(None)
def link_cut_plan(uow: UnitOfWork, work_order_id: uuid.UUID, operation_id: uuid.UUID, data: CutPlanLink) -> WorkOrderRead:
    return _detail(uow, wip.link_cut_plan(uow, work_order_id, operation_id, data).id)


@query(None)
def record_offcut(uow: UnitOfWork, work_order_id: uuid.UUID, data: OffcutRecord) -> WorkOrderRead:
    return _detail(uow, wip.record_offcut(uow, work_order_id, data).id)


# ---- planning ---------------------------------------------------------------------------------------------------------------
@query("production.capacity.read")
def capacity(uow: UnitOfWork, date_from: date | None = None, date_to: date | None = None,
             work_center_id: uuid.UUID | None = None) -> CapacityRead:
    start = date_from or business_date(uow)
    return _capacity.capacity_view(uow, start, date_to or start + timedelta(days=13), work_center_id)


@query(costing.RUN)
def run_cost_rollup(uow: UnitOfWork, data: CostRollupRequest) -> CostRollupRead:
    return costing.run_rollup(uow, data)


@query(None)
def cost_rollups(uow: UnitOfWork, *, product_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0) -> Page[CostRollupRead]:
    return costing.list_rollups(uow, product_id=product_id, limit=limit, offset=offset)


@query(None)
def cost_rollup(uow: UnitOfWork, rollup_id: uuid.UUID) -> CostRollupRead:
    return costing.get_rollup(uow, rollup_id)


@query(feasibility.RUN)
def assess_feasibility(uow: UnitOfWork, data: FeasibilityRequest) -> FeasibilityRead:
    return feasibility.assess(uow, data)


@query(feasibility.RUN)
def assess_order_line(uow: UnitOfWork, line_id: uuid.UUID, need_by: date | None = None) -> FeasibilityRead:
    return feasibility.assess_order_line(uow, line_id, need_by)


@query(feasibility.SIMULATE)
def simulate(uow: UnitOfWork, data: SimulationRequest) -> SimulationRead:
    return feasibility.simulate(uow, data)
