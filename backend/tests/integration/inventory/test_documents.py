"""Warehouse documents: stock counts post the variance against the freeze snapshot (later movements stay valid),
adjustments need a second person, transfers go through in-transit in two postings, pick lists post nothing and a short
pick releases the rest, and the persisted shortage state follows demand and supply."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden
from app.modules.inventory import counts, documents, picking, shortages
from app.modules.inventory import service as inventory
from app.modules.inventory.models import Adjustment, PickList, ShortageState, StockCount, Transfer
from app.modules.inventory.schemas import (
    AdjustmentCreate,
    AdjustmentLineIn,
    CountCreate,
    CountEntries,
    CountEntry,
    Decision,
    DocLineIn,
    PickConfirm,
    PickEntry,
    PickListCreate,
    RelocationCreate,
    TransferCreate,
    Versioned,
    WarehouseCreate,
)
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
RAVI, SAHIL, KABIR, MEERA, PRIYA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.KABIR, keys.USERS.MEERA, keys.USERS.PRIYA


def _version(w: InvWorld, model: type, doc_id: object) -> int:
    with w.system() as uow:
        return uow.session.get(model, doc_id).version  # type: ignore[union-attr, no-any-return]


def test_stock_count_posts_variance_against_snapshot(inv_world: InvWorld) -> None:
    w = inv_world
    with w.uow(KABIR) as uow:  # the warehouse assistant counts
        c = counts.create_count(uow, CountCreate(warehouse_id=w.warehouse_id))
        cid = c.id
    v_cid = _version(w, StockCount, cid)
    with w.uow(KABIR) as uow:
        counts.freeze_count(uow, cid, Versioned(expected_version=v_cid))
    with w.uow(KABIR) as uow:
        read = counts.count_read(uow, uow.session.get(StockCount, cid))  # type: ignore[arg-type]
    by_product = {ln.product.product_key: ln for ln in read.lines}
    assert by_product[keys.PRODUCTS.OAK_TRAY].system_quantity == Decimal(600) and read.snapshot_seq
    # stock moves after the freeze: a relocation inside the counted area keeps the variance correct
    with w.system() as uow:
        stock = inventory.default_location(uow, w.warehouse_id).id
    with w.uow(RAVI) as uow:
        documents.relocate(uow, RelocationCreate(product_id=w.ref("MAPLE_TRIVET"), from_location_id=stock,
                                                 to_location_id=w.ref(keys.WAREHOUSE_REFS.BIN_A12), quantity=Decimal(5), unit="pcs"))
    entries = [CountEntry(line_id=ln.id, counted_quantity=ln.system_quantity) for ln in read.lines]
    entries = [CountEntry(line_id=e.line_id, counted_quantity=Decimal(597) if e.line_id == by_product[keys.PRODUCTS.OAK_TRAY].id else e.counted_quantity)
               for e in entries]
    v_cid = _version(w, StockCount, cid)
    with w.uow(KABIR) as uow:
        counts.enter_counts(uow, cid, CountEntries(expected_version=v_cid, entries=entries))
    v_cid = _version(w, StockCount, cid)
    with w.uow(KABIR) as uow:
        counts.submit_count(uow, cid, Versioned(expected_version=v_cid))
    v_cid = _version(w, StockCount, cid)
    with pytest.raises(Forbidden), w.uow(KABIR) as uow:  # warehouse assistants count, operations approve
        counts.approve_count(uow, cid, Decision(expected_version=v_cid))
    v_cid = _version(w, StockCount, cid)
    with w.uow(RAVI) as uow:
        posted = counts.approve_count(uow, cid, Decision(expected_version=v_cid))
        assert posted.status == "posted" and posted.posting_id is not None
    assert w.summary("OAK_TRAY")[0] == Decimal(597) and w.summary("MAPLE_TRIVET")[0] == Decimal(300)
    assert_ledger_consistent(w)


def test_adjustment_needs_a_second_person_and_may_short_reservations(inv_world: InvWorld) -> None:
    w = inv_world
    with w.uow(RAVI) as uow:
        inventory.reserve(uow, demand_type="so_line", demand_id=__import__("uuid").uuid7(), demand_parent_id=None, demand_label="t",
                          product_id=w.ref("ASH_BOARD"), warehouse_id=w.warehouse_id, quantity=Decimal(200))
        adj = documents.create_adjustment(uow, AdjustmentCreate(warehouse_id=w.warehouse_id, reason_code="damage", reason="Water damage",
                                                                lines=[AdjustmentLineIn(product_id=w.ref("ASH_BOARD"), quantity=Decimal(5), direction="out")]))
        documents.submit_adjustment(uow, adj.id, Versioned(expected_version=adj.version))
        adj_id = adj.id
    assert adj.number.startswith("ADJ-2026-")
    v_adj_id = _version(w, Adjustment, adj_id)
    with pytest.raises(Forbidden) as exc, w.uow(RAVI) as uow:
        documents.decide_adjustment(uow, adj_id, Decision(expected_version=v_adj_id), approve=True)
    assert exc.value.code == "approver_is_creator"
    v_adj_id = _version(w, Adjustment, adj_id)
    with w.uow(SAHIL) as uow:
        documents.decide_adjustment(uow, adj_id, Decision(expected_version=v_adj_id), approve=True)
    assert w.summary("ASH_BOARD") == (Decimal(195), Decimal(200))  # an approved loss ate into reserved stock...
    with w.system() as uow:
        names = list(uow.session.scalars(select(DomainEvent.event_type).where(DomainEvent.company_id == w.company_id)))
    assert "inventory.reservation.shortfall_detected" in names and "inventory.adjustment.posted" in names  # ...never silently
    assert_ledger_consistent(w)


def test_transfer_dispatch_and_receive_through_in_transit(inv_world: InvWorld) -> None:
    w = inv_world
    with w.uow(PRIYA) as uow:
        second = documents.create_warehouse(uow, WarehouseCreate(code="WH-SEC", name="Second", branch_id=w.branch_id))
        second_id = second.id
    with w.uow(RAVI) as uow:
        tr = documents.create_transfer(uow, TransferCreate(from_warehouse_id=w.warehouse_id, to_warehouse_id=second_id,
                                                           lines=[DocLineIn(product_id=w.ref("OAK_TRAY"), quantity=Decimal(50))]))
        tid = tr.id
    v_tid = _version(w, Transfer, tid)
    with w.uow(RAVI) as uow:
        documents.dispatch_transfer(uow, tid, Versioned(expected_version=v_tid))
    assert w.summary("OAK_TRAY")[0] == Decimal(550)
    with w.uow(RAVI) as uow:
        pos = __import__("app.modules.inventory.reads", fromlist=["x"]).product_position(uow, w.ref("OAK_TRAY"))
        assert pos.in_transit == Decimal(50)
    v_tid = _version(w, Transfer, tid)
    with w.uow(RAVI) as uow:
        done = documents.receive_transfer(uow, tid, Versioned(expected_version=v_tid))
        assert done.status == "received" and done.receive_posting_id and done.dispatch_posting_id
    with w.system() as uow:
        s = inventory.summary_of(uow, w.ref("OAK_TRAY"), second_id)
        assert s is not None and s.available_on_hand == Decimal(50)
    assert_ledger_consistent(w)


def test_pick_list_posts_nothing_and_short_pick_releases_and_refreshes_shortage(inv_world: InvWorld) -> None:
    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    w.reserve(MEERA, order_id)
    before = w.postings()
    with w.uow(RAVI) as uow:
        pl = picking.create_pick_list(uow, PickListCreate(order_id=order_id, assignee_user_id=w.ref(KABIR)))
        pid = pl.id
    assert pl.number.startswith("PL-2026-")
    v_pid = _version(w, PickList, pid)
    with w.uow(RAVI) as uow:
        picking.release_pick_list(uow, pid, Versioned(expected_version=v_pid))
    with w.uow(KABIR) as uow:
        read = picking.pick_list_read(uow, uow.session.get(PickList, pid))  # type: ignore[arg-type]
        picking.confirm_pick(uow, pid, PickConfirm(expected_version=read.version, entries=[PickEntry(line_id=read.lines[0].id, picked_quantity=Decimal(200))]))
    assert w.postings() == before  # picking posts nothing
    assert w.summary("OAK_TRAY") == (Decimal(600), Decimal(200))  # the short 40 was released
    w.drain()  # inventory.shortage_refresh: 40 unreserved demand but 400 free -> no shortage
    with w.system() as uow:
        assert uow.session.scalars(select(ShortageState).where(ShortageState.status == "open")).first() is None
    with w.uow(RAVI) as uow:
        challan_id = picking.challan_from_pick_list(uow, pid)
    issued = w.transition_challan(RAVI, challan_id, "issue")
    assert issued.lines[0].quantity == Decimal(200) and w.summary("OAK_TRAY") == (Decimal(400), Decimal(0))
    assert w.get_order(MEERA, order_id).lines[0].qty_delivered == Decimal(200)
    assert_ledger_consistent(w)


def test_shortage_state_detected_changed_resolved_once_each(inv_world: InvWorld) -> None:
    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("MAPLE_TRIVET", "600")))  # 600 ordered, 300 on hand
    w.reserve(MEERA, order_id)
    w.drain()
    with w.system() as uow:
        s = uow.session.scalars(select(ShortageState).where(ShortageState.company_id == w.company_id)).one()
        assert (s.status, s.shortfall_qty, s.version) == ("open", Decimal(300), 1)
        assert s.caused_by == [{"type": "orders.sales_order_line", "id": str(w.get_order(MEERA, order_id).lines[0].id)}]
    w.drain()  # replays and re-deliveries change nothing
    with w.uow(RAVI) as uow:
        shortages.refresh(uow, w.ref("MAPLE_TRIVET"), w.warehouse_id)
    with w.system() as uow:
        assert uow.session.scalars(select(ShortageState)).one().version == 1
    w.transition_order(MEERA, order_id, "cancel", reason_code="stock_unavailable")
    w.drain()
    with w.system() as uow:
        s = uow.session.scalars(select(ShortageState).where(ShortageState.company_id == w.company_id)).one()
        assert (s.status, s.version) == ("resolved", 2)
        names = [e for e in uow.session.scalars(select(DomainEvent.event_type).where(
            DomainEvent.company_id == w.company_id, DomainEvent.event_type.like("inventory.shortage.%")).order_by(DomainEvent.seq))]
    assert names == ["inventory.shortage.detected", "inventory.shortage.resolved"]
