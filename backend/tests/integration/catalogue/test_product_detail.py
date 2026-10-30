"""Product detail, completeness from actual fields, writes and their guards, isolation, source reader and search."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, VersionConflict
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import (
    CompletenessRule,
    PackagingIn,
    ProductFilters,
    ProductUpdate,
    SpecificationIn,
)
from app.platform import sources
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.registry import get_registry
from app.seed.world import keys
from tests.integration.catalogue.test_product_list import make_product
from tests.integration.catalogue.world import (
    World,
    build_personas,
    category_name,
    product_name,
    subcategory_name,
)
from tests.support import actor

pytestmark = pytest.mark.db


def _missing(detail: object) -> set[str]:
    return {m.code.value for m in detail.completeness.missing}  # type: ignore[attr-defined]


def test_detail_returns_all_field_groups_with_section_guards(world: World) -> None:
    """UI-40: every field group, deep-linkable sections; the pricing tab needs pricing.price_list.read."""
    detail = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    assert detail.category.name == category_name(keys.CATEGORIES.SERVEWARE)
    assert detail.subcategory and detail.subcategory.name == subcategory_name(keys.SUBCATEGORIES.TRAYS)
    assert detail.brand == "Lamikraft" and detail.shape == "Rectangular" and detail.finish == "Matte lacquer"
    assert detail.specification is not None and detail.specification.material_type == "Oak veneer"
    assert detail.specification.length_mm_source == "450" and detail.specification.thickness_mm_source == "12"
    assert [(d.kind.value, d.source_text, d.parse_status.value) for d in detail.dimensions] == [
        ("master_size", "450 x 300", "parsed")
    ]
    assert detail.provenance.origin.value == "seed" and detail.version == 1
    base = f"/products/{detail.id}"
    # sales hold pricing.price.read (resolved prices in the overview) but not pricing.price_list.read: no pricing tab
    assert [(s.key, s.path) for s in detail.sections] == [
        ("overview", base), ("specifications", f"{base}/specifications"), ("packaging", f"{base}/packaging"),
    ]
    for persona in (keys.USERS.SAHIL, keys.USERS.ANANYA):  # management and finance hold pricing.price_list.read
        guarded = catalogue.get_product(world.actor(persona), world.ref("OAK_TRAY"))
        assert [(s.key, s.path) for s in guarded.sections][-1] == ("pricing", f"{base}/pricing")
    kabir = catalogue.get_product(world.actor(keys.USERS.KABIR), world.ref("OAK_TRAY"))  # warehouse: no prices
    assert [s.key for s in kabir.sections] == ["overview", "specifications", "packaging"]
    assert kabir.prices is None and kabir.redacted_fields == ["prices"]
    by_key = catalogue.get_product_by_key(world.actor(keys.USERS.MEERA), f"  {keys.PRODUCTS.OAK_TRAY} ")
    assert by_key.id == detail.id


def test_detail_capabilities_come_from_the_product_policy(world: World) -> None:
    meera = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))  # sales: read only
    assert meera.capabilities["update"].model_dump() == {"allowed": False, "reason_code": "permission_denied"}
    assert meera.allowed_transitions == []
    priya = catalogue.get_product(world.actor(keys.USERS.PRIYA), world.ref("OAK_TRAY"))
    assert priya.capabilities["update"].model_dump() == {"allowed": True, "reason_code": None}


def test_completeness_is_computed_from_actual_fields(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    oak = catalogue.get_product(meera, world.ref("OAK_TRAY"))
    assert _missing(oak) == {"no_hsn_sac"} and oak.completeness.score_pct == 100  # hsn_sac awaits the owner (info)
    walnut = catalogue.get_product(meera, world.ref("WALNUT_BOARD"))
    assert _missing(walnut) == {"no_hsn_sac", "no_carton_qty", "no_unit_weight"}  # palletised, no carton data
    assert walnut.completeness.checks_passed == walnut.completeness.checks_evaluated - 2
    bare_id, _ = make_product(world, "TST-BARE", spec=False)
    bare = catalogue.get_product(meera, bare_id)
    assert {"no_specification", "no_thickness", "no_packaging", "no_carton_qty", "no_size", "no_decor"} <= _missing(bare)
    assert [n.code for n in bare.completeness.not_evaluated] == ["no_primary_image"]  # media arrive in Slice 2

    summary = catalogue.completeness_summary(meera)
    counts = {r.code.value: r.count for r in summary.rules}
    assert summary.total_products == 5 and summary.complete_products == 3
    assert counts["no_carton_qty"] == 2 and counts["no_specification"] == 1 and counts["no_hsn_sac"] == 5
    filtered = catalogue.list_products(meera, ProductFilters(issue=CompletenessRule.NO_CARTON_QTY))
    assert sorted(p.product_key for p in filtered.items) == sorted([keys.PRODUCTS.WALNUT_BOARD, "TST-BARE"])


def test_update_replaces_sections_bumps_version_and_emits_changed_groups(world: World) -> None:
    priya = world.actor(keys.USERS.PRIYA)
    product_id = world.ref("MAPLE_TRIVET")
    with UnitOfWork(priya) as uow:
        result = catalogue.update_product(
            uow, product_id,
            ProductUpdate(
                expected_version=1, finish="Oiled", hsn_sac="44191900",
                packaging=PackagingIn(master_carton_qty="48", unit_weight_kg="0.28", packing_type="Shrink wrap"),
            ),
        )
    product = result.product
    assert product.version == 2 and product.finish == "Oiled" and product.stock_attributes.hsn_sac == "44191900"
    assert product.packaging is not None and product.packaging.carton_qty == 48
    assert str(product.packaging.unit_weight_g) == "280"
    assert product.packaging.alias_provenance == {
        "carton_qty": {"master_carton_qty": "48"}, "unit_weight_g": {"unit_weight_kg": "0.28"},
    }
    with UnitOfWork(priya) as uow:
        event = uow.session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "catalogue.product.updated",
                                      DomainEvent.aggregate_id == product_id)
        ).one()
    assert event.payload["changed_groups"] == ["master", "packaging", "stock_attributes"]
    assert event.payload["changed_fields"] == ["finish", "hsn_sac", "packaging"]
    assert event.aggregate_version == 2
    with pytest.raises(VersionConflict), UnitOfWork(priya) as uow:
        catalogue.update_product(uow, product_id, ProductUpdate(expected_version=1, finish="Waxed"))
    with pytest.raises(ValidationFailed) as conflict, UnitOfWork(priya) as uow:
        catalogue.update_product(
            uow, product_id,
            ProductUpdate(expected_version=2, packaging=PackagingIn(carton_qty=24, master_carton_qty=12)),
        )
    assert conflict.value.extra["errors"][0]["code"] == "alias_conflict"


def test_overview_prices_only_from_real_lists(world: World) -> None:
    """UI-39: one overview price per currency in which a real active list prices the product; never a converted
    or relabelled figure (no USD row exists, so none is shown)."""
    oak = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("OAK_TRAY"))
    assert oak.prices is not None and oak.redacted_fields == []
    by_currency = {p.currency: p for p in oak.prices}
    assert set(by_currency) == {"EUR", "GBP"}
    eur, gbp = by_currency["EUR"], by_currency["GBP"]
    assert eur.unit_price is not None and format(eur.unit_price.amount, "f") == keys.PRICES.OAK_TRAY_EUR
    assert eur.price_list_code == keys.PRICE_LISTS.EXP_EUR and eur.item_id == world.ref("PLI_EXP_EUR_OAK_TRAY")
    assert gbp.unit_price is not None and format(gbp.unit_price.amount, "f") == keys.PRICES.OAK_TRAY_GBP
    assert eur.recommendation is not None and eur.recommendation.status == "AVAILABLE"
    assert gbp.recommendation is not None and gbp.recommendation.status == "NOT_EVALUATED"  # no GBP threshold
    walnut = catalogue.get_product(world.actor(keys.USERS.MEERA), world.ref("WALNUT_BOARD"))
    assert walnut.prices is not None and [(p.currency, p.unit_code) for p in walnut.prices] == [("INR", "sheets")]
    assert walnut.prices[0].unit_price is not None
    assert format(walnut.prices[0].unit_price.amount, "f") == keys.PRICES.WALNUT_BOARD_INR


def test_lookup_by_key_with_special_characters(world: World) -> None:
    """API-13: ``GET /catalogue/products/lookup?key=`` resolves keys that are unsafe in a path."""
    odd_key = "TST/ODD #1 & 50%"
    product_id, _ = make_product(world, odd_key)
    meera = world.actor(keys.USERS.MEERA)
    assert catalogue.get_product_by_key(meera, f"  {odd_key} ").id == product_id
    assert catalogue.get_product_by_key(meera, keys.PRODUCTS.OAK_TRAY).id == world.ref("OAK_TRAY")
    with pytest.raises(NotFound):
        catalogue.get_product_by_key(meera, "TST/ODD #1")


def test_writes_need_catalogue_keys(world: World) -> None:
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:  # management: no catalogue writes
        catalogue.update_product(uow, world.ref("OAK_TRAY"), ProductUpdate(expected_version=1, finish="x"))
    with pytest.raises(Conflict):
        make_product(world, keys.PRODUCTS.OAK_TRAY)  # product_key is unique per company
    with pytest.raises(ValidationFailed), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.update_product(
            uow, world.ref("OAK_TRAY"),
            ProductUpdate(expected_version=1, specification=SpecificationIn(thickness_mm="-2")),
        )


def test_reads_need_product_read_and_other_companies_are_not_found(world: World) -> None:
    with pytest.raises(Forbidden):
        catalogue.get_product(actor(world.company_id), world.ref("OAK_TRAY"))
    other = build_personas()
    with pytest.raises(NotFound):
        catalogue.get_product(other.actor(keys.USERS.SAHIL), world.ref("OAK_TRAY"))
    assert catalogue.list_products(other.actor(keys.USERS.SAHIL), ProductFilters()).total == 0
    assert catalogue.product_stats(other.actor(keys.USERS.SAHIL)).total == 0


def test_source_reader_and_search_provider(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    with UnitOfWork(meera) as uow:
        facts = sources.read(uow, "catalogue.product", world.ref("OAK_TRAY"))
        assert facts is not None and facts.label == f"{keys.PRODUCTS.OAK_TRAY} · {product_name('OAK_TRAY')}"
        assert facts.facts["carton_qty"] == "24" and facts.facts["thickness_mm"] == "12"
        assert facts.facts["decor_no"] == "0120" and facts.required_permission == "catalogue.product.read"
        assert facts.canonical_path == f"/products/{world.ref('OAK_TRAY')}" and facts.money == []
        provider = next(p for p in get_registry().search_providers if p.resource_type == "catalogue.product")
        hits = provider.search(uow, "oak tray", 10)
        assert [h.resource_id for h in hits] == [world.ref("OAK_TRAY")]
        assert provider.search(uow, keys.PRODUCTS.ASH_BOARD, 10)[0].rank == 100
        assert provider.search(uow, "o", 10) == []
    with UnitOfWork(actor(world.company_id)) as uow:
        assert sources.read(uow, "catalogue.product", world.ref("OAK_TRAY")) is None


def test_resolve_product_unique_ambiguous_and_not_found(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    by_key = catalogue.resolve_product(meera, keys.PRODUCTS.OAK_TRAY.lower())
    assert by_key.status == "unique" and by_key.candidates[0].match == "product_key"
    assert by_key.candidates[0].product_id == world.ref("OAK_TRAY")
    tokens = catalogue.resolve_product(meera, "oak tray")
    assert tokens.status == "unique" and tokens.candidates[0].product_key == keys.PRODUCTS.OAK_TRAY
    make_product(world, "LK-OT-0300", name="Oak serving tray 300")  # a Slice-2 variant, test-local here
    ambiguous = catalogue.resolve_product(meera, "oak tray")
    assert ambiguous.status == "ambiguous" and ambiguous.total_matches == 2
    exact = catalogue.resolve_product(meera, product_name("OAK_TRAY"))
    assert exact.status == "unique" and exact.candidates[0].match == "exact_name"
    make_product(world, "TST-SKU-A", display_sku="DUP-SKU")
    make_product(world, "TST-SKU-B", display_sku="DUP-SKU")
    assert catalogue.resolve_product(meera, "dup-sku").status == "ambiguous"  # display SKUs are non-unique
    assert catalogue.resolve_product(meera, "mahogany").status == "not_found"
    assert catalogue.resolve_product(meera, "%").status == "not_found"
