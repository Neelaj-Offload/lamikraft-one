"""HTTP-facing command and query functions: each runs a service function in the caller's unit of work and returns
the read model. Kept apart from ``service.py`` (the cross-module API) so routers stay free of models."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.inventory import counts, documents, picking, reads
from app.modules.inventory.models import (
    Adjustment,
    Lot,
    OpeningBatch,
    PickList,
    ReorderRule,
    Reservation,
    StockCount,
    Transfer,
    Warehouse,
)
from app.modules.inventory.policies import require_warehouse, visible_warehouse_ids
from app.modules.inventory.reservations import release as _release
from app.modules.inventory.schemas import (
    AdjustmentCreate,
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
    OpeningBatchCreate,
    PickConfirm,
    PickListCreate,
    PickListRead,
    PostingRead,
    RelocationCreate,
    ReorderRuleIn,
    ReorderRuleRead,
    ReservationRead,
    ReservationRelease,
    ReverseRequest,
    TransferCreate,
    Versioned,
    WarehouseCreate,
    WarehouseRead,
)
from app.platform.idempotency.service import run_idempotent
from app.platform.uow import UnitOfWork

stock_page = reads.stock_page
product_position = reads.product_position
availability = reads.availability
movement_page = reads.movement_page
posting_read = reads.posting_read
reservation_page = reads.reservation_page
shortage_reads = reads.shortage_reads


def idempotent[T: BaseModel](
    uow: UnitOfWork, operation: str, body: Any, fn: Callable[[], T], model: type[T]
) -> tuple[T, bool]:
    payload = body.model_dump(mode="json") if isinstance(body, BaseModel) else body
    out, replayed = run_idempotent(
        uow,
        key=uow.actor.idempotency_key,
        operation=operation,
        body=payload,
        fn=lambda: fn().model_dump(mode="json"),
    )
    return model.model_validate(out), replayed


def _get(uow: UnitOfWork, model: type, doc_id: uuid.UUID, resource: str) -> Any:
    doc = uow.session.scalars(
        select(model).where(model.company_id == uow.actor.company_id, model.id == doc_id)
    ).first()
    if doc is None:
        raise NotFound(code="not_found", resource_type=resource)
    require_warehouse(uow, doc.from_warehouse_id if model is Transfer else doc.warehouse_id)
    return doc


# ---- ledger commands ----------------------------------------------------------------------------------------
def reverse(uow: UnitOfWork, posting_id: uuid.UUID, body: ReverseRequest) -> PostingRead:
    posting = documents.reverse_posting_command(
        uow, posting_id, reason_code=body.reason_code, reason=body.reason
    )
    return reads.posting_read(uow, posting.id)


def relocate(uow: UnitOfWork, body: RelocationCreate) -> PostingRead:
    return reads.posting_read(uow, documents.relocate(uow, body).id)


def release(uow: UnitOfWork, reservation_id: uuid.UUID, body: ReservationRelease) -> ReservationRead:
    res = uow.session.scalars(
        select(Reservation).where(
            Reservation.company_id == uow.actor.company_id, Reservation.id == reservation_id
        )
    ).first()
    if res is None or res.warehouse_id not in set(visible_warehouse_ids(uow)):
        raise NotFound(code="not_found", resource_type="inventory.reservation")
    require_warehouse(uow, res.warehouse_id, "inventory.stock.reserve")
    _release(uow, reservation_id, reason_code=body.reason_code, quantity=body.quantity)
    return reads.reservation_reads(uow, [uow.session.get(Reservation, reservation_id)])[0]  # type: ignore[list-item]


# ---- master data ----------------------------------------------------------------------------------------------
def warehouses(uow: UnitOfWork) -> list[WarehouseRead]:
    rows = uow.session.scalars(
        select(Warehouse).where(Warehouse.id.in_(visible_warehouse_ids(uow))).order_by(Warehouse.code)
    )
    return [documents.warehouse_read(uow, w) for w in rows]


def create_warehouse(uow: UnitOfWork, body: WarehouseCreate) -> WarehouseRead:
    return documents.warehouse_read(uow, documents.create_warehouse(uow, body))


def create_bin(uow: UnitOfWork, warehouse_id: uuid.UUID, body: BinCreate) -> WarehouseRead:
    documents.create_bin(uow, warehouse_id, body)
    return documents.warehouse_read(uow, require_warehouse(uow, warehouse_id))


def lots(uow: UnitOfWork, *, product_id: uuid.UUID | None, limit: int, offset: int) -> list[LotRead]:
    stmt = select(Lot).where(Lot.company_id == uow.actor.company_id)
    if product_id:
        stmt = stmt.where(Lot.product_id == product_id)
    return [
        documents.lot_read(uow, lot)
        for lot in uow.session.scalars(stmt.order_by(Lot.lot_code).limit(limit).offset(offset))
    ]


def create_lot(uow: UnitOfWork, body: LotCreate) -> LotRead:
    return documents.lot_read(uow, documents.create_lot(uow, body))


def measure_lot(uow: UnitOfWork, lot_id: uuid.UUID, body: LotMeasure) -> LotRead:
    return documents.lot_read(uow, documents.measure_lot(uow, lot_id, body))


def reorder_rules(uow: UnitOfWork, *, below_min_only: bool) -> list[ReorderRuleRead]:
    rows = list(
        uow.session.scalars(
            select(ReorderRule).where(
                ReorderRule.company_id == uow.actor.company_id,
                ReorderRule.warehouse_id.in_(visible_warehouse_ids(uow)),
            )
        )
    )
    out = documents.reorder_reads(uow, rows)
    return [r for r in out if r.below_min] if below_min_only else out


def put_reorder_rule(uow: UnitOfWork, body: ReorderRuleIn) -> ReorderRuleRead:
    return documents.reorder_reads(uow, [documents.upsert_reorder_rule(uow, body)])[0]


# ---- documents ---------------------------------------------------------------------------------------------------
def documents_list(
    uow: UnitOfWork, kind: str, *, status: str | None, limit: int, offset: int
) -> list[DocumentSummary]:
    return documents.document_summaries(uow, kind, status=status, limit=limit, offset=offset)[0]


def create_adjustment(uow: UnitOfWork, body: AdjustmentCreate) -> DocumentRead:
    return documents.adjustment_read(uow, documents.create_adjustment(uow, body))


def get_adjustment(uow: UnitOfWork, adjustment_id: uuid.UUID) -> DocumentRead:
    return documents.adjustment_read(uow, _get(uow, Adjustment, adjustment_id, "inventory.adjustment"))


def submit_adjustment(uow: UnitOfWork, adjustment_id: uuid.UUID, body: Versioned) -> DocumentRead:
    return documents.adjustment_read(uow, documents.submit_adjustment(uow, adjustment_id, body))


def decide_adjustment(
    uow: UnitOfWork, adjustment_id: uuid.UUID, body: Decision, approve: bool
) -> DocumentRead:
    return documents.adjustment_read(
        uow, documents.decide_adjustment(uow, adjustment_id, body, approve=approve)
    )


def create_opening_batch(uow: UnitOfWork, body: OpeningBatchCreate) -> DocumentRead:
    return documents.opening_read(uow, documents.create_opening_batch(uow, body))


def get_opening_batch(uow: UnitOfWork, batch_id: uuid.UUID) -> DocumentRead:
    return documents.opening_read(uow, _get(uow, OpeningBatch, batch_id, "inventory.opening_batch"))


def submit_opening_batch(uow: UnitOfWork, batch_id: uuid.UUID, body: Versioned) -> DocumentRead:
    return documents.opening_read(uow, documents.submit_opening_batch(uow, batch_id, body))


def decide_opening_batch(uow: UnitOfWork, batch_id: uuid.UUID, body: Decision, approve: bool) -> DocumentRead:
    return documents.opening_read(uow, documents.decide_opening_batch(uow, batch_id, body, approve=approve))


def create_transfer(uow: UnitOfWork, body: TransferCreate) -> DocumentRead:
    return documents.transfer_read(uow, documents.create_transfer(uow, body))


def get_transfer(uow: UnitOfWork, transfer_id: uuid.UUID) -> DocumentRead:
    return documents.transfer_read(uow, _get(uow, Transfer, transfer_id, "inventory.transfer"))


def transfer_action(uow: UnitOfWork, transfer_id: uuid.UUID, action: str, body: Versioned) -> DocumentRead:
    fn = {
        "dispatch": documents.dispatch_transfer,
        "receive": documents.receive_transfer,
        "cancel": documents.cancel_transfer,
    }[action]
    return documents.transfer_read(uow, fn(uow, transfer_id, body))


def create_count(uow: UnitOfWork, body: CountCreate) -> CountRead:
    return counts.count_read(uow, counts.create_count(uow, body))


def get_count(uow: UnitOfWork, count_id: uuid.UUID) -> CountRead:
    return counts.count_read(uow, _get(uow, StockCount, count_id, "inventory.stock_count"))


def enter_counts(uow: UnitOfWork, count_id: uuid.UUID, body: CountEntries) -> CountRead:
    return counts.count_read(uow, counts.enter_counts(uow, count_id, body))


def add_count_line(uow: UnitOfWork, count_id: uuid.UUID, body: CountLineAdd) -> CountRead:
    return counts.count_read(uow, counts.add_count_line(uow, count_id, body))


def approve_count(uow: UnitOfWork, count_id: uuid.UUID, body: Decision) -> CountRead:
    return counts.count_read(uow, counts.approve_count(uow, count_id, body))


def count_action(uow: UnitOfWork, count_id: uuid.UUID, action: str, body: Versioned) -> CountRead:
    fn = {"freeze": counts.freeze_count, "submit": counts.submit_count, "cancel": counts.cancel_count}[action]
    return counts.count_read(uow, fn(uow, count_id, body))


def create_pick_list(uow: UnitOfWork, body: PickListCreate) -> PickListRead:
    return picking.pick_list_read(uow, picking.create_pick_list(uow, body))


def get_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID) -> PickListRead:
    return picking.pick_list_read(uow, _get(uow, PickList, pick_list_id, "inventory.pick_list"))


def confirm_pick(uow: UnitOfWork, pick_list_id: uuid.UUID, body: PickConfirm) -> PickListRead:
    return picking.pick_list_read(uow, picking.confirm_pick(uow, pick_list_id, body))


def challan_from_pick_list(uow: UnitOfWork, pick_list_id: uuid.UUID) -> PickListRead:
    picking.challan_from_pick_list(uow, pick_list_id)
    return picking.pick_list_read(uow, _get(uow, PickList, pick_list_id, "inventory.pick_list"))


def pick_list_action(uow: UnitOfWork, pick_list_id: uuid.UUID, action: str, body: Versioned) -> PickListRead:
    fn = {"release": picking.release_pick_list, "cancel": picking.cancel_pick_list}[action]
    return picking.pick_list_read(uow, fn(uow, pick_list_id, body))
