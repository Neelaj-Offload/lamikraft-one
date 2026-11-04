"""Slice-4 briefing families through the real ``tasks.rules`` consumer: ``ops.shortages`` (one issue per short product
and warehouse, its causes grouped as members, an operations task until resolved), ``ops.picking`` (a task for the
picker while a pick list is released) and ``admin.stock_integrity`` (the nightly projection check)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.modules.inventory import integrity, picking
from app.modules.inventory.models import PickList
from app.modules.inventory.schemas import PickConfirm, PickEntry, PickListCreate, Versioned
from app.modules.tasks.models import Issue, IssueMember, Task
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld

pytestmark = pytest.mark.db
MEERA, NEHA, RAVI, KABIR = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.RAVI, keys.USERS.KABIR


def _issues(w: InvWorld, family: str) -> list[Issue]:
    with w.system() as uow:
        return list(uow.session.scalars(select(Issue).where(Issue.company_id == w.company_id, Issue.family == family).order_by(Issue.created_at)))


def _open_tasks(w: InvWorld, issue: Issue) -> list[Task]:
    with w.system() as uow:
        return list(uow.session.scalars(select(Task).where(Task.issue_id == issue.id, Task.state.in_(["open", "in_progress"]))))


def test_shortage_issue_groups_causes_and_resolves(inv_world: InvWorld) -> None:
    w = inv_world
    first = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("MAPLE_TRIVET", "600")))
    second = w.order(MEERA, w.won_quote(MEERA, "BERG", ("MAPLE_TRIVET", "600")))
    w.reserve(MEERA, first)  # 300 granted, 300 short; the second order has 600 unreserved
    w.drain()
    [issue] = _issues(w, "ops.shortages")
    assert issue.state == "open" and issue.title == f"Short of {keys.PRODUCTS.MAPLE_TRIVET} at {keys.WAREHOUSES.MAIN}"
    with w.system() as uow:
        members = {m.ref_type: m for m in uow.session.scalars(select(IssueMember).where(IssueMember.issue_id == issue.id, IssueMember.active.is_(True)))}
        order_members = list(uow.session.scalars(select(IssueMember.ref_id).where(IssueMember.issue_id == issue.id, IssueMember.ref_type == "orders.sales_order")))
    assert "inventory.shortage" in members and set(order_members) == {first, second}  # root cause grouped: both demands
    [task] = _open_tasks(w, issue)
    assert task.queue_code == "operations" and task.completion_check == "shortage_resolved"
    # both orders cancelled: the shortage resolves and the task closes
    w.transition_order(MEERA, first, "cancel", reason_code="customer_cancelled")
    w.transition_order(MEERA, second, "cancel", reason_code="customer_cancelled")
    w.drain()
    [issue] = _issues(w, "ops.shortages")
    assert issue.state != "open" and _open_tasks(w, issue) == []
    assert len(_issues(w, "ops.shortages")) == 1  # replays and re-derivations never open a second issue


def test_released_pick_list_is_a_picking_task_until_picked(inv_world: InvWorld) -> None:
    w = inv_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    w.reserve(MEERA, order_id)
    with w.uow(RAVI) as uow:
        pl = picking.create_pick_list(uow, PickListCreate(order_id=order_id, assignee_user_id=w.ref(KABIR)))
        pid, version = pl.id, pl.version
    with w.uow(RAVI) as uow:
        picking.release_pick_list(uow, pid, Versioned(expected_version=version))
    w.drain()
    [issue] = _issues(w, "ops.picking")
    [task] = _open_tasks(w, issue)
    assert task.assignee_user_id == w.ref(KABIR) and task.title.startswith("Pick PL-2026-")
    with w.system() as uow:
        version = uow.session.get(PickList, pid).version  # type: ignore[union-attr]
    with w.uow(KABIR) as uow:
        read = picking.pick_list_read(uow, uow.session.get(PickList, pid))  # type: ignore[arg-type]
        picking.confirm_pick(uow, pid, PickConfirm(expected_version=version, entries=[PickEntry(line_id=read.lines[0].id, picked_quantity=Decimal(240))]))
    w.drain()
    [issue] = _issues(w, "ops.picking")
    assert _open_tasks(w, issue) == []


def test_projection_mismatch_becomes_an_integrity_issue(inv_world: InvWorld) -> None:
    w = inv_world
    with w.system() as uow:
        assert integrity.detect_mismatches(uow) == 0
        uow.session.execute(text("UPDATE inventory_stock_balance SET quantity = quantity + 1 WHERE company_id = :c AND quantity > 0 "
                                 "AND product_id = :p"), {"c": w.company_id, "p": w.ref("OAK_TRAY")})
    with w.system() as uow:
        found = integrity.check(uow)
        assert {m.kind for m in found} == {"balance", "summary_available"}
        assert integrity.detect_mismatches(uow) == 1
    w.drain()
    [issue] = _issues(w, "admin.stock_integrity")
    [task] = _open_tasks(w, issue)
    assert task.queue_code == "admin" and "LK-OT-0450" in task.title
