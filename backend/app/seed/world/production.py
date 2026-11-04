"""Production fixtures (fixtures.md §8, Slice 4), created through the real services in registry order after the
inventory world (60):

- the walnut board LK-WB-1800 gets a cost of record (INR 2,450.0000 per sheet, effective D-30, Deepa);
- the finished product LK-WP-0001 "Walnut cabinet panel set" (Priya, stock-tracked, unit ``set``);
- work centres PANEL-SAW (1 saw, 85 %, INR 1,200/h), EDGE-BAND (1, 90 %, INR 900/h) and ASSEMBLY (2 benches,
  100 %, no rate yet: the cost rollup is honestly incomplete) on the company calendar (Deepa, D-5);
- BOM v1 (6 sheets of LK-WB-1800 per set, sheet material) and routing v1 (cut panels on the saw as the board
  operation, edge banding, assembly) authored by Deepa and approved by Sahil (never the author);
- WO-2026-0001 for 8 sets at WH-MAIN, planned for D0, due D0+5, released by Deepa at D0 08:25: it needs 48 sheets,
  40 are on hand, so 40 are reserved and the work order is **blocked** by the LK-WB-1800 shortage.
Re-running is idempotent (lookups by code, product and number).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import CREATOR, as_member, at_ist

PRODUCT_KEY = keys.PRODUCTION_PRODUCTS.WALNUT_PANEL_SET
DEEPA = "DEEPA"


def _ensure_product(ctx: SeedContext) -> None:
    from app.modules.catalogue import service as catalogue
    from app.modules.catalogue.schemas import ProductCreate, SpecificationIn
    from app.seed.world.inventory import make_stock_tracked

    ctx.at(at_ist(-6, 10, 0))
    with as_member(ctx, CREATOR) as uow:
        existing = catalogue.find_product_id(uow, PRODUCT_KEY)
        if existing is None:
            result = catalogue.create_product(uow, ProductCreate(
                product_key=PRODUCT_KEY, display_sku=PRODUCT_KEY,
                product_name=keys.PRODUCTION_PRODUCT_NAMES["WALNUT_PANEL_SET"],
                brand=keys.BRAND_NAMES[keys.BRANDS.LK], category_id=ctx.ref(keys.CATEGORIES.DECORATIVE_BOARDS),
                subcategory_id=ctx.ref(keys.SUBCATEGORIES.VENEERED_PANELS), unit_of_sale="set",  # type: ignore[arg-type]
                decor_no=keys.DECORS.AMERICAN_WALNUT, decor_name=keys.DECOR_NAMES[keys.DECORS.AMERICAN_WALNUT],
                status="active", stock_uom_code="set",  # type: ignore[arg-type]
                specification=SpecificationIn(thickness_mm="18"), origin="seed",  # type: ignore[arg-type]
            ))
            existing = result.product.id
        make_stock_tracked(uow, [existing])
    ctx.refs["WALNUT_PANEL_SET"] = existing


def _cost(ctx: SeedContext) -> None:
    from app.modules.pricing import service as pricing
    from app.modules.pricing.models import ProductCost
    from app.modules.pricing.schemas import ProductCostCreate

    ctx.at(at_ist(-5, 9, 0))
    with as_member(ctx, DEEPA) as uow:
        found = uow.session.scalar(select(ProductCost.id).where(ProductCost.company_id == ctx.company_id,
                                                               ProductCost.product_id == ctx.ref("WALNUT_BOARD")))
        if found is None:
            pricing.record_product_cost(uow, ctx.ref("WALNUT_BOARD"), ProductCostCreate(
                unit_cost_amount=Decimal(keys.WALNUT_BOARD_COST), unit_cost_currency="INR", unit_code="sheets",  # type: ignore[arg-type]
                effective_from=(at_ist(-30, 9, 0)).date(), source_ref="Kaveri price list 2026-09", notes="seed",
            ), origin="seed")


def _work_centers(ctx: SeedContext) -> None:
    from app.core.money import Money
    from app.modules.production.masters import create_work_center
    from app.modules.production.models import WorkCenter
    from app.modules.production.schemas import WorkCenterCreate

    specs = (
        ("PANEL_SAW", "Panel saw", 1, "85", "1200"),
        ("EDGE_BAND", "Edge bander", 1, "90", "900"),
        ("ASSEMBLY", "Assembly benches", 2, "100", None),
    )
    ctx.at(at_ist(-5, 9, 30))
    with as_member(ctx, DEEPA) as uow:
        for attr, name, machines, eff, rate in specs:
            code = getattr(keys.WORK_CENTERS, attr)
            wc = uow.session.scalars(select(WorkCenter).where(WorkCenter.company_id == ctx.company_id,
                                                              WorkCenter.code == code)).first()
            if wc is None:
                wc = create_work_center(uow, WorkCenterCreate(
                    code=code, name=name, machine_count=machines, efficiency_pct=Decimal(eff),
                    rate_per_hour=Money(amount=Decimal(rate), currency="INR") if rate else None))
            ctx.refs[getattr(keys.WORK_CENTER_REFS, attr)] = wc.id


def _masters(ctx: SeedContext) -> None:
    from app.modules.production import masters
    from app.modules.production.schemas import (
        BomCreate,
        BomLineIn,
        MasterCommand,
        RoutingCreate,
        RoutingOperationIn,
    )

    product_id = ctx.ref("WALNUT_PANEL_SET")
    wc = keys.WORK_CENTER_REFS
    ctx.at(at_ist(-5, 10, 0))
    with as_member(ctx, DEEPA) as uow:
        bom = masters.approved_bom(uow, product_id)
        routing = masters.approved_routing(uow, product_id)
        draft_bom = draft_routing = None
        if bom is None:
            draft_bom = masters.create_bom(uow, BomCreate(product_id=product_id, notes="Panels cut from walnut boards", lines=[
                BomLineIn(component_product_id=ctx.ref("WALNUT_BOARD"), qty_per=Decimal(6), uom_code="sheets",
                          is_sheet_material=True)]))
        if routing is None:
            draft_routing = masters.create_routing(uow, RoutingCreate(product_id=product_id, operations=[
                RoutingOperationIn(seq=10, name="Cut panels", work_center_id=ctx.ref(wc.PANEL_SAW),
                                   setup_minutes=Decimal(30), run_minutes_per_unit=Decimal(18), is_board_cutting=True),
                RoutingOperationIn(seq=20, name="Edge band", work_center_id=ctx.ref(wc.EDGE_BAND),
                                   setup_minutes=Decimal(15), run_minutes_per_unit=Decimal(25)),
                RoutingOperationIn(seq=30, name="Assemble and pack", work_center_id=ctx.ref(wc.ASSEMBLY),
                                   run_minutes_per_unit=Decimal(40)),
            ]))
        ids = (draft_bom.id if draft_bom else None, draft_routing.id if draft_routing else None)
    ctx.at(at_ist(-5, 15, 0))
    with as_member(ctx, keys.USERS.SAHIL) as uow:
        if ids[0] is not None:
            b = masters.get_bom(uow, ids[0])
            masters.approve_bom(uow, b.id, MasterCommand(expected_version=b.version))
        if ids[1] is not None:
            r = masters.get_routing(uow, ids[1])
            masters.approve_routing(uow, r.id, MasterCommand(expected_version=r.version))
    with as_member(ctx, DEEPA) as uow:
        bom, routing = masters.approved_bom(uow, product_id), masters.approved_routing(uow, product_id)
        assert bom is not None and routing is not None
        ctx.refs[keys.PRODUCTION_REFS.BOM_PANEL_SET] = bom.id
        ctx.refs[keys.PRODUCTION_REFS.ROUTING_PANEL_SET] = routing.id


def _work_order(ctx: SeedContext) -> None:
    from app.modules.production import work_orders
    from app.modules.production.models import WorkOrder
    from app.modules.production.schemas import WorkOrderCreate, WorkOrderTransition

    ctx.at(at_ist(0, 8, 20))
    with as_member(ctx, DEEPA) as uow:
        wo = uow.session.scalars(select(WorkOrder).where(WorkOrder.company_id == ctx.company_id,
                                                         WorkOrder.wo_number == keys.WORK_ORDERS.PANEL_SETS)).first()
        if wo is None:
            d0 = at_ist(0, 8, 20).date()
            wo = work_orders.create_work_order(uow, WorkOrderCreate(
                product_id=ctx.ref("WALNUT_PANEL_SET"), quantity=Decimal(8), warehouse_id=ctx.ref(keys.WAREHOUSE_REFS.MAIN),
                planned_start_date=d0, due_date=d0 + timedelta(days=5),
                notes="Nordhaus fit-out panels; afternoon shift on the saw"))
        wo_id, status, version = wo.id, wo.status, wo.version
    ctx.refs[keys.WORK_ORDER_REFS.PANEL_SETS] = wo_id
    if status == "draft":
        ctx.at(at_ist(0, 8, 25))
        with as_member(ctx, DEEPA) as uow:
            work_orders.transition(uow, wo_id, WorkOrderTransition(action="release", expected_version=version))


def seed_production(ctx: SeedContext) -> None:
    _ensure_product(ctx)
    _cost(ctx)
    _work_centers(ctx)
    _masters(ctx)
    _work_order(ctx)
