"""Protected costing (PERM-13, FG-CP-13, LP-05.3, Scenario E): costing lives only behind its own endpoints guarded by
``pricing.cost.read`` (reads audited); it never appears in custom-product or quote reads, lists, CSV, search, events,
or tool output for anyone, and a sales user cannot read it at all."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Forbidden
from app.modules.pricing import service as pricing
from app.modules.pricing.schemas import ProductCostCreate
from app.modules.sales import service as sales
from app.modules.sales.schemas import (
    CostingCreate,
    CustomProductCreate,
    CustomProductFilters,
    QuoteLineCreate,
)
from app.platform.audit.models import AuditLog
from app.platform.events.models import DomainEvent
from app.platform.search import service as search
from app.seed.world import keys
# The sales world's fixtures, imported here so they override security/conftest.py's identity `world` in this module.
from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.sales.world import SalesWorld, sales_world, world  # noqa: F401

pytestmark = pytest.mark.db
SENTINEL = "13.5791"
MEERA, SAHIL, PRIYA, ANANYA = keys.USERS.MEERA, keys.USERS.SAHIL, keys.USERS.PRIYA, keys.USERS.ANANYA


def test_costing_absent_without_pricing_cost_read(world: SalesWorld) -> None:
    with world.uow(MEERA) as uow:
        custom = sales.create_custom_product(uow, CustomProductCreate(product_name="Sentinel tray", quoted_price=Decimal("30"), quoted_currency="EUR"))  # type: ignore[arg-type]
    with pytest.raises(Forbidden), world.uow(MEERA) as uow:  # sales cannot write or read costing
        sales.record_costing(uow, custom.id, CostingCreate(cost_amount=Decimal(SENTINEL), cost_currency="EUR"))
    with world.uow(PRIYA) as uow:
        sales.record_costing(uow, custom.id, CostingCreate(cost_amount=Decimal(SENTINEL), cost_currency="EUR",
                                                           components=[{"label": "veneer", "amount": "9"}]))
    with world.uow(ANANYA) as uow:
        pricing.record_product_cost(uow, world.ref("OAK_TRAY"), ProductCostCreate(
            unit_cost_amount=Decimal(SENTINEL), unit_cost_currency="EUR", unit_code="pcs", effective_from=date(2026, 10, 1)))
    with pytest.raises(Forbidden), world.uow(MEERA) as uow:
        sales.list_costing(uow, custom.id)
    q = world.new_draft(MEERA, "NORDHAUS")
    with world.uow(MEERA) as uow:
        sales.add_line(uow, q.id, QuoteLineCreate(expected_version=q.version, line_type="custom", custom_product_id=custom.id, quantity=Decimal("200")))
        sales.add_line(uow, q.id, QuoteLineCreate(expected_version=q.version + 1, product_id=world.ref("OAK_TRAY"), quantity=Decimal("24")))
        surfaces = [
            sales.get_custom_product(uow, custom.id).model_dump_json(),
            sales.list_custom_products(uow, CustomProductFilters()).model_dump_json(),
            sales.export_custom_products_csv(uow, CustomProductFilters(), include_costing=True).decode("utf-8-sig"),
            sales.get_quote(uow, q.id).model_dump_json(),
            search.search(uow, "Sentinel").model_dump_json(),
            pricing.product_prices(uow, world.ref("OAK_TRAY")).model_dump_json(),
        ]
    for surface in surfaces:
        assert SENTINEL not in surface and "cost_amount" not in surface
    # management reads costing only through the guarded endpoint, and the read is audited (versions, never values)
    with world.uow(SAHIL) as uow:
        rows = sales.list_costing(uow, custom.id)
        detail = sales.get_custom_product(uow, custom.id)
        assert SENTINEL not in detail.model_dump_json() and detail.capabilities["read_costing"].allowed
    assert [format(r.cost.amount, "f") for r in rows] == [SENTINEL]
    with world.uow(SAHIL) as uow:
        audits = uow.session.scalars(select(AuditLog).where(AuditLog.action == "sales.custom_product.costing_read")).all()
        events = uow.session.scalars(select(DomainEvent.payload)).all()
    assert audits and all(SENTINEL not in json.dumps(a.details, default=str) for a in audits)
    assert all(SENTINEL not in json.dumps(p, default=str) for p in events)
