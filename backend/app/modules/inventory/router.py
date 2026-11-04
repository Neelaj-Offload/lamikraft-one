"""Inventory API (``/api/v1/inventory``): stock by product and warehouse, positions, availability, the ledger browser,
postings and reversals, relocations, reservations, shortages, warehouses and bins, lots, reorder rules, adjustments,
opening batches, transfers, stock counts and pick lists. Commands accept ``Idempotency-Key`` (replays return the
stored response with ``Idempotent-Replayed: true``). Routers never import models; services enforce scope and state."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor, IdempotencyKeyHeader
from app.core.http.pagination import MAX_LIMIT
from app.modules.inventory import commands as cmd
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    Availability,
    BinCreate,
    CountCreate,
    CountEntries,
    CountLineAdd,
    CountRead,
    Decision,
    DocumentRead,
    DocumentSummary,
    LotCreate,
    LotMeasure,
    LotRead,
    MovementPage,
    OpeningBatchCreate,
    PickConfirm,
    PickListCreate,
    PickListRead,
    PostingRead,
    ProductPosition,
    RelocationCreate,
    ReorderRuleIn,
    ReorderRuleRead,
    ReservationPage,
    ReservationRead,
    ReservationRelease,
    ReverseRequest,
    ShortageRead,
    StockPage,
    TransferCreate,
    Versioned,
    WarehouseCreate,
    WarehouseRead,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/inventory", tags=["inventory"])
READ = "inventory.stock.read"
REPLAYED = "Idempotent-Replayed"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


def _run[T: BaseModel](
    actor: Any, response: Response, operation: str, body: Any, fn: Callable[[UnitOfWork], T], model: type[T]
) -> T:
    with UnitOfWork(actor) as uow:
        out, replayed = cmd.idempotent(uow, operation, body, lambda: fn(uow), model)
    if replayed:
        response.headers[REPLAYED] = "true"
    return out


# ---- stock, positions, availability ------------------------------------------------------------------------
@router.get("/stock", openapi_extra=requires(READ))
def list_stock(
    actor: Actor,
    q: Annotated[str | None, Query(max_length=200)] = None,
    warehouse_id: uuid.UUID | None = None,
    short_only: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> StockPage:
    """Stock by product and warehouse from the projections: on hand (company-owned in bins), reserved, available,
    QC hold, rejected, the open shortage and the reorder minimum; filters apply before paging."""
    with UnitOfWork(actor) as uow:
        return cmd.stock_page(
            uow, q=q, warehouse_id=warehouse_id, short_only=short_only, limit=limit, offset=offset
        )


@router.get("/stock/{product_id}", openapi_extra=requires(READ))
def get_product_position(actor: Actor, product_id: uuid.UUID) -> ProductPosition:
    """Where a product is: per warehouse, per location and lot, external holdings and in transit."""
    with UnitOfWork(actor) as uow:
        return cmd.product_position(uow, product_id)


@router.get("/availability", openapi_extra=requires(READ))
def get_availability(actor: Actor, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> Availability:
    with UnitOfWork(actor) as uow:
        return cmd.availability(uow, product_id, warehouse_id)


# ---- ledger --------------------------------------------------------------------------------------------
@router.get("/movements", openapi_extra=requires(READ))
def list_movements(
    actor: Actor,
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    source_type: Annotated[str | None, Query(pattern=r"^[a-z_]{1,30}$")] = None,
    source_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> MovementPage:
    """The immutable ledger, newest first, limited to movements touching the actor's warehouses."""
    with UnitOfWork(actor) as uow:
        return cmd.movement_page(
            uow,
            product_id=product_id,
            warehouse_id=warehouse_id,
            source_type=source_type,
            source_id=source_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )


@router.get("/postings/{posting_id}", openapi_extra=requires(READ))
def get_posting(actor: Actor, posting_id: uuid.UUID) -> PostingRead:
    with UnitOfWork(actor) as uow:
        return cmd.posting_read(uow, posting_id)


