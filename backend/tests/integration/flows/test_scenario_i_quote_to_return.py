"""Scenario I end to end (PLAN Slice 4 exit; operations.md §14): an approved opening batch, a won quote converted
once, competing reservations without oversell, a partial challan with exactly one movement, a customer return linked
to the original line, a second challan cancelled with an auditable reversal, and the ledger consistent throughout."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules.challans.schemas import (
    ChallanCreate,
    ChallanLineCreate,
    ChallanType,
    DestinationType,
    LineType,
)
from app.modules.inventory.models import StockMovement, StockPosting
from app.modules.orders import service as orders
from app.modules.orders.schemas import ChallanFromOrder
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
MEERA, NEHA, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.RAVI


def test_end_to_end(inv_world: InvWorld) -> None:
    w = inv_world
    assert w.summary("OAK_TRAY") == (Decimal(600), Decimal(0))  # the approved opening batch
    assert_ledger_consistent(w)

    # 1. accept once: a won quote converts to exactly one order (a retry returns the same order)
    quote_id = w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with w.uow(MEERA) as uow:
        order, created = orders.convert_quote(uow, quote_id)
        order_id = order.id
    with w.uow(MEERA) as uow:
        again, created_again = orders.convert_quote(uow, quote_id)
    assert created and not created_again and again.id == order_id
    d = w.get_order(MEERA, order_id)
    assert d.order_number.startswith("SO-2026-") and d.total is not None and d.total.amount == Decimal("5760.0000")
    w.transition_order(MEERA, order_id, "confirm")

    # 2. competing reservations: a second order wants 500 of the remaining 360 -> partial grant, shortfall emitted
    r1 = w.reserve(MEERA, order_id)
    assert [(o.granted, o.shortfall) for o in r1.outcomes] == [(Decimal(240), Decimal(0))]
    other = w.order(NEHA, w.won_quote(NEHA, "THORNBURY", ("OAK_TRAY", "500")))
    r2 = w.reserve(NEHA, other)
    assert [(o.granted, o.shortfall) for o in r2.outcomes] == [(Decimal(360), Decimal(140))]
    assert w.summary("OAK_TRAY") == (Decimal(600), Decimal(600))
    assert_ledger_consistent(w)

    # 3. a partial challan: 100 of the 240; issue posts exactly one movement and records the delivery
    with w.uow(RAVI) as uow:
        challan_id = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={d.lines[0].id: Decimal(100)}))
    issued = w.transition_challan(RAVI, challan_id, "issue")
    assert issued.inventory_effect == "posting" and issued.issue_posting_id is not None
    assert w.postings("challan", challan_id) == 1
    line = w.get_order(MEERA, order_id).lines[0]
    assert (line.qty_delivered, line.qty_remaining, line.qty_reserved) == (Decimal(100), Decimal(140), Decimal(140))
    assert w.summary("OAK_TRAY") == (Decimal(500), Decimal(500))
    assert_ledger_consistent(w)

    # 4. a partial customer return linked to the original line (excess refused)
    out_line = issued.lines[0]
    with w.uow(RAVI) as uow:
        from app.modules.challans import service as challans

        with pytest.raises(ValidationFailed):
            challans.create_challan(uow, ChallanCreate(
                challan_type=ChallanType.RETURN, destination_type=DestinationType.CUSTOMER, original_challan_id=challan_id,
                lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("OAK_TRAY"), quantity=Decimal(101), original_line_id=out_line.id)]))
    with w.uow(RAVI) as uow:
        ret = challans.create_challan(uow, ChallanCreate(
            challan_type=ChallanType.RETURN, destination_type=DestinationType.CUSTOMER, original_challan_id=challan_id,
            lines=[ChallanLineCreate(line_type=LineType.CATALOG, product_id=w.ref("OAK_TRAY"), quantity=Decimal(10), original_line_id=out_line.id)]))
        ret_id = ret.id
    returned = w.transition_challan(RAVI, ret_id, "issue")
    assert returned.inventory_effect == "posting" and len(returned.return_links) == 1
    assert w.get_order(MEERA, order_id).lines[0].qty_returned == Decimal(10)
    assert w.summary("OAK_TRAY")[0] == Decimal(510)  # back in STOCK (OAK_TRAY is not QC-required)
    with w.system() as uow:
        moves = list(uow.session.scalars(select(StockMovement).join(StockPosting).where(StockPosting.source_id == ret_id)))
        assert len(moves) == 1 and moves[0].source_line_id == returned.lines[0].id

    # 5. a second challan, cancelled after issue: a reversal posting restores stock and the order line
    with w.uow(RAVI) as uow:
        second = orders.create_challan_for_order(uow, order_id, ChallanFromOrder(quantities={d.lines[0].id: Decimal(40)}))
    w.transition_challan(RAVI, second, "issue")
    assert w.get_order(MEERA, order_id).lines[0].qty_delivered == Decimal(140)
    cancelled = w.transition_challan(RAVI, second, "cancel", reason_code="wrong_items", reason="Wrong pallet loaded")
    assert cancelled.status == "cancelled" and cancelled.reversal_posting_id is not None
    with w.system() as uow:
        rev = uow.session.get(StockPosting, cancelled.reversal_posting_id)
        assert rev is not None and rev.reverses_posting_id == cancelled.issue_posting_id and rev.reason == "Wrong pallet loaded"
    assert w.get_order(MEERA, order_id).lines[0].qty_delivered == Decimal(100)
    assert cancelled.history[-1].reason_code == "wrong_items" and cancelled.history[-1].actor is not None
    assert w.summary("OAK_TRAY")[0] == Decimal(510)
    assert_ledger_consistent(w)
