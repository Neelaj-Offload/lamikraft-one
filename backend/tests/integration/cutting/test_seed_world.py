"""The Slice-2 cutting fixture (fixtures.md §8): CUT-2026-0001, LK-WB-1800 walnut panels, owner Ravi, saved and
calculated at D0 08:15 through the real services; re-running the seed changes nothing."""

from __future__ import annotations

from datetime import datetime

from app.modules.cutting import service
from app.modules.cutting.schemas import PlanFilters
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.cutting import PANELS, PLAN_NUMBER, PLAN_REF, SAVED_AT, seed_cutting
from app.seed.world.parties import at_ist
from tests.integration.sales.world import SalesWorld


def test_cut_plan_fixture(world: SalesWorld) -> None:
    seed_cutting(world.ctx)
    plan_id = world.ref(PLAN_REF)
    with UnitOfWork(world.actor(keys.USERS.RAVI)) as uow:
        plan = service.get_plan(uow, plan_id)
    assert plan.plan_number == PLAN_NUMBER and plan.status == "calculated"
    assert plan.owner.id == world.user_id(keys.USERS.RAVI)
    saved: datetime = at_ist(*SAVED_AT)
    assert plan.created_at == saved and plan.latest_calculation is not None
    assert plan.latest_calculation.created_at == saved
    assert all(i.sku.startswith(keys.PRODUCTS.WALNUT_BOARD) and i.decor_key == keys.DECORS.AMERICAN_WALNUT for i in plan.items)
    totals = plan.latest_calculation.totals
    assert totals.required == sum(q for *_rest, q in PANELS) == totals.placed_required and totals.unfit == 0
    seed_cutting(world.ctx)  # idempotent
    with UnitOfWork(world.actor(keys.USERS.RAVI)) as uow:
        assert service.list_plans(uow, PlanFilters()).total == 1