@router.post(
    "/postings/{posting_id}/reverse", status_code=201, openapi_extra=requires("inventory.posting.reverse")
)
def reverse_posting(
    actor: Actor,
    posting_id: uuid.UUID,
    body: ReverseRequest,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PostingRead:
    """A compensating posting (from/to swapped) with ``reverses_posting_id``; at most once per posting; needs a recent
    sign-in. Challan postings are corrected by cancelling the challan."""
    return _run(
        actor,
        response,
        f"inventory.reverse:{posting_id}",
        body,
        lambda uow: cmd.reverse(uow, posting_id, body),
        PostingRead,
    )


@router.post("/relocations", status_code=201, openapi_extra=requires("inventory.stock.post"))
def create_relocation(
    actor: Actor, body: RelocationCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PostingRead:
    """Bin-to-bin move inside a warehouse (one posting)."""
    return _run(actor, response, "inventory.relocate", body, lambda uow: cmd.relocate(uow, body), PostingRead)


# ---- reservations and shortages ------------------------------------------------------------------------------
@router.get("/reservations", openapi_extra=requires(READ))
def list_reservations(
    actor: Actor,
    status: Annotated[str | None, Query(pattern=r"^(active|fulfilled|released|cancelled)$")] = None,
    product_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ReservationPage:
    with UnitOfWork(actor) as uow:
        return cmd.reservation_page(
            uow,
            status=status,
            product_id=product_id,
            warehouse_id=warehouse_id,
            demand_parent_id=order_id,
            limit=limit,
            offset=offset,
        )


@router.post("/reservations/{reservation_id}/release", openapi_extra=requires("inventory.stock.reserve"))
def release_reservation(
    actor: Actor,
    reservation_id: uuid.UUID,
    body: ReservationRelease,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ReservationRead:
    return _run(
        actor,
        response,
        f"inventory.release:{reservation_id}",
        body,
        lambda uow: cmd.release(uow, reservation_id, body),
        ReservationRead,
    )


@router.get("/shortages", openapi_extra=requires(READ))
def list_shortages(
    actor: Actor, include_resolved: bool = False, warehouse_id: uuid.UUID | None = None
) -> list[ShortageRead]:
    """Persisted shortages (unreserved demand beyond free stock) with their causes (demands first)."""
    with UnitOfWork(actor) as uow:
        return cmd.shortage_reads(uow, include_resolved=include_resolved, warehouse_id=warehouse_id)


# ---- warehouses, bins, lots, reorder rules -----------------------------------------------------------------------
@router.get("/warehouses", openapi_extra=requires(READ))
def list_warehouses(actor: Actor) -> list[WarehouseRead]:
    with UnitOfWork(actor) as uow:
        return cmd.warehouses(uow)


@router.post("/warehouses", status_code=201, openapi_extra=requires("inventory.warehouse.manage"))
def create_warehouse(
    actor: Actor, body: WarehouseCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> WarehouseRead:
    """A warehouse with its STOCK, QC and REJ locations (admin)."""
    return _run(
        actor,
        response,
        "inventory.warehouse.create",
        body,
        lambda uow: cmd.create_warehouse(uow, body),
        WarehouseRead,
    )


@router.post(
    "/warehouses/{warehouse_id}/bins", status_code=201, openapi_extra=requires("inventory.warehouse.manage")
)
def create_bin(
    actor: Actor,
    warehouse_id: uuid.UUID,
    body: BinCreate,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> WarehouseRead:
    return _run(
        actor,
        response,
        f"inventory.bin:{warehouse_id}",
        body,
        lambda uow: cmd.create_bin(uow, warehouse_id, body),
        WarehouseRead,
    )


@router.get("/lots", openapi_extra=requires(READ))
def list_lots(
    actor: Actor, product_id: uuid.UUID | None = None, limit: Limit = 50, offset: Offset = 0
) -> list[LotRead]:
    with UnitOfWork(actor) as uow:
        return cmd.lots(uow, product_id=product_id, limit=limit, offset=offset)


@router.post("/lots", status_code=201, openapi_extra=requires("inventory.lot.manage"))
def create_lot(
    actor: Actor, body: LotCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> LotRead:
    return _run(actor, response, "inventory.lot.create", body, lambda uow: cmd.create_lot(uow, body), LotRead)


@router.post("/lots/{lot_id}/measure", openapi_extra=requires("inventory.lot.manage"))
def measure_lot(
    actor: Actor,
    lot_id: uuid.UUID,
    body: LotMeasure,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> LotRead:
    """Record measured dimensions (offcuts, board lots): ``inventory.lot.measured``."""
    return _run(
        actor,
        response,
        f"inventory.lot.measure:{lot_id}",
        body,
        lambda uow: cmd.measure_lot(uow, lot_id, body),
        LotRead,
    )


@router.get("/reorder-rules", openapi_extra=requires(READ))
def list_reorder_rules(actor: Actor, below_min_only: bool = False) -> list[ReorderRuleRead]:
    with UnitOfWork(actor) as uow:
        return cmd.reorder_rules(uow, below_min_only=below_min_only)


@router.put("/reorder-rules", openapi_extra=requires("inventory.reorder_rule.manage"))
def put_reorder_rule(
    actor: Actor, body: ReorderRuleIn, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> ReorderRuleRead:
    return _run(
        actor,
        response,
        "inventory.reorder_rule.put",
        body,
        lambda uow: cmd.put_reorder_rule(uow, body),
        ReorderRuleRead,
    )


# ---- documents ---------------------------------------------------------------------------------------------------
@router.get("/documents", openapi_extra=requires(READ))
def list_documents(
    actor: Actor,
    kind: Annotated[str, Query(pattern=r"^(adjustment|opening_batch|transfer|stock_count|pick_list)$")],
    status: Annotated[str | None, Query(pattern=r"^[a-z_]{1,20}$")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[DocumentSummary]:
    with UnitOfWork(actor) as uow:
        return cmd.documents_list(uow, kind, status=status, limit=limit, offset=offset)


@router.post("/adjustments", status_code=201, openapi_extra=requires("inventory.adjustment.create"))
def create_adjustment(
    actor: Actor, body: AdjustmentCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> DocumentRead:
    return _run(
        actor,
        response,
        "inventory.adjustment.create",
        body,
        lambda uow: cmd.create_adjustment(uow, body),
        DocumentRead,
    )


@router.get("/adjustments/{adjustment_id}", openapi_extra=requires(READ))
def get_adjustment(actor: Actor, adjustment_id: uuid.UUID) -> DocumentRead:
    with UnitOfWork(actor) as uow:
        return cmd.get_adjustment(uow, adjustment_id)


@router.post("/adjustments/{adjustment_id}/submit", openapi_extra=requires("inventory.adjustment.create"))
def submit_adjustment(
    actor: Actor,
    adjustment_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    return _run(
        actor,
        response,
        f"inventory.adjustment.submit:{adjustment_id}",
        body,
        lambda uow: cmd.submit_adjustment(uow, adjustment_id, body),
        DocumentRead,
    )


@router.post("/adjustments/{adjustment_id}/approve", openapi_extra=requires("inventory.adjustment.approve"))
def approve_adjustment(
    actor: Actor,
    adjustment_id: uuid.UUID,
    body: Decision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    """Approve and post (the approver is never the creator); may eat into reservations, which emits a shortfall."""
    return _run(
        actor,
        response,
        f"inventory.adjustment.approve:{adjustment_id}",
        body,
        lambda uow: cmd.decide_adjustment(uow, adjustment_id, body, True),
        DocumentRead,
    )


@router.post("/adjustments/{adjustment_id}/reject", openapi_extra=requires("inventory.adjustment.approve"))
def reject_adjustment(
    actor: Actor,
    adjustment_id: uuid.UUID,
    body: Decision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    return _run(
        actor,
        response,
        f"inventory.adjustment.reject:{adjustment_id}",
        body,
        lambda uow: cmd.decide_adjustment(uow, adjustment_id, body, False),
        DocumentRead,
    )


@router.post("/opening-batches", status_code=201, openapi_extra=requires("inventory.opening_batch.create"))
def create_opening_batch(
    actor: Actor, body: OpeningBatchCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> DocumentRead:
    """Opening stock to be approved by a different person (rejected where non-opening movements exist unless a line
    is marked ``late_opening``). Needs a recent sign-in."""
    return _run(
        actor,
        response,
        "inventory.opening_batch.create",
        body,
        lambda uow: cmd.create_opening_batch(uow, body),
        DocumentRead,
    )


@router.get("/opening-batches/{batch_id}", openapi_extra=requires(READ))
def get_opening_batch(actor: Actor, batch_id: uuid.UUID) -> DocumentRead:
    with UnitOfWork(actor) as uow:
        return cmd.get_opening_batch(uow, batch_id)


@router.post("/opening-batches/{batch_id}/submit", openapi_extra=requires("inventory.opening_batch.create"))
def submit_opening_batch(
    actor: Actor,
    batch_id: uuid.UUID,
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    return _run(
        actor,
        response,
        f"inventory.opening_batch.submit:{batch_id}",
        body,
        lambda uow: cmd.submit_opening_batch(uow, batch_id, body),
        DocumentRead,
    )


@router.post("/opening-batches/{batch_id}/approve", openapi_extra=requires("inventory.opening_batch.approve"))
def approve_opening_batch(
    actor: Actor,
    batch_id: uuid.UUID,
    body: Decision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    """Approve and post the batch from the opening location (MFA step-up; never the creator)."""
    return _run(
        actor,
        response,
        f"inventory.opening_batch.approve:{batch_id}",
        body,
        lambda uow: cmd.decide_opening_batch(uow, batch_id, body, True),
        DocumentRead,
    )


@router.post("/opening-batches/{batch_id}/reject", openapi_extra=requires("inventory.opening_batch.approve"))
def reject_opening_batch(
    actor: Actor,
    batch_id: uuid.UUID,
    body: Decision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    return _run(
        actor,
        response,
        f"inventory.opening_batch.reject:{batch_id}",
        body,
        lambda uow: cmd.decide_opening_batch(uow, batch_id, body, False),
        DocumentRead,
    )


@router.post("/transfers", status_code=201, openapi_extra=requires("inventory.stock.post"))
def create_transfer(
    actor: Actor, body: TransferCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> DocumentRead:
    return _run(
        actor,
        response,
        "inventory.transfer.create",
        body,
        lambda uow: cmd.create_transfer(uow, body),
        DocumentRead,
    )


@router.get("/transfers/{transfer_id}", openapi_extra=requires(READ))
def get_transfer(actor: Actor, transfer_id: uuid.UUID) -> DocumentRead:
    with UnitOfWork(actor) as uow:
        return cmd.get_transfer(uow, transfer_id)


@router.post("/transfers/{transfer_id}/{action}", openapi_extra=requires("inventory.stock.post"))
def act_on_transfer(
    actor: Actor,
    transfer_id: uuid.UUID,
    action: Annotated[str, Path(pattern=r"^(dispatch|receive|cancel)$")],
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> DocumentRead:
    """``dispatch`` (stock to in transit), ``receive`` (into the destination) or ``cancel`` (drafts)."""
    return _run(
        actor,
        response,
        f"inventory.transfer.{action}:{transfer_id}",
        body,
        lambda uow: cmd.transfer_action(uow, transfer_id, action, body),
        DocumentRead,
    )


@router.post("/stock-counts", status_code=201, openapi_extra=requires("inventory.stock_count.create"))
def create_stock_count(
    actor: Actor, body: CountCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> CountRead:
    return _run(
        actor,
        response,
        "inventory.stock_count.create",
        body,
        lambda uow: cmd.create_count(uow, body),
        CountRead,
    )


@router.get("/stock-counts/{count_id}", openapi_extra=requires(READ))
def get_stock_count(actor: Actor, count_id: uuid.UUID) -> CountRead:
    with UnitOfWork(actor) as uow:
        return cmd.get_count(uow, count_id)


@router.post("/stock-counts/{count_id}/entries", openapi_extra=requires("inventory.stock_count.create"))
def enter_stock_counts(
    actor: Actor,
    count_id: uuid.UUID,
    body: CountEntries,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CountRead:
    return _run(
        actor,
        response,
        f"inventory.stock_count.entries:{count_id}",
        body,
        lambda uow: cmd.enter_counts(uow, count_id, body),
        CountRead,
    )


@router.post(
    "/stock-counts/{count_id}/lines", status_code=201, openapi_extra=requires("inventory.stock_count.create")
)
def add_stock_count_line(
    actor: Actor,
    count_id: uuid.UUID,
    body: CountLineAdd,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CountRead:
    return _run(
        actor,
        response,
        f"inventory.stock_count.line:{count_id}",
        body,
        lambda uow: cmd.add_count_line(uow, count_id, body),
        CountRead,
    )


@router.post("/stock-counts/{count_id}/approve", openapi_extra=requires("inventory.stock_count.approve"))
def approve_stock_count(
    actor: Actor,
    count_id: uuid.UUID,
    body: Decision,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CountRead:
    """Post ``counted - snapshot`` per line (the approver is not the person who submitted the count)."""
    return _run(
        actor,
        response,
        f"inventory.stock_count.approve:{count_id}",
        body,
        lambda uow: cmd.approve_count(uow, count_id, body),
        CountRead,
    )


@router.post("/stock-counts/{count_id}/{action}", openapi_extra=requires("inventory.stock_count.create"))
def act_on_stock_count(
    actor: Actor,
    count_id: uuid.UUID,
    action: Annotated[str, Path(pattern=r"^(freeze|submit|cancel)$")],
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> CountRead:
    """``freeze`` (snapshot + high-water mark), ``submit`` (every line counted) or ``cancel``."""
    return _run(
        actor,
        response,
        f"inventory.stock_count.{action}:{count_id}",
        body,
        lambda uow: cmd.count_action(uow, count_id, action, body),
        CountRead,
    )


@router.post("/pick-lists", status_code=201, openapi_extra=requires("inventory.pick_list.create"))
def create_pick_list(
    actor: Actor, body: PickListCreate, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PickListRead:
    """Pick lines from the order's active reservations (picking posts nothing)."""
    return _run(
        actor,
        response,
        "inventory.pick_list.create",
        body,
        lambda uow: cmd.create_pick_list(uow, body),
        PickListRead,
    )


@router.get("/pick-lists/{pick_list_id}", openapi_extra=requires(READ))
def get_pick_list(actor: Actor, pick_list_id: uuid.UUID) -> PickListRead:
    with UnitOfWork(actor) as uow:
        return cmd.get_pick_list(uow, pick_list_id)


@router.post("/pick-lists/{pick_list_id}/pick", openapi_extra=requires("inventory.pick_list.update"))
def confirm_pick(
    actor: Actor,
    pick_list_id: uuid.UUID,
    body: PickConfirm,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PickListRead:
    """Picked quantities; a short pick releases the unpicked part of the reservation."""
    return _run(
        actor,
        response,
        f"inventory.pick_list.pick:{pick_list_id}",
        body,
        lambda uow: cmd.confirm_pick(uow, pick_list_id, body),
        PickListRead,
    )


@router.post(
    "/pick-lists/{pick_list_id}/challan", status_code=201, openapi_extra=requires("challans.challan.create")
)
def challan_from_pick_list(
    actor: Actor, pick_list_id: uuid.UUID, response: Response, idempotency_key: IdempotencyKeyHeader = None
) -> PickListRead:
    """A draft challan with the picked quantities (its issue is the one movement)."""
    return _run(
        actor,
        response,
        f"inventory.pick_list.challan:{pick_list_id}",
        {},
        lambda uow: cmd.challan_from_pick_list(uow, pick_list_id),
        PickListRead,
    )


@router.post("/pick-lists/{pick_list_id}/{action}", openapi_extra=requires("inventory.pick_list.create"))
def act_on_pick_list(
    actor: Actor,
    pick_list_id: uuid.UUID,
    action: Annotated[str, Path(pattern=r"^(release|cancel)$")],
    body: Versioned,
    response: Response,
    idempotency_key: IdempotencyKeyHeader = None,
) -> PickListRead:
    """``release`` (a picking task) or ``cancel``."""
    return _run(
        actor,
        response,
        f"inventory.pick_list.{action}:{pick_list_id}",
        body,
        lambda uow: cmd.pick_list_action(uow, pick_list_id, action, body),
        PickListRead,
    )
