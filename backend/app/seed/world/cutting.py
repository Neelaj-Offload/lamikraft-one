"""Cutting fixtures (fixtures.md §8, Slice 2): cut plan CUT-2026-0001 for LK-WB-1800 walnut panels, owned by Ravi,
saved and calculated at D0 08:15 through the real services."""

from __future__ import annotations

from decimal import Decimal

from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import as_member, at_ist

#: SeedContext.refs key of the plan and its number (keys.CUT_PLAN_REFS / keys.CUT_PLANS)
PLAN_REF = keys.CUT_PLAN_REFS.WALNUT
PLAN_NUMBER = keys.CUT_PLANS.WALNUT
PLAN_NAME = "Walnut panels for the Nordhaus fit-out"
#: (sku suffix, length mm, width mm, quantity)
PANELS = (
    ("SIDE", "720", "560", 8),
    ("SHELF", "764", "520", 12),
    ("TOP", "1200", "600", 4),
    ("DOOR", "715", "396", 8),
)
SAVED_AT = (0, 8, 15)


def seed_cutting(ctx: SeedContext) -> None:
    from app.modules.cutting import service
    from app.modules.cutting.schemas import PlanCommand, PlanCreate, PlanFilters, PlanItemIn

    ctx.at(at_ist(*SAVED_AT))
    product_key = keys.PRODUCTS.WALNUT_BOARD
    decor = keys.DECORS.AMERICAN_WALNUT
    with as_member(ctx, keys.USERS.RAVI) as uow:
        existing = service.list_plans(uow, PlanFilters(q=PLAN_NUMBER, include_archived=True))
        if existing.items:
            ctx.refs[PLAN_REF] = existing.items[0].id
            return
        plan = service.create_plan(
            uow,
            PlanCreate(
                name=PLAN_NAME,
                items=[
                    PlanItemIn(
                        sku=f"{product_key}-{suffix}", decor=decor,
                        thickness_mm=Decimal("18"), length_mm=Decimal(length), width_mm=Decimal(width), quantity=qty,
                    )
                    for suffix, length, width, qty in PANELS
                ],
            ),
        )
        service.request_calculation(uow, plan.id, PlanCommand(expected_version=plan.version))
        ctx.refs[PLAN_REF] = plan.id
