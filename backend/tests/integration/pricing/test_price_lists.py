"""Price-list read APIs, breakdown field guard, protected product cost, append-only history and the no-overlap
constraint, on real PostgreSQL."""

from __future__ import annotations

import zlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db.base import new_id
from app.core.errors import Conflict, Forbidden
from app.core.money import Money
from app.modules.pricing import service as pricing
from app.modules.pricing.models import PriceList, PriceListItem, PriceListItemHistory, ProductCost
from app.modules.pricing.schemas import (
    CostComponent,
    PriceListCreate,
    PriceListItemCreate,
    PriceListStatus,
    ProductCostCreate,
    SupersedeItem,
)
from app.platform.audit.models import AuditLog
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
    assert [(i.product_key, format(i.unit_price.amount, "f"), i.unit_price.currency) for i in items.items] == [
        (keys.PRODUCTS.ASH_BOARD, keys.PRICES.ASH_BOARD_EUR, "EUR"),
        (keys.PRODUCTS.MAPLE_TRIVET, keys.PRICES.MAPLE_TRIVET_EUR, "EUR"),
        (keys.PRODUCTS.OAK_TRAY, keys.PRICES.OAK_TRAY_EUR, "EUR"),
    ]
    prices = pricing.product_prices(meera, world.ref("OAK_TRAY"))
    assert sorted((p.price_list_code, format(p.unit_price.amount, "f")) for p in prices.prices) == [
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
    assert meera_item.unit_price.model_dump(mode="json") == {"amount": "3600.0000", "currency": "INR"}
    sahil_item = pricing.list_price_list_items(world.actor(keys.USERS.SAHIL), pl.id).items[0]
    assert sahil_item.base_price is not None and sahil_item.addon_price is not None
    assert (format(sahil_item.base_price.amount, "f"), sahil_item.base_price_label, format(sahil_item.addon_price.amount, "f")) == (
        "3000.0000", "Board", "600.0000"
    )
    assert sahil_item.base_price.currency == sahil_item.addon_price.currency == "INR"
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
    assert ananya.current_cost is not None and ananya.current_cost.unit_cost == Money(amount=SENTINEL, currency="EUR")
    assert redact(ananya, world.actor(keys.USERS.ANANYA), for_model=True).current_cost is None  # never to a model
    history = pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    assert history.total == 1 and [(c.cost_version, c.unit_cost) for c in history.items] == [
        (1, Money(amount=SENTINEL, currency="EUR"))
    ]
    with UnitOfWork(world.actor(keys.USERS.ANANYA)) as uow:
        cost_rows = uow.session.execute(
            select(ProductCost.cost_version).where(ProductCost.product_id == world.ref("OAK_TRAY"))
        ).all()
    assert len(cost_rows) == 1


def test_cost_reads_are_audited_without_values(world: World) -> None:
    """permissions.md §6: pricing.cost.read is sensitive (audited on use); the audit lists field names, never values."""
    _record_cost(world)
    pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    pricing.product_prices(world.actor(keys.USERS.ANANYA), world.ref("OAK_TRAY"))
    pricing.product_prices(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))  # no cost returned: no audit
    pricing.list_product_costs(world.actor(keys.USERS.SAHIL), world.ref("MAPLE_TRIVET"))  # no rows: no audit
    with UnitOfWork(world.actor(keys.USERS.ANANYA)) as uow:
        rows = list(uow.session.scalars(
            select(AuditLog).where(AuditLog.action == "pricing.product_cost.read").order_by(AuditLog.occurred_at, AuditLog.id)
        ))
    assert [(r.actor_user_id, r.resource_id) for r in rows] == [
        (world.user_id(keys.USERS.SAHIL), world.ref("OAK_TRAY")), (world.user_id(keys.USERS.ANANYA), world.ref("OAK_TRAY")),
    ]
    assert all(r.restricted_fields == ["unit_cost", "cost_components"] and r.details == {"cost_versions": [1]} for r in rows)
    assert all(str(SENTINEL) not in str((r.changes, r.details)) for r in rows)


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


