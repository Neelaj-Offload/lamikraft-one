"""Cost rollups (determinism, missing-input flags, the redaction canary) and read-only feasibility / what-if.

Rollup of LK-WP-0001 at D0 in INR: material 6 sheets x 2,450.0000 = 14,700.0000; panel saw (30 setup / batch 1 +
18 run) min / 60 x 1,200 = 960.0000; edge band (15 + 25) / 60 x 900 = 600.0000; assembly has no hourly rate ->
missing, excluded, status ``incomplete``, total 16,260.0000 (labelled partial)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import NotFound
from app.core.money import Money
from app.modules.inventory.models import Reservation, StockMovement, StockPosting
from app.modules.production import feasibility as feas
from app.modules.production import service
from app.modules.production.common import ReadOnlyViolation, read_only
from app.modules.production.models import CostRollup, WorkCenter
from app.modules.production.schemas import (
    CapacityChange,
    CostRollupRequest,
    FeasibilityRequest,
    SimulationRequest,
    StockChange,
    WorkCenterUpdate,
)
from app.platform.audit.models import AuditLog
from app.platform.authz.redaction import redact
from app.platform.events.models import DomainEvent
from app.seed.world import keys
from tests.integration.production.world import DEEPA, ProdWorld

pytestmark = pytest.mark.db
RAVI, SAHIL, MEERA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.MEERA
INR = "INR"


def _money(v: str) -> Money:
    return Money(amount=Decimal(v), currency=INR)


def test_rollup_is_deterministic_and_lists_missing_inputs(prod_world: ProdWorld) -> None:
    w = prod_world
    req = CostRollupRequest(product_id=w.panel_set, as_of=w.d(0), currency=INR)
    with w.uow(DEEPA) as uow:
        first = service.run_cost_rollup(uow, req)
    assert first.status == "incomplete" and not first.reused
    assert [(m.kind, m.reason_code) for m in first.missing_inputs] == [("work_centre_rate", "rate_missing")]
    assert first.material_total == _money("14700.0000") and first.operation_total == _money("1560.0000")
    assert first.total == _money("16260.0000")
    assert [(ln.kind, ln.amount.amount) for ln in first.lines or []] == [
        ("material", Decimal("14700.0000")), ("operation", Decimal("960.0000")), ("operation", Decimal("600.0000"))]
    with w.uow(DEEPA) as uow:
        again = service.run_cost_rollup(uow, req)
    assert again.reused and again.id == first.id and again.input_hash == first.input_hash
    assert w.count(CostRollup) == 1
    # a new input (the assembly rate) is a new hash, a new rollup, now complete
    with w.uow(DEEPA) as uow:
        wc = service.work_center(uow, w.ref(keys.WORK_CENTER_REFS.ASSEMBLY))
        service.update_work_center(uow, wc.id, WorkCenterUpdate(expected_version=wc.version, rate_per_hour=_money("600")))
        third = service.run_cost_rollup(uow, req)
    assert third.status == "complete" and third.missing_inputs == [] and third.input_hash != first.input_hash
    assert third.total == _money("16660.0000")  # + 40 / 60 x 600
    with w.system() as uow:
        computed = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "production.cost_rollup.computed",
                                                                 DomainEvent.company_id == w.company_id)).all()
    assert [e.payload["status"] for e in computed] == ["incomplete", "complete"]
    assert all(set(e.payload) == {"rollup_id", "product_id", "status", "origin"} for e in computed)  # never a figure


def test_missing_cost_of_record_and_fx_are_listed_not_borrowed(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.uow(DEEPA) as uow:
        eur = service.run_cost_rollup(uow, CostRollupRequest(product_id=w.panel_set, as_of=w.d(0), currency="EUR"))
        early = service.run_cost_rollup(uow, CostRollupRequest(product_id=w.panel_set, as_of=w.d(-60), currency=INR))
    assert {m.reason_code for m in eur.missing_inputs} >= {"fx_rate_missing"}
    assert eur.material_total == Money(amount=Decimal(0), currency="EUR")
    assert {m.reason_code for m in early.missing_inputs} >= {"cost_missing"}  # the cost of record is effective from D-30


def test_cost_redaction_canary(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.uow(DEEPA) as uow:
        rollup = service.run_cost_rollup(uow, CostRollupRequest(product_id=w.panel_set, as_of=w.d(0)))
        # permitted users see figures, but nothing guarded ever reaches a model
        for_model = redact(service.cost_rollup(uow, rollup.id), uow.actor, for_model=True)
    assert for_model.total is None and for_model.lines is None and "total" in for_model.redacted_fields
    with w.uow(RAVI) as uow:  # operations: may see the rollup, never its figures
        seen = service.cost_rollup(uow, rollup.id)
        listed = service.cost_rollups(uow, product_id=w.panel_set).items[0]
        saw = service.work_center(uow, w.ref(keys.WORK_CENTER_REFS.PANEL_SAW))
    for view in (seen, listed):
        assert view.total is None and view.material_total is None and view.operation_total is None and view.lines is None
        assert {"total", "material_total", "operation_total", "lines"} <= set(view.redacted_fields)
        assert view.status == "incomplete" and view.missing_inputs  # status and missing inputs stay visible
    assert saw.rate_per_hour is None
    with w.uow(MEERA) as uow, pytest.raises(Exception) as exc:  # sales hold neither key
        service.cost_rollup(uow, rollup.id)
    assert getattr(exc.value, "code", None) == "permission_denied"
    # the work-order source reader (tasks, briefings, agent) carries no money at all
    from app.modules.production.readers import read_work_order_facts

    with w.uow(DEEPA) as uow:
        facts = read_work_order_facts(uow, w.wo_id)
    assert facts is not None and facts.money == [] and not any("amount" in k or "cost" in k for k in facts.facts)


def test_feasibility_evidence_from_stock_components_and_capacity(prod_world: ProdWorld) -> None:
    w = prod_world
    with w.uow(MEERA) as uow:  # sales may run feasibility
        stock = service.assess_feasibility(uow, FeasibilityRequest(product_id=w.ref("OAK_TRAY"), quantity=Decimal(100),
                                                                   need_by=w.d(3)))
    assert stock.outcome == "feasible" and stock.to_make == 0 and stock.evidence[0].kind == "stock"
    with w.uow(DEEPA) as uow:
        make = service.assess_feasibility(uow, FeasibilityRequest(product_id=w.panel_set, quantity=Decimal(2), need_by=w.d(4)))
    # all 40 walnut sheets are reserved by WO-2026-0001 and no purchase-order source is registered: an estimate
    assert make.outcome == "estimate" and "lead_time:LK-WB-1800" in make.missing_inputs
    assert [e.kind for e in make.evidence][:2] == ["stock", "components"] and make.evidence[1].status == "missing"
    # procurement's supply provider (registered by that lane) tells when more boards arrive
    po = feas.Supply(ref_type="procurement.purchase_order_line", ref_id=uuid.uuid7(), label="PO-2026-0001 line 1",
                     quantity=Decimal(20), expected_date=w.d(1), lead_time_source="vendor_item")
    feas.register_supply_provider("test.po", lambda _u, p, _w: [po] if p == w.walnut else [])
    try:
        with w.uow(DEEPA) as uow:
            ok = service.assess_feasibility(uow, FeasibilityRequest(product_id=w.panel_set, quantity=Decimal(2), need_by=w.d(4)))
            late = service.assess_feasibility(uow, FeasibilityRequest(product_id=w.panel_set, quantity=Decimal(60), need_by=w.d(4)))
    finally:
        feas._SUPPLY.pop("test.po", None)
    assert ok.outcome in ("feasible", "at_risk") and ok.earliest_completion is not None and ok.earliest_completion <= w.d(4)
    assert {e.kind for e in ok.evidence} >= {"stock", "components", "capacity"}
    assert late.outcome == "not_feasible"  # 360 sheets needed, 20 due


def test_feasibility_and_simulation_write_nothing(prod_world: ProdWorld) -> None:
    w = prod_world

    def counts() -> tuple[int, ...]:
        with w.system() as uow:
            return tuple(int(uow.session.scalar(select(func.count()).select_from(m).where(m.company_id == w.company_id)) or 0)
                         for m in (StockPosting, StockMovement, Reservation, DomainEvent, AuditLog, CostRollup))

    before = counts()
    with w.uow(DEEPA) as uow:
        service.assess_feasibility(uow, FeasibilityRequest(product_id=w.panel_set, quantity=Decimal(3), need_by=w.d(5)))
        sim = service.simulate(uow, SimulationRequest(
            checks=[FeasibilityRequest(product_id=w.panel_set, quantity=Decimal(3), need_by=w.d(5))],
            stock_changes=[StockChange(product_id=w.walnut, delta=Decimal(30))],
            capacity_changes=[CapacityChange(work_center_id=w.ref(keys.WORK_CENTER_REFS.ASSEMBLY), machine_count=4)]))
    assert counts() == before
    assert sim.simulation is True and "nothing was reserved" in sim.label
    assert sim.baseline[0].outcome == "estimate" and sim.scenario[0].outcome in ("feasible", "at_risk")
    # the guard itself: a write attempted inside the read-only block raises
    with w.uow(DEEPA) as uow:
        wc = uow.session.get(WorkCenter, w.ref(keys.WORK_CENTER_REFS.ASSEMBLY))
        with pytest.raises(ReadOnlyViolation), read_only(uow):
            wc.machine_count = 9
            uow.flush()
        uow.session.expire(wc)  # discard the refused change
        with pytest.raises(ReadOnlyViolation), read_only(uow):
            uow.add(WorkCenter(code="NEVER", name="never"))
    with w.uow(DEEPA) as uow, pytest.raises(ReadOnlyViolation), read_only(uow):
        uow.emit("production.capacity.overloaded", aggregate_id=None, payload={})


def test_order_line_feasibility_follows_order_visibility(prod_world: ProdWorld) -> None:
    w = prod_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "240")))
    line = w.get_order(MEERA, order_id).lines[0]
    with w.uow(MEERA) as uow:
        res = service.assess_order_line(uow, line.id, w.d(10))
    assert res.outcome == "feasible" and res.quantity == Decimal(240)
    with w.uow(keys.USERS.NEHA) as uow, pytest.raises(NotFound):  # another salesperson's order: never confirmed
        service.assess_order_line(uow, line.id, w.d(10))
