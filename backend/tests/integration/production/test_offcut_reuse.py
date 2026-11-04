"""Offcut reuse (Slice 5): cut plans consume measured offcut lots.

- Candidates are the measured offcut lots on hand in visible warehouses (with whether a plan group matches); the
  selection pins the measured size (grain along the length) and marks a calculated plan stale.
- The calculation fills the offcut before opening a standard sheet; the board is stored as ``source='offcut'`` with
  its lot, and the plan's board requirement still counts every board.
- Releasing the work order releases the plan and issues the offcut lot from its bin to the work order's WIP (one issue
  transaction, counted as issued), so only the standard sheets are reserved; the lot is no longer a candidate.
- A second plan that chose the same lot is refused at release (409 ``offcut_unavailable``) and the work order stays
  a draft.
- Scope: a lot in a warehouse the actor cannot read is never offered and selecting it is the same 422 as an unknown
  id; an invisible plan is a 404; selecting lots needs ``inventory.stock.read``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.modules.cutting import service as cutting
from app.modules.cutting.models import CalcBoard, Plan
from app.modules.cutting.schemas import PlanCommand, PlanCreate, PlanItemIn, PlanOffcutsUpdate
from app.modules.inventory import documents
from app.modules.inventory import service as inventory
from app.modules.inventory.enums import LocationType
from app.modules.inventory.models import Location, StockBalance
from app.modules.inventory.schemas import WarehouseCreate
from app.modules.production.schemas import CutPlanLink
from app.platform.org.models import Branch
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld, assert_ledger_consistent

pytestmark = pytest.mark.db
RAVI, MEERA, NEHA, ANANYA, PRIYA = (keys.USERS.RAVI, keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.ANANYA,
                                    keys.USERS.PRIYA)


def _offcut(w: ProdWorld, code: str, length: str, width: str, *, grain: str = "length",
            warehouse_id: uuid.UUID | None = None) -> uuid.UUID:
    """A measured walnut offcut lot on hand (stand-in for production's record_offcut in another work order)."""
    with w.system() as uow:
        lot_id = inventory.record_measured_lot(uow, product_id=w.walnut, lot_code=code, lot_kind="offcut",
                                               length_mm=Decimal(length), width_mm=Decimal(width),
                                               thickness_mm=Decimal(18), grain_axis=grain)
        src = inventory.company_location(uow, LocationType.PRODUCTION)
        dest = inventory.default_location(uow, warehouse_id or w.warehouse_id)
        inventory.post_movement(uow, inventory.PostingRequest(
            source_type="adjustment", source_id=uuid.uuid7(), purpose="adjust", reason="test offcut on hand",
            lines=(inventory.PostingLine(product_id=w.walnut, quantity=Decimal(1), uom_code="sheets",
                                         from_location_id=src.id, to_location_id=dest.id, lot_id=lot_id),)))
        return lot_id


def _plan(w: ProdWorld, person: str = DEEPA, name: str = "Walnut doors with an offcut") -> uuid.UUID:
    """One 1100 x 580 panel (fits the 1180 x 610 offcut) and five 720 x 560 shelves (together they need two sheets;
    with the offcut, the shelves fit one sheet)."""
    decor = keys.DECORS.AMERICAN_WALNUT
    with w.uow(person) as uow:
        plan = cutting.create_plan(uow, PlanCreate(name=name, items=[
            PlanItemIn(sku="WD-PANEL", decor=decor, thickness_mm=Decimal(18), length_mm=Decimal(1100), width_mm=Decimal(580), quantity=1),
            PlanItemIn(sku="WD-SHELF", decor=decor, thickness_mm=Decimal(18), length_mm=Decimal(720), width_mm=Decimal(560), quantity=5),
        ]))
        return plan.id


def _choose(w: ProdWorld, plan_id: uuid.UUID, lot_ids: list[uuid.UUID], person: str = DEEPA):  # type: ignore[no-untyped-def]
    with w.uow(person, idempotency_key=str(uuid.uuid7())) as uow:
        version = cutting.get_plan(uow, plan_id).version
        out, _ = cutting.replace_offcuts_command(uow, plan_id, PlanOffcutsUpdate(expected_version=version, lot_ids=lot_ids))
        return out


def _calculate(w: ProdWorld, plan_id: uuid.UUID, person: str = DEEPA):  # type: ignore[no-untyped-def]
    with w.uow(person) as uow:
        version = cutting.get_plan(uow, plan_id).version
        cutting.request_calculation(uow, plan_id, PlanCommand(expected_version=version))
        return cutting.get_plan(uow, plan_id)


def _link(w: ProdWorld, wo, plan_id: uuid.UUID):  # type: ignore[no-untyped-def]  # noqa: ANN001
    from app.modules.production import service

    op = next(o for o in wo.operations if o.is_board_cutting)
    with w.uow(DEEPA) as uow:
        return service.link_cut_plan(uow, wo.id, op.id, CutPlanLink(expected_version=wo.version, cut_plan_id=plan_id))


def _balances(w: ProdWorld, lot_id: uuid.UUID) -> dict[str, Decimal]:
    with w.system() as uow:
        rows = uow.session.execute(select(Location.location_type, StockBalance.quantity)
                                   .join(Location, Location.id == StockBalance.location_id)
                                   .where(StockBalance.lot_id == lot_id)).all()
    return {t: Decimal(q) for t, q in rows if Decimal(q) != 0 and t != "production"}  # the virtual source of the test lot


def test_plan_cuts_from_an_offcut_and_release_issues_it_to_wip(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    lot = _offcut(w, "OC-TEST-01", "610", "1180", grain="width")  # measured across: pinned 1180 x 610
    plan_id = _plan(w)
    with w.uow(DEEPA) as uow:
        cands = cutting.offcut_candidates(uow, plan_id)
    [cand] = [c for c in cands.items if c.lot_id == lot]
    assert cands.stock_visible and cand.matches_group and not cand.selected
    assert (cand.decor_key, cand.thickness_key, cand.lot_code) == (keys.DECORS.AMERICAN_WALNUT, "18", "OC-TEST-01")
    plain = _calculate(w, plan_id)
    assert plain.latest_calculation.totals.boards == 2 and plain.latest_calculation.totals.offcut_boards == 0
    chosen = _choose(w, plan_id, [lot])
    assert chosen.stale is True  # a calculated plan with a new selection must be recalculated
    [pinned] = chosen.offcuts
    assert (pinned.length_mm, pinned.width_mm, pinned.on_hand, pinned.used, pinned.matches_group) == (
        Decimal("1180"), Decimal("610"), True, False, True)
    detail = _calculate(w, plan_id)
    calc = detail.latest_calculation
    assert calc.totals.boards == 2 and calc.totals.offcut_boards == 1, [
        (b.source, b.raw_length_mm, b.raw_width_mm, [p.sku for p in b.placements]) for g in calc.groups for b in g.boards]
    boards = calc.groups[0].boards
    assert [(b.source, b.lot_id, b.lot_code) for b in boards] == [("offcut", lot, "OC-TEST-01"), ("standard", None, None)]
    assert boards[0].margin_mm == Decimal(0) and [p.sku for p in boards[0].placements] == ["WD-PANEL"]
    assert detail.offcuts[0].used is True
    with w.system() as uow:
        assert uow.session.scalar(select(CalcBoard.lot_id).where(CalcBoard.calculation_id == calc.id,
                                                                 CalcBoard.source == "offcut")) == lot
    # recalculating the same inputs gives the same result
    assert _calculate(w, plan_id).latest_calculation.result_hash == calc.result_hash

    wo = _link(w, w.new_wo("1"), plan_id)
    assert wo.materials[0].qty_required == Decimal(2)  # every board of the plan
    before_free = w.summary("WALNUT_BOARD")
    wo = w.act(wo.id, "release")
    mat = wo.materials[0]
    assert (mat.qty_issued, mat.qty_reserved, mat.qty_to_issue) == (Decimal(1), Decimal(1), Decimal(1))
    [issue] = [t for t in wo.transactions if t.kind == "issue"]
    assert [(ln.lot_code, ln.quantity, ln.to_location) for ln in issue.lines] == [("OC-TEST-01", Decimal(1), "WIP")]
    assert _balances(w, lot) == {"wip": Decimal(1)}
    with w.system() as uow:
        assert uow.session.get(Plan, plan_id).status == "released"
    assert w.summary("WALNUT_BOARD")[0] == before_free[0]  # offcut lots never count as available stock
    with w.uow(DEEPA) as uow:
        assert all(c.lot_id != lot for c in cutting.offcut_candidates(uow, plan_id).items)
        assert inventory.offcut_lots(uow, lot_ids=[lot]) == []
    assert_ledger_consistent(w)


def test_a_lot_taken_by_another_work_order_refuses_the_release(prod_world: ProdWorld) -> None:
    w = prod_world
    w.cancel_seed_wo()
    lot = _offcut(w, "OC-TEST-02", "1180", "610")
    first, second = _plan(w, name="First"), _plan(w, name="Second")
    for plan_id in (first, second):
        _choose(w, plan_id, [lot])
        _calculate(w, plan_id)
    with w.uow(DEEPA) as uow:
        [cand] = [c for c in cutting.offcut_candidates(uow, first).items if c.lot_id == lot]
        second_number = cutting.get_plan(uow, second).plan_number
    assert cand.selected and cand.other_plans == [second_number]
    w.act(_link(w, w.new_wo("1"), first).id, "release")
    late = _link(w, w.new_wo("1"), second)
    with pytest.raises(Conflict) as exc:
        w.act(late.id, "release")
    assert exc.value.code == "offcut_unavailable" and exc.value.extra["lots"] == ["OC-TEST-02"]
    assert w.wo(late.id).status == "draft"
    with w.system() as uow:
        assert uow.session.get(Plan, second).status == "calculated"  # the refused release rolled back
    with w.uow(DEEPA) as uow:
        assert cutting.get_plan(uow, second).offcuts[0].on_hand is False


def test_selection_validation_and_replay(prod_world: ProdWorld) -> None:
    w = prod_world
    lot = _offcut(w, "OC-TEST-03", "800", "400")
    plan_id = _plan(w)
    for bad in ([uuid.uuid7()], [w.walnut_lot()]):  # unknown id; a standard board lot
        with pytest.raises(ValidationFailed) as exc:
            _choose(w, plan_id, bad)
        assert exc.value.extra["errors"][0]["code"] == "offcut_not_available"
    with pytest.raises(ValidationFailed) as exc:
        _choose(w, plan_id, [lot, lot])
    assert exc.value.extra["errors"][0]["code"] == "duplicate_lot"
    with w.uow(DEEPA, idempotency_key="offcut-replay") as uow:
        version = cutting.get_plan(uow, plan_id).version
        body = PlanOffcutsUpdate(expected_version=version, lot_ids=[lot])
        first, replayed = cutting.replace_offcuts_command(uow, plan_id, body)
    with w.uow(DEEPA, idempotency_key="offcut-replay") as uow:
        again, replayed_again = cutting.replace_offcuts_command(uow, plan_id, body)
    assert (replayed, replayed_again, again.version) == (False, True, first.version)
    assert [o.lot_id for o in first.offcuts] == [lot] and first.stale is False  # never calculated: nothing stale
    cleared = _choose(w, plan_id, [])
    assert cleared.offcuts == []
    # a duplicated plan keeps the selection (an input); availability is checked again at release
    _choose(w, plan_id, [lot])
    with w.uow(DEEPA) as uow:
        copy = cutting.duplicate_plan(uow, plan_id)
        assert [o.lot_id for o in cutting.get_plan(uow, copy.id).offcuts] == [lot]


def test_offcut_scope_warehouses_plans_and_permissions(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.system() as uow:
        fac = Branch(id=uuid.uuid7(), company_id=w.company_id, branch_code="FAC", name="Factory")
        uow.add(fac)
        fac_id = fac.id
    with w.uow(PRIYA) as uow:
        wh_fac = documents.create_warehouse(uow, WarehouseCreate(code="WH-FAC", name="Factory store", branch_id=fac_id)).id
    hidden = _offcut(w, "OC-FAC-01", "1180", "610", warehouse_id=wh_fac)
    visible = _offcut(w, "OC-HO-01", "1180", "610")
    plan_id = _plan(w)
    # Deepa's stock keys are HO-branch scoped: the factory lot is never offered and is one 422 when named
    with w.uow(DEEPA) as uow:
        offered = {c.lot_id for c in cutting.offcut_candidates(uow, plan_id).items}
    assert visible in offered and hidden not in offered
    with pytest.raises(ValidationFailed) as exc:
        _choose(w, plan_id, [hidden])
    assert exc.value.extra["errors"][0]["code"] == "offcut_not_available"
    # Meera's own plan: sales reads stock company-wide; Neha (sales, own) cannot see Meera's plan
    mine = _plan(w, person=MEERA, name="Meera's plan")
    with w.uow(MEERA) as uow:
        assert {visible, hidden} <= {c.lot_id for c in cutting.offcut_candidates(uow, mine).items}
    for call in (lambda uow: cutting.offcut_candidates(uow, mine),
                 lambda uow: cutting.replace_offcuts_command(uow, mine, PlanOffcutsUpdate(expected_version=1, lot_ids=[]))):
        with pytest.raises(NotFound), w.uow(NEHA, idempotency_key=str(uuid.uuid7())) as uow:
            call(uow)
    # operations (Ravi, HO) reads the HO lot for a plan in its scope
    with w.uow(RAVI) as uow:
        assert visible in {c.lot_id for c in cutting.offcut_candidates(uow, plan_id).items}
    # finance holds no cutting keys at all
    with pytest.raises((Forbidden, NotFound)), w.uow(ANANYA) as uow:
        cutting.offcut_candidates(uow, plan_id)
    # without stock read the candidates are empty and choosing lots is forbidden
    no_stock = w.actor(DEEPA)
    perms = {k: v for k, v in no_stock.permissions.items() if k != "inventory.stock.read"}
    w.actors["DEEPA_NO_STOCK"] = no_stock.with_(permissions=perms)
    with w.uow("DEEPA_NO_STOCK") as uow:
        empty = cutting.offcut_candidates(uow, plan_id)
    assert (empty.items, empty.stock_visible) == ([], False)
    with pytest.raises(Forbidden):
        _choose(w, plan_id, [visible], person="DEEPA_NO_STOCK")
