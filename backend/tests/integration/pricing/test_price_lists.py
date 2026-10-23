"""Price-list read APIs, breakdown field guard, protected product cost, append-only history and the no-overlap
constraint, on real PostgreSQL."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceListItem, PriceListItemHistory, ProductCost
from app.modules.pricing.schemas import (
    CostComponent,
    PriceListCreate,
    PriceListItemCreate,
    PriceListStatus,
    ProductCostCreate,
)
from app.platform.authz.redaction import redact
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.pricing import item_ref
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

SENTINEL = Decimal("13.5791")


def _record_cost(world: World, user: str = keys.USERS.ANANYA) -> None:
    with UnitOfWork(world.actor(user)) as uow:
        pricing.record_product_cost(
            uow, world.ref("OAK_TRAY"),
            ProductCostCreate(unit_cost_amount=SENTINEL, unit_cost_currency="EUR", unit_code="pcs",
                              effective_from=date(2026, 10, 1), cost_components=[CostComponent(label="veneer", amount=Decimal("9"))]),
        )


def test_lists_items_and_product_prices(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    page = pricing.list_price_lists(meera)
    assert [p.code for p in page.items] == sorted([keys.PRICE_LISTS.DOM_INR, keys.PRICE_LISTS.EXP_EUR, keys.PRICE_LISTS.EXP_GBP])
    assert page.total == 3 and all(p.status == PriceListStatus.ACTIVE for p in page.items)
    assert pricing.list_price_lists(meera, currency="GBP").total == 1
    assert pricing.list_price_lists(meera, on_date=date(2027, 1, 1)).total == 0
    eur = world.ref("PL_EXP_EUR")
    detail = pricing.get_price_list(meera, eur)
    assert (detail.code, detail.currency, detail.item_count, detail.valid_to) == (keys.PRICE_LISTS.EXP_EUR, "EUR", 3,
                                                                                date(2026, 12, 31))
    items = pricing.list_price_list_items(meera, eur)
    assert [(i.product_key, str(i.unit_price), i.currency) for i in items.items] == [
        (keys.PRODUCTS.ASH_BOARD, keys.PRICES.ASH_BOARD_EUR, "EUR"),
        (keys.PRODUCTS.MAPLE_TRIVET, keys.PRICES.MAPLE_TRIVET_EUR, "EUR"),
        (keys.PRODUCTS.OAK_TRAY, keys.PRICES.OAK_TRAY_EUR, "EUR"),
    ]
    prices = pricing.product_prices(meera, world.ref("OAK_TRAY"))
    assert sorted((p.price_list_code, str(p.unit_price)) for p in prices.prices) == [
        (keys.PRICE_LISTS.EXP_EUR, keys.PRICES.OAK_TRAY_EUR), (keys.PRICE_LISTS.EXP_GBP, keys.PRICES.OAK_TRAY_GBP),
    ]
    assert prices.on_date == date(2026, 10, 12)


def test_price_list_capabilities_follow_permission_and_state(world: World) -> None:
    eur = world.ref("PL_EXP_EUR")
    meera = pricing.get_price_list(world.actor(keys.USERS.MEERA), eur)
    assert {k: (c.allowed, c.reason_code) for k, c in meera.capabilities.items()} == {
        "add_item": (False, "permission_denied"), "supersede_item": (False, "permission_denied"),
    }
    assert meera.allowed_transitions == []
    priya = world.actor(keys.USERS.PRIYA)
    active = pricing.get_price_list(priya, eur)
    assert {k: (c.allowed, c.reason_code) for k, c in active.capabilities.items()} == {
        "add_item": (False, "price_list_not_draft"), "supersede_item": (True, None),
    }
    assert active.allowed_transitions == []
    with UnitOfWork(priya) as uow:
        draft_id = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-CAPS", "name": "Draft", "price_type": "export", "currency": "EUR", "valid_from": "2026-01-01",
        })).id
    draft = pricing.get_price_list(priya, draft_id)
    assert draft.capabilities["add_item"].allowed is True
    assert [(t.action, t.to_status, t.requires_reason) for t in draft.allowed_transitions] == [("activate", "active", False)]


def test_breakdown_fields_need_price_list_read(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DOM-INR-BRK", "name": "Breakdown", "price_type": "domestic", "currency": "INR",
            "valid_from": "2026-01-01", "price_basis": "per sheet",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(
            product_id=world.ref("WALNUT_BOARD"), unit_code="sheets", unit_price=Decimal("3600"),
            base_price=Decimal("3000"), base_price_label="Board", addon_price=Decimal("600"), addon_price_label="Veneer",
            yield_qty_per_board=Decimal("1"), thickness_mm=Decimal("18"), price_basis="per sheet",
        ))
    meera_item = pricing.list_price_list_items(world.actor(keys.USERS.MEERA), pl.id).items[0]
    assert meera_item.base_price is None and meera_item.addon_price is None and meera_item.yield_qty_per_board is None
    assert meera_item.redacted_fields == ["addon_price", "addon_price_label", "base_price", "base_price_label",
                                          "price_basis", "source_kind", "thickness_mm", "yield_qty_per_board"]
    assert str(meera_item.unit_price) == "3600.0000"
    sahil_item = pricing.list_price_list_items(world.actor(keys.USERS.SAHIL), pl.id).items[0]
    assert (str(sahil_item.base_price), sahil_item.base_price_label, str(sahil_item.addon_price)) == ("3000.0000", "Board", "600.0000")
    assert sahil_item.redacted_fields == []
    assert pricing.get_price_list(world.actor(keys.USERS.MEERA), pl.id).price_basis is None
    assert pricing.get_price_list(world.actor(keys.USERS.SAHIL), pl.id).price_basis == "per sheet"


def test_product_cost_is_restricted_everywhere(world: World) -> None:
    _record_cost(world)
    with pytest.raises(Forbidden):  # sales cannot record or read costs
        _record_cost(world, keys.USERS.MEERA)
    with pytest.raises(Forbidden):
        pricing.list_product_costs(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    meera = pricing.product_prices(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    assert meera.current_cost is None and meera.redacted_fields == ["current_cost"]
    assert str(SENTINEL) not in meera.model_dump_json()
    ananya = pricing.product_prices(world.actor(keys.USERS.ANANYA), world.ref("OAK_TRAY"))
    assert ananya.current_cost is not None and ananya.current_cost.unit_cost_amount == SENTINEL
    assert redact(ananya, world.actor(keys.USERS.ANANYA), for_model=True).current_cost is None  # never to a model
    history = pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    assert [(c.cost_version, c.unit_cost_amount) for c in history] == [(1, SENTINEL)]
    with UnitOfWork(world.actor(keys.USERS.ANANYA)) as uow:
        audit_rows = uow.session.execute(
            select(ProductCost.cost_version).where(ProductCost.product_id == world.ref("OAK_TRAY"))
        ).all()
    assert len(audit_rows) == 1


def test_history_and_cost_are_append_only(world: World) -> None:
    _record_cost(world)
    with pytest.raises(DBAPIError, match="append-only|permission denied"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(PriceListItemHistory).values(reason="tampered"))
    with pytest.raises(DBAPIError, match="append-only|permission denied"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(ProductCost).values(unit_cost_amount=Decimal(1)))


def test_items_never_overlap_for_the_same_list_product_and_unit(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-EUR", "name": "Draft", "price_type": "export", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(1)))
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(2)))
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # active lists change by supersede
        pricing.add_item(uow, world.ref("PL_EXP_EUR"),
                         PriceListItemCreate(product_id=world.ref("WALNUT_BOARD"), unit_code="sheets", unit_price=Decimal(1)))
    original = world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY"))
    with pytest.raises(DBAPIError, match="ex_pricing_price_list_item_no_overlap"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        row = uow.session.get(PriceListItem, original)
        assert row is not None
        uow.session.execute(insert(PriceListItem).values(
            id=new_id(), company_id=world.company_id, price_list_id=row.price_list_id, product_id=row.product_id,
            product_key=row.product_key, unit_code="pcs", unit_price=Decimal(5), valid_from=date(2026, 6, 1),
            status="active", source_kind="manual", version=1, created_at=row.created_at, updated_at=row.created_at,
        ))