def test_supersede_only_on_active_lists(world: World) -> None:
    """Draft items are edited before activation and retired lists are history: neither is superseded."""
    priya = world.actor(keys.USERS.PRIYA)
    with UnitOfWork(priya) as uow:
        draft = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-SUP", "name": "Draft", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        draft_item = pricing.add_item(uow, draft.id, PriceListItemCreate(
            product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(30)))
        draft_id, draft_item_id = draft.id, draft_item.id
    caps = pricing.get_price_list(priya, draft_id).capabilities
    assert (caps["supersede_item"].allowed, caps["supersede_item"].reason_code) == (False, "price_list_not_active")
    with pytest.raises(Conflict) as excinfo, UnitOfWork(priya) as uow:
        pricing.supersede_item(uow, draft_item_id, SupersedeItem(unit_price=Decimal(31), valid_from=date(2026, 11, 1)))
    assert excinfo.value.code == "price_list_not_active"
    with UnitOfWork(priya) as uow:  # a retired list (Slice 2 retires lists; set directly here)
        uow.session.execute(update(PriceList).where(PriceList.id == world.ref("PL_EXP_GBP")).values(status="retired"))
    retired = pricing.get_price_list(world.actor(keys.USERS.PRIYA), world.ref("PL_EXP_GBP")).capabilities
    assert retired["supersede_item"].reason_code == "price_list_not_active"
    with pytest.raises(Conflict) as excinfo, UnitOfWork(priya) as uow:
        pricing.supersede_item(uow, world.ref(item_ref("PL_EXP_GBP", "OAK_TRAY")),
                               SupersedeItem(unit_price=Decimal(21), valid_from=date(2026, 11, 1)))
    assert excinfo.value.code == "price_list_not_active"


def test_active_item_prices_are_immutable_in_the_database(world: World) -> None:
    """commercial.md §2.2 / ADR-018: once the list is active, the price columns cannot be updated, even by SQL; only
    shortening valid_to, retiring and setting superseded_by once are allowed. Draft items stay editable."""
    priya = world.actor(keys.USERS.PRIYA)
    item_id = world.ref(item_ref("PL_EXP_EUR", "OAK_TRAY"))
    for values in ({"unit_price": Decimal(1)}, {"unit_code": "box"}, {"valid_from": date(2026, 2, 1)},
                   {"status": "draft"}):
        with pytest.raises(DBAPIError, match="immutable|only be"), UnitOfWork(priya) as uow:
            uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(**values))
    with UnitOfWork(priya) as uow:  # shortening valid_to is allowed
        uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(valid_to=date(2026, 11, 30)))
    for later in (date(2026, 12, 31), None):  # never extended or reopened
        with pytest.raises(DBAPIError, match="only be shortened"), UnitOfWork(priya) as uow:
            uow.session.execute(update(PriceListItem).where(PriceListItem.id == item_id).values(valid_to=later))
    with UnitOfWork(priya) as uow:
        draft = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "DRAFT-EDIT", "name": "Draft", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        draft_item = pricing.add_item(uow, draft.id, PriceListItemCreate(
            product_id=world.ref("OAK_TRAY"), unit_code="pcs", unit_price=Decimal(30)))
        uow.session.execute(update(PriceListItem).where(PriceListItem.id == draft_item.id).values(unit_price=Decimal(29)))
        assert uow.session.scalar(select(PriceListItem.unit_price).where(PriceListItem.id == draft_item.id)) == Decimal(29)


def test_activation_takes_the_target_lock(world: World) -> None:
    """Concurrent activations for the same scope, type and currency serialise on one advisory lock, so the overlap
    check cannot race under READ COMMITTED (the exclusion constraint only covers one list)."""
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        pl = pricing.create_price_list(uow, PriceListCreate.model_validate({
            "code": "SMP-LOCK", "name": "Lock", "price_type": "sample", "currency": "EUR", "valid_from": "2026-01-01",
        }))
        pricing.add_item(uow, pl.id, PriceListItemCreate(product_id=world.ref("OAK_TRAY"), unit_code="pcs",
                                                         unit_price=Decimal(30)))
        pricing.activate_price_list(uow, pl.id)
        target = pricing._activation_target(pl)
        held = uow.session.scalar(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
            "AND classid = :a AND objid = :b"
        ), {"a": zlib.crc32(b"pricing.activation") & 0x7FFFFFFF, "b": zlib.crc32(target.encode()) & 0x7FFFFFFF})
    assert held == 1
    assert target == f"{world.company_id}:standard:-:sample:EUR"
