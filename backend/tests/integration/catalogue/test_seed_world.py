"""The lane's seeds build the fixture world through services, in order, and are idempotent (fixtures.md §1, §4-§6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Category, Product, Subcategory
from app.modules.commercial.models import RuleSet
from app.modules.parties import service as parties
from app.modules.parties.models import Party
from app.modules.pricing.models import PriceList, PriceListItem
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from app.seed.world.catalogue import CATEGORIES
from app.seed.world.parties import MAISON_SHIPPING_CHANGE_AT
from tests.integration.catalogue.world import World, seed_world

pytestmark = pytest.mark.db


def _counts(world: World) -> dict[str, int]:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        return {
            model.__tablename__: int(uow.session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Party, Category, Subcategory, Product, PriceList, PriceListItem, RuleSet)
        }


def test_world_numbers_follow_creation_order(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        for key in ("NORDHAUS", "MAISON", "BERG", "THORNBURY"):
            party = parties.get_party(uow, world.ref(key))
            assert party.party_number == getattr(keys.PARTIES, key)
            assert party.legal_name == keys.PARTY_NAMES[key]
        thornbury = parties.get_party(uow, world.ref("THORNBURY"))
    assert thornbury.owner.id == world.user_id(keys.USERS.NEHA)
    assert thornbury.customer_type == "dealer" and thornbury.default_currency == "GBP"
    assert thornbury.contacts[0].name == keys.CONTACTS["THORNBURY"][0] and thornbury.contacts[0].is_primary
    assert thornbury.tax_identifiers == []


def test_world_counts_and_taxonomy(world: World) -> None:
    assert _counts(world) == {
        "parties_party": 4,
        "catalogue_category": 2,
        "catalogue_subcategory": 4,
        "catalogue_product": 4,
        "pricing_price_list": 3,
        "pricing_price_list_item": 5,
        "commercial_rule_set": 1,
    }
    tree = catalogue.list_categories(world.actor(keys.USERS.MEERA))
    assert [(c.name, [s.name for s in c.subcategories], c.product_count) for c in tree] == [
        (CATEGORIES[keys.CATEGORIES.SERVEWARE][0], [name for _key, name in CATEGORIES[keys.CATEGORIES.SERVEWARE][2]], 3),
        (CATEGORIES[keys.CATEGORIES.DECORATIVE_BOARDS][0], [name for _key, name in CATEGORIES[keys.CATEGORIES.DECORATIVE_BOARDS][2]], 1),
    ]
    assert all(c.is_active and all(s.is_active for s in c.subcategories) for c in tree)


def test_seeds_are_idempotent(world: World) -> None:
    before = _counts(world)
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        events_before = uow.session.scalar(select(func.count()).select_from(DomainEvent)) or 0
    refs_before = dict(world.ctx.refs)
    seed_world(world)
    assert _counts(world) == before
    assert world.ctx.refs == refs_before
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        assert (uow.session.scalar(select(func.count()).select_from(DomainEvent)) or 0) == events_before


def test_maison_shipping_change_is_a_dated_party_update(world: World) -> None:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        updates = list(
            uow.session.scalars(
                select(DomainEvent).where(
                    DomainEvent.company_id == world.company_id, DomainEvent.event_type == "parties.party.updated"
                )
            )
        )
    assert len(updates) == 1
    event = updates[0]
    assert event.aggregate_id == world.ref("MAISON")
    assert event.payload["changed_fields"] == ["addresses.shipping"]
    assert event.payload["party_number"] == keys.PARTIES.MAISON
    assert event.occurred_at == datetime(2026, 10, 11, 4, 35, tzinfo=UTC) == MAISON_SHIPPING_CHANGE_AT
    assert event.actor_user_id == world.user_id(keys.USERS.PRIYA)


def test_seed_history_is_chronological(world: World) -> None:
    """fixtures.md §1 rule 2: the seed clock only moves forward, so outbox order (seq) is time order; the D-1 Maison
    change runs in its own late SeedDef (parties.world.changes, order 55) after the D-116/D-115 catalogue and pricing."""
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        events = list(
            uow.session.execute(
                select(DomainEvent.event_type, DomainEvent.occurred_at)
                .where(DomainEvent.company_id == world.company_id)
                .order_by(DomainEvent.seq)
            )
        )
    times = [occurred for _type, occurred in events]
    assert times == sorted(times)
    assert events[-1][0] == "parties.party.updated"


def test_oak_tray_fixture_fields(world: World) -> None:
    detail = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    assert detail.product_key == detail.display_sku == keys.PRODUCTS.OAK_TRAY
    assert detail.decor.decor_no == keys.DECORS.NATURAL_OAK == "0120"
    assert detail.packaging is not None and detail.specification is not None
    assert detail.packaging.carton_qty == 24 and detail.packaging.inner_qty == 6
    assert detail.packaging.summary == "450g · 24/ctn · Poly bag"  # FG-PKG-11 canonical summary
    assert detail.packaging.warnings == []  # cbm 0.047520 = 48 x 33 x 30 cm; gross >= net
    assert str(detail.packaging.cbm) == "0.047520"
    assert (str(detail.size.length_mm), str(detail.size.width_mm)) == ("450", "300")
    assert str(detail.specification.thickness_mm) == "12"
    assert detail.unit_of_sale == detail.stock_attributes.stock_uom_code == "pcs"
    assert detail.stock_attributes.hsn_sac is None and detail.stock_attributes.track_lots is False
    walnut = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("WALNUT_BOARD"))
    assert walnut.stock_attributes.track_lots is True and walnut.stock_attributes.qc_required is True
    assert walnut.packaging is not None and walnut.packaging.carton_qty is None
    assert walnut.packaging.packing_type == "Pallet"
