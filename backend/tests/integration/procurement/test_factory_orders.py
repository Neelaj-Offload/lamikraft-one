"""Factory orders as stock work in progress (module 4): open PO lines for finished products feed "on order".

Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.inventory import categories
from app.modules.procurement.factory import factory_orders, on_order
from app.seed.world import keys
from tests.integration.procurement.world import PqlWorld

pytestmark = pytest.mark.db
SAHIL, RAVI = keys.USERS.SAHIL, keys.USERS.RAVI


def test_issued_po_is_factory_wip_and_on_order(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.issued_po(("OAK_TRAY", "50", "300"), expected=date(2026, 11, 20))
    lines = factory_orders(w.actor(SAHIL), product_id=w.ref("OAK_TRAY"))
    mine = [ln for ln in lines.items if ln.purchase_order_id == po_id]
    assert len(mine) == 1 and Decimal(mine[0].outstanding) == Decimal(50) and mine[0].status == "issued"
    with w.system() as uow:
        assert on_order(uow, [w.ref("OAK_TRAY")])[(w.ref("OAK_TRAY"), w.warehouse_id)] >= Decimal(50)
    page = categories.stock_by_category(w.actor(RAVI), categories.CategoryFilters(), limit=200)
    row = next(r for r in page.items if r.product_id == w.ref("OAK_TRAY") and r.warehouse_id == w.warehouse_id)
    assert Decimal(row.on_order) >= Decimal(50)
    # raw materials (the walnut board) never appear as factory WIP
    assert factory_orders(w.actor(SAHIL), product_id=w.ref("WALNUT_BOARD")).items == []
