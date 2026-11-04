"""Production API (``/api/v1/production``): work centres and capacity exceptions, BOM and routing versions (approve /
retire), work orders (plan, update, transitions, material reservations, issue / consume / return, output, operations,
cut-plan links, offcut lots), capacity, cost rollups, feasibility (also for an order line) and the what-if
simulation. Commands accept ``Idempotency-Key`` (replays answer ``Idempotent-Replayed: true``)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.inventory.commands import idempotent
from app.modules.production import service
from app.modules.production.enums import MasterStatus, WorkOrderStatus
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
    WorkOrderVersioned,
)
from app.platform.authz.redaction import redact
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/production", tags=["production"])
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]
WO_READ, WO_CREATE, WO_UPDATE = "production.work_order.read", "production.work_order.create", "production.work_order.update"
WO_TRANSITION, WO_POST = "production.work_order.transition", "production.work_order.post"


def _run[T: BaseModel](actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T],
                       model: type[T]) -> T:
    with UnitOfWork(actor) as uow:
        out, replayed = idempotent(uow, operation, body, lambda: fn(uow), model)
        out = redact(out, uow.actor)
    if replayed:
        response.headers[REPLAYED] = "true"
    return out


# ---- work centres ----------------------------------------------------------------------------------------------------------
@router.get("/work-centers", openapi_extra=requires("production.capacity.read"))
def list_work_centers(actor: Actor, include_inactive: bool = False) -> list[WorkCenterSummary]:
    """Work centres with their standard daily minutes (shifts x machines x efficiency); the hourly rate only for
    ``pricing.cost.read``."""
    return service.list_work_centers(actor, include_inactive=include_inactive)


@router.post("/work-centers", status_code=201, openapi_extra=requires("production.work_center.manage"))
def create_work_center(actor: Actor, body: WorkCenterCreate, response: Response,
                       idempotency_key: IdempotencyKeyHeader = None) -> WorkCenterRead:
    return _run(actor, response, "production.work_center.create", body,
                lambda uow: service.create_work_center(uow, body), WorkCenterRead)


@router.get("/work-centers/{work_center_id}", openapi_extra=requires("production.capacity.read"))
def get_work_center(actor: Actor, work_center_id: uuid.UUID) -> WorkCenterRead:
    """Calendar, shifts, exceptions and the capabilities of the caller."""
    return service.work_center(actor, work_center_id)


@router.patch("/work-centers/{work_center_id}", openapi_extra=requires("production.work_center.manage"))
def update_work_center(actor: Actor, work_center_id: uuid.UUID, body: WorkCenterUpdate, response: Response,
                       idempotency_key: IdempotencyKeyHeader = None) -> WorkCenterRead:
    return _run(actor, response, f"production.work_center.update:{work_center_id}", body,
                lambda uow: service.update_work_center(uow, work_center_id, body), WorkCenterRead)


@router.put("/work-centers/{work_center_id}/capacity-exceptions", openapi_extra=requires("production.work_center.manage"))
def set_capacity_exception(actor: Actor, work_center_id: uuid.UUID, body: CapacityExceptionIn, response: Response,
                           idempotency_key: IdempotencyKeyHeader = None) -> WorkCenterRead:
    """Set the available minutes of one day (maintenance, overtime); replaces an existing exception of that day."""
    return _run(actor, response, f"production.capacity_exception.set:{work_center_id}", body,
                lambda uow: service.set_capacity_exception(uow, work_center_id, body), WorkCenterRead)


@router.delete("/work-centers/{work_center_id}/capacity-exceptions/{exception_id}",
               openapi_extra=requires("production.work_center.manage"))
def delete_capacity_exception(actor: Actor, work_center_id: uuid.UUID, exception_id: uuid.UUID) -> WorkCenterRead:
    return service.delete_capacity_exception(actor, work_center_id, exception_id)


# ---- BOMs ---------------------------------------------------------------------------------------------------------------------
@router.get("/boms", openapi_extra=requires("production.bom.read"))
def list_boms(actor: Actor, product_id: uuid.UUID | None = None,
              status: Annotated[list[MasterStatus] | None, Query()] = None,
              q: Annotated[str | None, Query(max_length=200)] = None, limit: Limit = 50, offset: Offset = 0) -> Page[MasterSummary]:
    return service.list_boms(actor, product_id=product_id, status=[s.value for s in status] if status else None, q=q,
                             limit=limit, offset=offset)


@router.post("/boms", status_code=201, openapi_extra=requires("production.bom.manage"))
def create_bom(actor: Actor, body: BomCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None) -> BomRead:
    """A new draft version of the product's BOM (``copy_from_id`` starts from an existing version's lines)."""
    return _run(actor, response, "production.bom.create", body, lambda uow: service.create_bom(uow, body), BomRead)


@router.get("/boms/{bom_id}", openapi_extra=requires("production.bom.read"))
def get_bom(actor: Actor, bom_id: uuid.UUID) -> BomRead:
    return service.bom(actor, bom_id)


@router.patch("/boms/{bom_id}", openapi_extra=requires("production.bom.manage"))
def update_bom(actor: Actor, bom_id: uuid.UUID, body: BomUpdate, response: Response,
               idempotency_key: IdempotencyKeyHeader = None) -> BomRead:
    """Draft versions only (approved and retired versions are immutable: 409 ``version_approved``)."""
    return _run(actor, response, f"production.bom.update:{bom_id}", body, lambda uow: service.update_bom(uow, bom_id, body), BomRead)


@router.post("/boms/{bom_id}/approve", openapi_extra=requires("production.bom.approve"))
def approve_bom(actor: Actor, bom_id: uuid.UUID, body: MasterCommand, response: Response,
                idempotency_key: IdempotencyKeyHeader = None) -> BomRead:
    """Never by the version's author (403 ``separation_of_duties``); validates units, alternates and cycles; retires
    the previously approved version."""
    return _run(actor, response, f"production.bom.approve:{bom_id}", body, lambda uow: service.approve_bom(uow, bom_id, body), BomRead)


@router.post("/boms/{bom_id}/retire", openapi_extra=requires("production.bom.manage"))
def retire_bom(actor: Actor, bom_id: uuid.UUID, body: MasterCommand, response: Response,
               idempotency_key: IdempotencyKeyHeader = None) -> BomRead:
    return _run(actor, response, f"production.bom.retire:{bom_id}", body, lambda uow: service.retire_bom(uow, bom_id, body), BomRead)


# ---- routings -----------------------------------------------------------------------------------------------------------------
@router.get("/routings", openapi_extra=requires("production.routing.read"))
def list_routings(actor: Actor, product_id: uuid.UUID | None = None,
                  status: Annotated[list[MasterStatus] | None, Query()] = None,
                  q: Annotated[str | None, Query(max_length=200)] = None, limit: Limit = 50, offset: Offset = 0) -> Page[MasterSummary]:
    return service.list_routings(actor, product_id=product_id, status=[s.value for s in status] if status else None, q=q,
                                 limit=limit, offset=offset)


@router.post("/routings", status_code=201, openapi_extra=requires("production.routing.manage"))
def create_routing(actor: Actor, body: RoutingCreate, response: Response,
                   idempotency_key: IdempotencyKeyHeader = None) -> RoutingRead:
    return _run(actor, response, "production.routing.create", body, lambda uow: service.create_routing(uow, body), RoutingRead)


@router.get("/routings/{routing_id}", openapi_extra=requires("production.routing.read"))
def get_routing(actor: Actor, routing_id: uuid.UUID) -> RoutingRead:
    return service.routing(actor, routing_id)


@router.patch("/routings/{routing_id}", openapi_extra=requires("production.routing.manage"))
def update_routing(actor: Actor, routing_id: uuid.UUID, body: RoutingUpdate, response: Response,
                   idempotency_key: IdempotencyKeyHeader = None) -> RoutingRead:
    return _run(actor, response, f"production.routing.update:{routing_id}", body,
                lambda uow: service.update_routing(uow, routing_id, body), RoutingRead)


@router.post("/routings/{routing_id}/approve", openapi_extra=requires("production.routing.approve"))
def approve_routing(actor: Actor, routing_id: uuid.UUID, body: MasterCommand, response: Response,
                    idempotency_key: IdempotencyKeyHeader = None) -> RoutingRead:
    return _run(actor, response, f"production.routing.approve:{routing_id}", body,
                lambda uow: service.approve_routing(uow, routing_id, body), RoutingRead)


@router.post("/routings/{routing_id}/retire", openapi_extra=requires("production.routing.manage"))
def retire_routing(actor: Actor, routing_id: uuid.UUID, body: MasterCommand, response: Response,
                   idempotency_key: IdempotencyKeyHeader = None) -> RoutingRead:
    return _run(actor, response, f"production.routing.retire:{routing_id}", body,
                lambda uow: service.retire_routing(uow, routing_id, body), RoutingRead)


# ---- work orders ---------------------------------------------------------------------------------------------------------------
def _wo_filters(
    q: Annotated[str | None, Query(max_length=200, description="Tokens matched against the WO number, product and order")] = None,
    status: Annotated[list[WorkOrderStatus] | None, Query()] = None,
    blocked: bool | None = None,
    product_id: uuid.UUID | None = None,
    sales_order_id: uuid.UUID | None = None,
    scope: Annotated[str, Query(pattern=r"^(mine|all)$")] = "all",
) -> WorkOrderFilters:
    return WorkOrderFilters(q=q, status=status, blocked=blocked, product_id=product_id, sales_order_id=sales_order_id,
                            scope=scope)  # type: ignore[arg-type]


@router.get("/work-orders", openapi_extra=requires(WO_READ))
def list_work_orders(actor: Actor, filters: Annotated[WorkOrderFilters, Depends(_wo_filters)], limit: Limit = 50,
                     offset: Offset = 0) -> Page[WorkOrderSummary]:
    """Work orders within the actor's scope (production company, operations their branches); filters before paging."""
    return service.list_work_orders(actor, filters, limit=limit, offset=offset)


