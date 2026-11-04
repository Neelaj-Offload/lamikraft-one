"""Overdue PO scheduling and the ``ops.receipts`` briefing family (receive task, overdue chase for the buyer), on the
fixture PO-2026-0001 (Kaveri, LK-WB-1800 x 60, expected date moved D0 -> D0+3 at D-1 11:03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.procurement import purchase_orders
from app.modules.procurement.jobs import JOBS, SCHEDULES, SWEEP_JOB
from app.modules.procurement.schemas import ExpectedDateChange
from app.platform.events.models import DomainEvent
from app.seed.context import D0
from app.seed.world.parties import at_ist
from tests.integration.procurement.world import PRIYA, RAVI, PqlWorld

pytestmark = pytest.mark.db


def _events(w: PqlWorld, name: str) -> list[DomainEvent]:
    with w.system() as uow:
        return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                  DomainEvent.event_type == name)
                                        .order_by(DomainEvent.seq)))


def _sweep(w: PqlWorld) -> int:
    with w.system() as uow:
        return purchase_orders.sweep_overdue(uow)


def test_fixture_po_and_expected_date_change(pql_world: PqlWorld) -> None:
    w = pql_world
    po = w.po(w.ref("PO_KAVERI"))
    [line] = w.po_lines(po.id)
    assert (po.po_number, po.status, po.vendor_name) == ("PO-2026-0001", "issued", "Kaveri Timber Supplies")
    assert line.expected_date == D0.date() + timedelta(days=3) and line.quantity == 60
    [changed] = _events(w, "procurement.purchase_order_line.expected_date_changed")
    p = changed.payload
    assert (p["purchase_order_id"], p["po_line_id"], p["from_date"], p["to_date"]) == (
        str(po.id), str(line.id), "2026-10-12", "2026-10-15")
    assert changed.occurred_at == at_ist(-1, 11, 3).astimezone(UTC)


def test_overdue_sweep_emits_once_and_again_after_the_date_moves(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.ref("PO_KAVERI")
    assert SWEEP_JOB in {j.kind for j in JOBS} and SCHEDULES[0].interval_seconds == 300
    assert _sweep(w) == 0  # D0: expected D0+3, not late
    w.at(at_ist(4, 10, 0))  # Friday D0+4
    assert _sweep(w) == 1
    assert _sweep(w) == 0  # idempotent: the line is stamped
    [overdue] = _events(w, "procurement.purchase_order.became_overdue")
    assert overdue.payload["po_line_ids"] == [str(w.po_lines(po_id)[0].id)]
    line = w.po_lines(po_id)[0]
    with w.uow(PRIYA) as uow:
        purchase_orders.change_expected_date(uow, po_id, line.id, ExpectedDateChange(
            expected_version=line.version, expected_date=D0.date() + timedelta(days=6)))
    assert _sweep(w) == 0  # moved into the future
    w.at(at_ist(7, 9, 0))
    assert _sweep(w) == 1 and len(_events(w, "procurement.purchase_order.became_overdue")) == 2
    with w.uow(PRIYA) as uow:
        assert purchase_orders.get_purchase_order(uow, po_id).is_overdue is True
        page = purchase_orders.list_purchase_orders(uow, overdue_only=True)
    assert [p.po_number for p in page.items] == ["PO-2026-0001"]


def test_receipts_family_receive_task_and_overdue_chase(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.ref("PO_KAVERI")
    w.drain()
    [issue] = w.issues("ops.receipts")
    assert issue.title == "PO-2026-0001 from Kaveri Timber Supplies"
    [receive] = w.open_tasks(issue)
    assert receive.kind == "receive_goods" and receive.queue_code == "operations" and receive.due_kind == "soft"
    # the end of the shift on D0+3 (Thursday 15 Oct, 18:30 IST)
    assert receive.due_at == datetime(2026, 10, 15, 13, 0, tzinfo=UTC)
    # overdue: the buyer gets a hard-due chase task
    w.at(at_ist(4, 10, 0))
    _sweep(w)
    w.drain()
    [issue] = w.issues("ops.receipts")
    tasks = {t.kind: t for t in w.open_tasks(issue)}
    assert set(tasks) == {"receive_goods", "chase_vendor"}
    chase = tasks["chase_vendor"]
    assert chase.assignee_user_id == w.ref(PRIYA) and chase.due_kind == "hard"
    assert chase.title == "Chase Kaveri Timber Supplies: PO-2026-0001 line 1 is overdue"
    # received in full and inspected: both obligations close
    grn = w.receive(po_id, (1, "60", "WB-2614-B"))
    w.decide(w.inspections(grn.id)[0].id, "60", person=RAVI)
    w.drain()
    [issue] = w.issues("ops.receipts")
    assert w.open_tasks(issue) == [] and issue.state != "open"
    assert w.po(po_id).status == "received" and w.summary("WALNUT_BOARD")[0] == Decimal(100)
