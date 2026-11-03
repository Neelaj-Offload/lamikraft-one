"""Source readers for tasks, briefings and the agent: ``inventory.shortage`` and ``inventory.pick_list``.

Facts are display strings (product key, warehouse code, quantities as strings in the stock unit, cause labels);
visibility is the warehouse's (an invisible warehouse reads as ``None``)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.inventory.models import PickList, ShortageState
from app.modules.inventory.policies import READ, can_on_warehouse
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork


def read_shortage_facts(uow: UnitOfWork, shortage_id: uuid.UUID) -> SourceFacts | None:
    from app.modules.inventory.reads import _cause_labels, product_refs, warehouse_refs

    s = uow.session.scalars(
        select(ShortageState).where(
            ShortageState.company_id == uow.actor.company_id, ShortageState.id == shortage_id
        )
    ).first()
    if s is None or not can_on_warehouse(uow, s.warehouse_id, READ):
        return None
    product = product_refs(uow, [s.product_id])[s.product_id]
    wh = warehouse_refs(uow, [s.warehouse_id])[s.warehouse_id]
    from app.modules.inventory.models import Warehouse

    branch = uow.session.scalar(select(Warehouse.branch_id).where(Warehouse.id == s.warehouse_id))
    causes = _cause_labels(uow, list(s.caused_by or []))
    return SourceFacts(
        source_type="inventory.shortage",
        source_id=s.id,
        version=s.version,
        label=f"{product.product_key} at {wh.code}",
        status=s.status,
        owner_user_id=None,
        branch_id=branch,
        required_permission=READ,
        canonical_path=f"/operations/inventory?warehouse={wh.id}&short=1",
        is_closed=s.status != "open",
        updated_at=s.updated_at,
        facts={
            "product_key": product.product_key,
            "product_name": product.name,
            "warehouse_code": wh.code,
            "shortfall": format(s.shortfall_qty.normalize(), "f"),
            "unit": product.stock_unit,
            "caused_by": [{"type": c.type, "id": str(c.id), "label": c.label} for c in causes],
        },
    )


def read_pick_list_facts(uow: UnitOfWork, pick_list_id: uuid.UUID) -> SourceFacts | None:
    from app.modules.orders.models import SalesOrder

    pl = uow.session.scalars(
        select(PickList).where(PickList.company_id == uow.actor.company_id, PickList.id == pick_list_id)
    ).first()
    if pl is None or not can_on_warehouse(uow, pl.warehouse_id, READ):
        return None
    order_number = uow.session.scalar(select(SalesOrder.order_number).where(SalesOrder.id == pl.order_id))
    return SourceFacts(
        source_type="inventory.pick_list",
        source_id=pl.id,
        version=pl.version,
        label=f"{pl.number} · {order_number}",
        status=pl.status,
        owner_user_id=pl.assignee_user_id,
        branch_id=pl.branch_id,
        required_permission=READ,
        canonical_path=f"/operations/inventory/pick-lists/{pl.id}",
        is_closed=pl.status in ("picked", "cancelled"),
        updated_at=pl.updated_at,
        facts={
            "pick_list_number": pl.number,
            "order_number": order_number,
            "released_at": pl.released_at.isoformat() if pl.released_at else None,
        },
    )


READERS = {"inventory.shortage": read_shortage_facts, "inventory.pick_list": read_pick_list_facts}