@router.get("/work-orders/lookup", openapi_extra=requires(WO_READ))
def get_work_order_by_number(actor: Actor, wo_number: Annotated[str, Query(max_length=20)]) -> WorkOrderRead:
    return service.work_order_by_number(actor, wo_number)


@router.post("/work-orders", status_code=201, openapi_extra=requires(WO_CREATE))
def create_work_order(actor: Actor, body: WorkOrderCreate, response: Response,
                      idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Plan from a sales order line (product, remaining quantity, warehouse and date default from the order) or
    standalone; pins the product's approved BOM and routing versions."""
    return _run(actor, response, "production.work_order.create", body,
                lambda uow: service.create_work_order(uow, body), WorkOrderRead)


@router.get("/work-orders/{work_order_id}", openapi_extra=requires(WO_READ))
def get_work_order(actor: Actor, work_order_id: uuid.UUID) -> WorkOrderRead:
    """Materials (required, reserved, issued, consumed, returned, in WIP, free), operations with the linked cut plan,
    stock transactions, ``capabilities`` and ``allowed_transitions``."""
    return service.work_order(actor, work_order_id)


@router.patch("/work-orders/{work_order_id}", openapi_extra=requires(WO_UPDATE))
def update_work_order(actor: Actor, work_order_id: uuid.UUID, body: WorkOrderUpdate, response: Response,
                      idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Draft only: quantity (materials and minutes are re-planned), dates, notes."""
    return _run(actor, response, f"production.work_order.update:{work_order_id}", body,
                lambda uow: service.update_work_order(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/transitions", openapi_extra=requires(WO_TRANSITION))
def transition_work_order(actor: Actor, work_order_id: uuid.UUID, body: WorkOrderTransition, response: Response,
                          idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """``release`` (reserves materials; blocked when short; releases linked cut plans), ``complete`` (needs output),
    ``close`` (needs WIP cleared), ``cancel`` (reason; refused once output or consumption was posted)."""
    return _run(actor, response, f"production.work_order.transition:{work_order_id}", body,
                lambda uow: service.transition_work_order(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/recheck", openapi_extra=requires(WO_TRANSITION))
def recheck_work_order_materials(actor: Actor, work_order_id: uuid.UUID, body: WorkOrderVersioned, response: Response,
                                 idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Reserve again now (the event consumer does the same when stock arrives)."""
    return _run(actor, response, f"production.work_order.recheck:{work_order_id}", body,
                lambda uow: service.recheck_materials(uow, work_order_id), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/issue", openapi_extra=requires(WO_POST, "inventory.stock.post"))
def issue_work_order_materials(actor: Actor, work_order_id: uuid.UUID, body: IssueRequest, response: Response,
                               idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Post stock -> WIP (one posting), consuming the materials' reservations first."""
    return _run(actor, response, f"production.work_order.issue:{work_order_id}", body,
                lambda uow: service.issue_materials(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/consume", openapi_extra=requires(WO_POST, "inventory.stock.post"))
def consume_work_order_materials(actor: Actor, work_order_id: uuid.UUID, body: WipRequest, response: Response,
                                 idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Post WIP -> production (consumption)."""
    return _run(actor, response, f"production.work_order.consume:{work_order_id}", body,
                lambda uow: service.consume_materials(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/return", openapi_extra=requires(WO_POST, "inventory.stock.post"))
def return_work_order_materials(actor: Actor, work_order_id: uuid.UUID, body: WipRequest, response: Response,
                                idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Post WIP -> stock (unused material back); it is reserved again for the work order."""
    return _run(actor, response, f"production.work_order.return:{work_order_id}", body,
                lambda uow: service.return_materials(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/output", openapi_extra=requires(WO_POST, "inventory.stock.post"))
def report_work_order_output(actor: Actor, work_order_id: uuid.UUID, body: OutputRequest, response: Response,
                             idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Post good finished goods production -> stock (QC hold when the product requires QC); scrap is recorded."""
    return _run(actor, response, f"production.work_order.output:{work_order_id}", body,
                lambda uow: service.report_output(uow, work_order_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/operations/{operation_id}/complete", openapi_extra=requires(WO_POST))
def complete_work_order_operation(actor: Actor, work_order_id: uuid.UUID, operation_id: uuid.UUID, body: OperationComplete,
                                  response: Response, idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    return _run(actor, response, f"production.wo_operation.complete:{operation_id}", body,
                lambda uow: service.complete_operation(uow, work_order_id, operation_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/operations/{operation_id}/schedule", openapi_extra=requires(WO_TRANSITION))
def schedule_work_order_operation(actor: Actor, work_order_id: uuid.UUID, operation_id: uuid.UUID, body: OperationSchedule,
                                  response: Response, idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Move a pending operation to another day (capacity load and overloads follow)."""
    return _run(actor, response, f"production.wo_operation.schedule:{operation_id}", body,
                lambda uow: service.schedule_operation(uow, work_order_id, operation_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/operations/{operation_id}/cut-plan", openapi_extra=requires(WO_TRANSITION))
def link_work_order_cut_plan(actor: Actor, work_order_id: uuid.UUID, operation_id: uuid.UUID, body: CutPlanLink,
                             response: Response, idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """Link a calculated cut plan to the board operation: the sheet material then requires the plan's boards
    (``requirement_source=cut_plan``); a released work order releases the plan at once."""
    return _run(actor, response, f"production.wo_operation.cut_plan:{operation_id}", body,
                lambda uow: service.link_cut_plan(uow, work_order_id, operation_id, body), WorkOrderRead)


@router.post("/work-orders/{work_order_id}/offcuts", openapi_extra=requires(WO_POST, "inventory.lot.manage"))
def record_work_order_offcut(actor: Actor, work_order_id: uuid.UUID, body: OffcutRecord, response: Response,
                             idempotency_key: IdempotencyKeyHeader = None) -> WorkOrderRead:
    """A measured offcut becomes an ``offcut`` lot (``inventory.lot.measured``) posted production -> stock."""
    return _run(actor, response, f"production.work_order.offcut:{work_order_id}", body,
                lambda uow: service.record_offcut(uow, work_order_id, body), WorkOrderRead)


# ---- capacity, costing, feasibility, simulation ---------------------------------------------------------------------------------
@router.get("/capacity", openapi_extra=requires("production.capacity.read"))
def get_capacity(actor: Actor, date_from: Annotated[date | None, Query(alias="from")] = None,
                 date_to: Annotated[date | None, Query(alias="to")] = None, work_center_id: uuid.UUID | None = None) -> CapacityRead:
    """Load per work centre per day (pending operations of released work orders) against calendar capacity; at most 63
    days (default: two weeks from today)."""
    return service.capacity(actor, date_from, date_to, work_center_id)


@router.post("/cost-rollups", openapi_extra=requires("production.cost_rollup.run"))
def run_cost_rollup(actor: Actor, body: CostRollupRequest, response: Response,
                    idempotency_key: IdempotencyKeyHeader = None) -> CostRollupRead:
    """Deterministic rollup; the same inputs return the stored result (``reused``). Figures need ``pricing.cost.read``."""
    out = _run(actor, response, f"production.cost_rollup.run:{body.product_id}", body,
               lambda uow: service.run_cost_rollup(uow, body), CostRollupRead)
    response.status_code = 200 if out.reused else 201
    return out


@router.get("/cost-rollups", openapi_extra=requires("production.bom.read", "production.cost_rollup.run"))
def list_cost_rollups(actor: Actor, product_id: uuid.UUID | None = None, limit: Limit = 50, offset: Offset = 0) -> Page[CostRollupRead]:
    return service.cost_rollups(actor, product_id=product_id, limit=limit, offset=offset)


@router.get("/cost-rollups/{rollup_id}", openapi_extra=requires("production.bom.read", "production.cost_rollup.run"))
def get_cost_rollup(actor: Actor, rollup_id: uuid.UUID) -> CostRollupRead:
    return service.cost_rollup(actor, rollup_id)


@router.post("/feasibility", openapi_extra=requires("production.feasibility.run"))
def assess_feasibility(actor: Actor, body: FeasibilityRequest) -> FeasibilityRead:
    """Read-only: stock, supply, components and capacity evidence; nothing is reserved, posted or saved."""
    return service.assess_feasibility(actor, body)


@router.get("/feasibility/order-lines/{line_id}", openapi_extra=requires("production.feasibility.run"))
def assess_order_line_feasibility(actor: Actor, line_id: uuid.UUID, need_by: date | None = None) -> FeasibilityRead:
    """The remaining quantity of an order line by its requested date (404 when the order is not visible)."""
    return service.assess_order_line(actor, line_id, need_by)


@router.post("/simulations", openapi_extra=requires("production.simulation.run"))
def run_simulation(actor: Actor, body: SimulationRequest) -> SimulationRead:
    """What-if over an in-memory overlay next to the unchanged baseline; never writes."""
    return service.simulate(actor, body)
