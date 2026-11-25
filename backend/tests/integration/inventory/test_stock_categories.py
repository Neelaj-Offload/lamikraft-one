"""Stock categories (module 4): one pool split into inventory, sample and exhibition stock, markets and factory WIP.

Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.inventory import categories, documents
from app.modules.inventory import service as inventory
from app.modules.inventory.models import Location, Warehouse
from app.modules.inventory.schemas import (
    Decision,
    OpeningBatchCreate,
    OpeningLineIn,
    RelocationCreate,
    Versioned,
    WarehouseCreate,
)
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld

pytestmark = pytest.mark.db
RAVI, SAHIL, PRIYA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.PRIYA


def _location(w: InvWorld, warehouse_id: object, code: str) -> Location:
    with w.system() as uow:
        loc = uow.session.scalars(select(Location).where(Location.warehouse_id == warehouse_id, Location.code == code)).one()
        uow.session.expunge(loc)
        return loc


def _row(w: InvWorld, product: str, **filters: object) -> categories.CategoryRow:
    page = categories.stock_by_category(w.actor(RAVI), categories.CategoryFilters.model_validate(filters), limit=200)
    return next(r for r in page.items if r.product_id == w.ref(product) and r.warehouse_id == w.warehouse_id)


def test_existing_warehouse_has_category_locations(inv_world: InvWorld) -> None:
    w = inv_world
    sample, exhib, stock = (_location(w, w.warehouse_id, c) for c in ("SAMPLE", "EXHIB", "STOCK"))
    assert (sample.stock_category, exhib.stock_category, stock.stock_category) == ("sample", "exhibition", "inventory")
    assert not sample.counts_available and not exhib.counts_available and stock.counts_available
    with w.system() as uow:
        wh = uow.session.get(Warehouse, w.warehouse_id)
        assert wh is not None and (wh.market, wh.country_code) == ("domestic", "IN")


def test_new_warehouse_gets_market_country_and_category_locations(inv_world: InvWorld) -> None:
    w = inv_world
    with w.uow(PRIYA, step_up=True) as uow:
        wh = documents.create_warehouse(uow, WarehouseCreate(code="WH-NL", name="Rotterdam drop-ship", market="export",
                                                             country_code="NL"))
        wh_id = wh.id
    assert (_location(w, wh_id, "SAMPLE").stock_category, _location(w, wh_id, "EXHIB").stock_category) == (
        "sample", "exhibition")
    with w.system() as uow:
        assert uow.session.get(Warehouse, wh_id).country_code == "NL"  # type: ignore[union-attr]


def test_moving_stock_between_categories_and_availability(inv_world: InvWorld) -> None:
    w = inv_world
    before = _row(w, "OAK_TRAY")
    with w.system() as uow:
        stock = inventory.default_location(uow, w.warehouse_id).id
    exhib = _location(w, w.warehouse_id, "EXHIB").id
    sample = _location(w, w.warehouse_id, "SAMPLE").id
    with w.uow(RAVI) as uow:
        documents.relocate(uow, RelocationCreate(product_id=w.ref("OAK_TRAY"), from_location_id=stock, to_location_id=exhib,
                                                 quantity=Decimal(5), unit="pcs"))
        documents.relocate(uow, RelocationCreate(product_id=w.ref("OAK_TRAY"), from_location_id=stock, to_location_id=sample,
                                                 quantity=Decimal(2), unit="pcs"))
    after = _row(w, "OAK_TRAY")
    assert Decimal(after.inventory) == Decimal(before.inventory) - 7
    assert (Decimal(after.exhibition), Decimal(after.sample)) == (Decimal(5), Decimal(2))
    assert after.total == before.total
    # sample and exhibition stock is never available to sell
    assert w.summary("OAK_TRAY")[0] == Decimal(after.inventory)
    only_exhib = categories.stock_by_category(w.actor(RAVI), categories.CategoryFilters(category="exhibition"), limit=200)
    assert w.ref("OAK_TRAY") in {r.product_id for r in only_exhib.items}
    totals = categories.category_totals(w.actor(RAVI), categories.CategoryFilters())
    assert Decimal(totals["exhibition"]) >= 5 and Decimal(totals["sample"]) >= 2


def test_opening_stock_straight_into_a_category(inv_world: InvWorld) -> None:
    w = inv_world
    sample = _location(w, w.warehouse_id, "SAMPLE").id
    with w.uow(RAVI, step_up=True) as uow:
        batch = documents.create_opening_batch(uow, OpeningBatchCreate(warehouse_id=w.warehouse_id, lines=[
            OpeningLineIn(product_id=w.ref("MAPLE_TRIVET"), quantity=Decimal(12), location_id=sample, late_opening=True)]))
        documents.submit_opening_batch(uow, batch.id, Versioned(expected_version=batch.version))
        batch_id, version = batch.id, batch.version + 1
    with w.system() as uow:
        from app.modules.inventory.models import OpeningBatch

        version = uow.session.get(OpeningBatch, batch_id).version  # type: ignore[union-attr]
    with w.uow(SAHIL, step_up=True) as uow:
        documents.decide_opening_batch(uow, batch_id, Decision(expected_version=version), approve=True)
    assert Decimal(_row(w, "MAPLE_TRIVET").sample) == Decimal(12)


def test_raw_materials_are_left_out(inv_world: InvWorld) -> None:
    w = inv_world
    finished = categories.stock_by_category(w.actor(RAVI), categories.CategoryFilters(), limit=200)
    assert w.ref("WALNUT_BOARD") not in {r.product_id for r in finished.items}  # raw material (PRM/BRW/IP class)
    assert Decimal(_row(w, "WALNUT_BOARD", include_all_classes=True).inventory) == Decimal(40)
