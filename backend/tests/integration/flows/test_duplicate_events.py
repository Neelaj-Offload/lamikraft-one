"""SCN-I4: replayed outbox events have a single effect. Every Slice-4-relevant event already processed is delivered
again to every subscribed consumer (as a crashed worker or a duplicate relay would): postings, order figures,
reservations, shortage versions, briefing issues and tasks do not change."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.inventory.models import Reservation, ShortageState, StockMovement, StockPosting
from app.modules.orders.models import SalesOrderLine
from app.modules.orders.schemas import ChallanFromOrder
from app.modules.tasks.models import Issue, Task
from app.platform.events.models import DomainEvent
from app.registry import get_registry
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
MEERA, RAVI = keys.USERS.MEERA, keys.USERS.RAVI
REPLAYED = ("challans.challan.issued", "challans.return.received", "challans.challan.cancelled", "inventory.stock.posted",
            "inventory.posting.reversed", "inventory.reservation.created", "inventory.reservation.shortfall_detected",
            "inventory.shortage.detected", "inventory.shortage.changed", "orders.sales_order.confirmed",
            "orders.sales_order_line.delivered")


def _state(w: InvWorld) -> dict[str, object]:
    with w.system() as uow:
        s = uow.session

        def count(model: type) -> int:
            return int(s.scalar(select(func.count()).select_from(model).where(model.company_id == w.company_id)) or 0)  # type: ignore[attr-defined]

        return {
            "postings": count(StockPosting), "movements": count(StockMovement), "reservations": count(Reservation),
            "issues": count(Issue), "tasks": count(Task),
            "shortage_versions": sorted(s.scalars(select(ShortageState.version).where(ShortageState.company_id == w.company_id))),
            "delivered": sorted(Decimal(x) for x in s.scalars(select(SalesOrderLine.qty_delivered).where(SalesOrderLine.company_id == w.company_id))),
            "returned": sorted(Decimal(x) for x in s.scalars(select(SalesOrderLine.qty_returned).where(SalesOrderLine.company_id == w.company_id))),
        }


def test_replayed_outbox_events_have_single_effect(inv_world: InvWorld) -> None:
    from app.modules.challans import service as challans
    from app.modules.challans.schemas import (
        ChallanCreate,
        ChallanLineCreate,
        ChallanType,
        DestinationType,
        LineType,
    )
    from app.modules.orders import service as orders

    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("MAPLE_TRIVET", "600")))  # short: a shortage issue opens
    w.reserve(MEERA, order_id)
    line_id = w.get_order(MEERA, order_id).lines[0].id
    with w.uow(RAVI) as uow:
        challan_id = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={line_id: Decimal(100)}))
    issued = w.transition_challan(RAVI, challan_id, "issue")
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.CUSTOMER, original_challan_id=challan_id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("MAPLE_TRIVET"), quantity=Decimal(5), original_line_id=issued.lines[0].id)]))
        ret_id = ret.id
    w.transition_challan(RAVI, ret_id, "issue")
    with w.uow(RAVI) as uow:
        second = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={line_id: Decimal(50)}))
    w.transition_challan(RAVI, second, "issue")
    w.transition_challan(RAVI, second, "cancel", reason_code="wrong_items")
    w.drain()
    before = _state(w)
    assert before["issues"] and before["postings"]

    registry = get_registry()
    with w.system() as uow:
        events = list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                    DomainEvent.event_type.in_(REPLAYED)).order_by(DomainEvent.seq)))
    assert {e.event_type for e in events} >= {"challans.challan.issued", "inventory.stock.posted", "inventory.shortage.detected"}
    delivered = 0
    for event in events:
        for sub in registry.subscriptions.get(event.event_type, []):
            for _ in range(2):  # twice: duplicate relay plus a crashed worker's retry
                with w.system() as uow:
                    sub.handler(uow, uow.session.merge(event))
                delivered += 1
    assert delivered > 0
    w.drain()
    assert _state(w) == before
    assert_ledger_consistent(w)
