"""Cut-plan links and offcut lots; capacity load and overloads.

- Linking CUT-2026-0001 to the board operation makes the sheet material require the plan's boards
  (``requirement_source=cut_plan``); releasing the work order releases the plan (``cutting.plan.released`` with the
  work order id); a plan backs one work order only; a stale plan refuses the release.
- A measured offcut becomes an ``offcut`` lot (dimensions, grain, parent board lot) via ``inventory.lot.measured`` and
  a posting production -> stock that never counts as available.
- Load per work centre per day from released work orders vs calendar capacity; an overloaded day emits
  ``production.capacity.overloaded`` once (recomputing an unchanged state emits nothing); exceptions change capacity.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.modules.cutting.models import Plan
from app.modules.inventory.models import Lot, StockBalance
from app.modules.production import service
from app.modules.production.capacity import refresh_overloads
from app.modules.production.schemas import CapacityExceptionIn, CutPlanLink, OffcutRecord, OperationSchedule
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld, assert_ledger_consistent

pytestmark = pytest.mark.db


def _events(w: ProdWorld, name: str) -> list[DomainEvent]:
    with w.system() as uow:
        return list(uow.session.scalars(select(DomainEvent).where(DomainEvent.company_id == w.company_id,
                                                                  DomainEvent.event_type == name).order_by(DomainEvent.seq)))


def _link(w: ProdWorld, wo, plan_id: uuid.UUID) -> object:  # noqa: ANN001
    op = next(o for o in wo.operations if o.is_board_cutting)
    with w.uow(DEEPA) as uow:
        return service.link_cut_plan(uow, wo.id, op.id, CutPlanLink(expected_version=wo.version, cut_plan_id=plan_id))


def test_cut_plan_link_sets_board_requirement_and_release_releases_the_plan(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    plan_id = w.ref(keys.CUT_PLAN_REFS.WALNUT)
    wo = w.new_wo("8")
    assert wo.materials[0].qty_required == Decimal(48)
    wo = _link(w, wo, plan_id)
    mat = wo.materials[0]
    board_op = next(o for o in wo.operations if o.is_board_cutting)
    assert board_op.cut_plan is not None and board_op.cut_plan.ready and board_op.cut_plan.boards
    assert mat.requirement_source == "cut_plan" and mat.cut_plan_id == plan_id
    assert mat.qty_required == Decimal(board_op.cut_plan.boards) and mat.qty_required_bom == Decimal(48)
    wo = w.act(wo.id, "release")
    assert not wo.is_blocked and wo.materials[0].qty_reserved == Decimal(board_op.cut_plan.boards)
    with w.system() as uow:
        assert uow.session.get(Plan, plan_id).status == "released"
    [released] = _events(w, "cutting.plan.released")
    assert released.payload["plan_id"] == str(plan_id) and released.payload["work_order_id"] == str(wo.id)
    # the plan backs one work order only
    other = w.new_wo("1")
    with pytest.raises(Conflict) as exc:
        _link(w, other, plan_id)
    assert exc.value.code == "cut_plan_linked_elsewhere"


def test_stale_cut_plan_refuses_the_release(prod_world: ProdWorld) -> None:
    w = prod_world
    plan_id = w.ref(keys.CUT_PLAN_REFS.WALNUT)
    wo = _link(w, w.new_wo("1"), plan_id)
    with w.system() as uow:
        uow.session.get(Plan, plan_id).inputs_changed_since_calc = True
        uow.flush()
    with pytest.raises(Conflict) as exc:
        w.act(wo.id, "release")
    assert exc.value.code == "cut_plan_not_ready"
    assert w.wo(wo.id).status == "draft"


def test_offcut_lot_is_measured_posted_and_never_available(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    plan_id = w.ref(keys.CUT_PLAN_REFS.WALNUT)
    wo = w.act(_link(w, w.new_wo("8"), plan_id).id, "release")
    board_op = next(o for o in wo.operations if o.is_board_cutting)
    predicted = board_op.predicted_offcuts[0] if board_op.predicted_offcuts else None
    before = w.summary("WALNUT_BOARD")
    parent = w.walnut_lot()
    with w.uow(DEEPA) as uow:
        wo = service.record_offcut(uow, wo.id, OffcutRecord(
            expected_version=wo.version, material_id=wo.materials[0].id, operation_id=board_op.id,
            length_mm=Decimal("1180"), width_mm=Decimal("610"), thickness_mm=Decimal(18), grain_axis="length",
            parent_lot_id=parent, predicted_offcut_id=predicted.id if predicted else None))
    [txn] = [t for t in wo.transactions if t.kind == "offcut"]
    with w.system() as uow:
        lot = uow.session.get(Lot, txn.lot_id)
        assert (lot.lot_kind, lot.lot_code, lot.verification_status) == ("offcut", "WO-2026-0002-OC01", "verified")
        assert (lot.length_mm, lot.width_mm, lot.thickness_mm, lot.grain_axis) == (Decimal("1180.000"), Decimal("610.000"),
                                                                                     Decimal("18.000"), "length")
        assert lot.parent_lot_id == parent and lot.product_id == w.walnut
        on_hand = uow.session.scalar(select(StockBalance.quantity).where(StockBalance.lot_id == lot.id))
        assert Decimal(on_hand) == Decimal(1)
    measured = _events(w, "inventory.lot.measured")
    assert measured[-1].payload == {"lot_id": str(txn.lot_id), "lot_kind": "offcut", "origin": "user"}
    assert w.summary("WALNUT_BOARD") == before  # offcut lots never count as available stock
    assert_ledger_consistent(w)


def test_capacity_load_overload_once_and_exceptions(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    day = w.d(1)
    # 8 sets: assembly 320 min on 2 benches (1080 min/day) fits; 30 sets: 1200 min > 1080 -> overloaded
    wo = w.act(w.new_wo("30", planned_start_date=day).id, "release")
    with w.uow(DEEPA) as uow:
        cap = service.capacity(uow, day, day)
    rows = {r.work_center.code: r.days[0] for r in cap.rows}
    assert rows["ASSEMBLY"].capacity_minutes == Decimal("1080.0000") and rows["ASSEMBLY"].load_minutes == Decimal(1200)
    assert rows["ASSEMBLY"].overloaded and "WO-2026-0002" in rows["ASSEMBLY"].work_orders
    assert rows["PANEL-SAW"].load_minutes == Decimal(570) and rows["PANEL-SAW"].overloaded  # 459 min available
    overloads = _events(w, "production.capacity.overloaded")
    assert {e.payload["date"] for e in overloads} == {day.isoformat()} and len(overloads) == 3
    with w.system() as uow:
        refresh_overloads(uow, [(w.ref(keys.WORK_CENTER_REFS.ASSEMBLY), day)])
    assert len(_events(w, "production.capacity.overloaded")) == 3  # unchanged state: nothing new
    # overtime on assembly that day: no longer overloaded; moving the saw operation to the next day clears the saw
    with w.uow(DEEPA) as uow:
        service.set_capacity_exception(uow, w.ref(keys.WORK_CENTER_REFS.ASSEMBLY),
                                       CapacityExceptionIn(exception_date=day, available_minutes=1300, reason="overtime"))
        saw_op = next(o for o in wo.operations if o.seq == 10)
        service.schedule_operation(uow, wo.id, saw_op.id, OperationSchedule(expected_version=wo.version, planned_date=w.d(2)))
        cap = service.capacity(uow, day, w.d(2))
    rows = {r.work_center.code: r for r in cap.rows}
    assert not rows["ASSEMBLY"].days[0].overloaded and rows["ASSEMBLY"].days[0].exception_reason == "overtime"
    assert rows["PANEL-SAW"].days[0].load_minutes == 0 and rows["PANEL-SAW"].days[1].load_minutes == Decimal(570)
    # Sunday after D0 (Mon 2026-10-12): no capacity on the default Mon-Sat calendar
    with w.uow(DEEPA) as uow:
        sunday = service.capacity(uow, w.d(6), w.d(6)).rows[0].days[0]
    assert sunday.day_type == "non_working" and sunday.capacity_minutes == 0
