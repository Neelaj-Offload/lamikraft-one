"""Catalogue home figures (LM-14/15, API-11/12, UI-27/30/31, LM-22/API-23, API-67, LP-11.2): stats, recent products,
exclude-self facets and per-product completeness counted from the real columns."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationFailed
from app.modules.catalogue import products
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import CompletenessRule, ProductCreate, ProductFilters, ProductUpdate
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

PRIYA, MEERA, RAVI = keys.USERS.PRIYA, keys.USERS.MEERA, keys.USERS.RAVI
SEEDED = ("OAK_TRAY", "MAPLE_TRIVET", "ASH_BOARD", "WALNUT_BOARD")


def _bare(world: World, key: str) -> None:
    with UnitOfWork(world.actor(PRIYA)) as uow:
        catalogue.create_product(
            uow,
            ProductCreate(product_key=key, product_name=key, category_id=world.ref(keys.CATEGORIES.SERVEWARE)),
        )


def test_stats_count_distinct_products(world: World) -> None:
    _bare(world, "TST-BARE-1")
    stats = catalogue.product_stats(world.actor(PRIYA))
    assert stats.total == len(SEEDED) + 1 == sum(stats.by_status.values())
    assert stats.by_status["active"] == stats.total
    # every seeded product is priced in a real active list; the bare one is not (counted once, not per list)
    assert stats.without_active_price == 1
    assert sum(c.count for c in stats.by_category) == stats.total
    no_price = catalogue.list_products(world.actor(PRIYA), ProductFilters(has_price=False))
    assert [p.product_key for p in no_price.items] == ["TST-BARE-1"] and no_price.total == 1


def test_stats_hide_price_figures_without_pricing_read(world: World) -> None:
    base = world.actor(PRIYA)
    no_pricing = base.with_(permissions={k: v for k, v in base.permissions.items() if not k.startswith("pricing.")})
    stats = catalogue.product_stats(no_pricing)
    assert stats.without_active_price is None
    with pytest.raises(ValidationFailed):
        catalogue.list_products(no_pricing, ProductFilters(has_price=True))
    summary = catalogue.completeness_summary(no_pricing)
    assert "no_active_price" in {n.code for n in summary.not_evaluated}


def test_recent_products_with_origin_and_actor(world: World) -> None:
    pid = world.ref("ASH_BOARD")
    version = catalogue.get_product(world.actor(PRIYA), pid).version
    with UnitOfWork(world.actor(PRIYA)) as uow:
        catalogue.update_product(uow, pid, ProductUpdate(expected_version=version, finish="Waxed"))
    recent = products.recent_products(world.actor(MEERA), limit=6)
    assert recent[0].id == pid and recent[0].origin == "seed"
    assert recent[0].updated_by_name == keys.PEOPLE[PRIYA].name
    assert len(recent) == len(SEEDED)
    assert recent[0].redacted_fields == []  # sales hold pricing.price.read


def test_facets_exclude_self_and_count_scoped_rows(world: World) -> None:
    serveware = world.ref(keys.CATEGORIES.SERVEWARE)
    facets = catalogue.product_facets(world.actor(MEERA), ProductFilters(category_id=serveware))
    # the category facet ignores its own filter (all categories still counted) ...
    assert sum(v.count for v in facets.categories) == len(SEEDED)
    # ... while every other dimension counts only the filtered rows
    assert facets.total == sum(v.count for v in facets.statuses)
    assert facets.total < len(SEEDED)
    thickness = facets.thicknesses[0].value
    narrowed = catalogue.list_products(world.actor(MEERA), ProductFilters(category_id=serveware, thickness=thickness))
    assert narrowed.total == facets.thicknesses[0].count


def test_metrics_count_distinct_products_real_fields(world: World) -> None:
    _bare(world, "TST-BARE-2")
    summary = catalogue.completeness_summary(world.actor(PRIYA))
    counts = {r.code: r.count for r in summary.rules}
    assert summary.total_products == len(SEEDED) + 1
    # the bare product lacks specification, packaging, decor and an image; counted once per rule
    assert counts[CompletenessRule.NO_SPECIFICATION] == 1
    assert counts[CompletenessRule.NO_PACKAGING] == 1
    assert counts[CompletenessRule.NO_ACTIVE_PRICE] == 1
    assert counts[CompletenessRule.NO_IMAGE] == summary.total_products  # nothing has media yet
    for rule in summary.rules:
        page = catalogue.list_products(world.actor(PRIYA), ProductFilters(issue=rule.code))
        assert page.total == rule.count, rule.code  # the link filter shows exactly the counted products
    detail = catalogue.get_product(world.actor(PRIYA), world.ref("OAK_TRAY"))
    assert {m.code for m in detail.completeness.missing} >= {CompletenessRule.NO_IMAGE, CompletenessRule.NO_PRIMARY_IMAGE}
    assert 0 < detail.completeness.score_pct < 100
