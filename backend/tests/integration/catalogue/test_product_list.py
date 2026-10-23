"""Product list: every filter before pagination with the same total (legacy bug §10.1 #6), product_name search,
decor and thickness normalisation, facets and stats — on real PostgreSQL over the seeded world."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import (
    PackagingIn,
    ProductCreate,
    ProductFilters,
    ProductStatus,
    SpecificationIn,
)
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def make_product(
    world: World,
    product_key: str,
    *,
    thickness: str | None = None,
    decor: str | None = None,
    name: str | None = None,
    sub: str = "SUB_TRAYS",
    category: str = "CAT_SERVEWARE",
    spec: bool = True,
    status: ProductStatus = ProductStatus.ACTIVE,
    display_sku: str | None = None,
) -> tuple[uuid.UUID, list[str]]:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result = catalogue.create_product(
            uow,
            ProductCreate(
                product_key=product_key,
                display_sku=display_sku,
                product_name=name or f"Test product {product_key}",
                category_id=world.ref(category),
                subcategory_id=world.ref(sub),
                unit_of_sale="pcs",
                decor_no=decor,
                status=status,
                specification=SpecificationIn(thickness_mm=thickness, length_mm="100", width_mm="100") if spec else None,
                packaging=PackagingIn(carton_qty=10) if spec else None,
            ),
        )
    return result.product.id, result.warnings


def _keys(world: World, user: str = keys.USERS.MEERA, **filters: object) -> tuple[int, list[str]]:
    page = catalogue.list_products(world.actor(user), ProductFilters(**filters), limit=200)
    return page.total, [p.product_key for p in page.items]


def test_thickness_filter_applies_before_pagination_with_a_correct_total(world: World) -> None:
    # 30 test products interleaved: thickness 18, thickness 12, and no specification at all
    expected = {keys.PRODUCTS.ASH_BOARD, keys.PRODUCTS.WALNUT_BOARD}
    for i in range(30):
        product_key = f"TST-{i:04d}"
        kind = i % 3
        make_product(world, product_key, thickness="18" if kind == 0 else "12" if kind == 1 else None, spec=kind != 2)
        if kind == 0:
            expected.add(product_key)
    meera = world.actor(keys.USERS.MEERA)
    seen: list[str] = []
    totals: set[int] = set()
    for offset in range(0, 15, 5):
        page = catalogue.list_products(meera, ProductFilters(thickness="18"), limit=5, offset=offset)
        totals.add(page.total)
        seen += [p.product_key for p in page.items]
        assert all(str(p.thickness_mm) == "18" for p in page.items)
    assert totals == {len(expected)} == {12}
    assert len(seen) == len(set(seen)) == 12 and set(seen) == expected  # 5 + 5 + 2, no product without specs
    assert _keys(world, thickness="18.000", q="TST")[0] == 10  # combined filters share one WHERE clause
    assert catalogue.list_products(meera, ProductFilters(thickness="18"), limit=5, offset=10).total == 12


def test_thickness_point_eight_equals_point_eighty(world: World) -> None:
    make_product(world, "TST-THIN", thickness="0.80")
    for raw in ("0.8", "0.80", "0.800", "0.8 mm"):
        assert _keys(world, thickness=raw) == (1, ["TST-THIN"])
    detail = catalogue.get_product_by_key(world.actor(keys.USERS.MEERA), "TST-THIN")
    assert detail.specification is not None and str(detail.specification.thickness_mm) == "0.8"
    with pytest.raises(ValidationFailed):
        _keys(world, thickness="thin")


def test_product_name_search_and_tokenised_q(world: World) -> None:
    assert _keys(world, q="chopping") == (1, [keys.PRODUCTS.ASH_BOARD])
    assert _keys(world, q="SERVING tray") == (1, [keys.PRODUCTS.OAK_TRAY])
    assert _keys(world, q="walnut 18") == (1, [keys.PRODUCTS.WALNUT_BOARD])
    assert _keys(world, q=keys.PRODUCTS.MAPLE_TRIVET.lower()) == (1, [keys.PRODUCTS.MAPLE_TRIVET])
    make_product(world, "TST-SKU-1", display_sku="SHARED-SKU", name="Display alias one")
    make_product(world, "TST-SKU-2", display_sku="SHARED-SKU", name="Display alias two")  # display_sku is non-unique
    assert _keys(world, q="shared-sku") == (2, ["TST-SKU-1", "TST-SKU-2"])


@pytest.mark.parametrize("q", ["%", "_", ".*", "(a+)+$", "\\", "%_%"])
def test_search_input_is_literal_never_a_pattern(world: World, q: str) -> None:
    assert _keys(world, q=q) == (0, [])


def test_decor_identity_keeps_leading_zeros_and_normalises_float_artefacts(world: World) -> None:
    _id, warnings = make_product(world, "TST-DECOR-A", decor="120.0")
    assert warnings == ["decor_no:DECOR_FLOAT_ARTEFACT_NORMALISED"]
    make_product(world, "TST-DECOR-B", decor="120")
    detail = catalogue.get_product_by_key(world.actor(keys.USERS.MEERA), "TST-DECOR-A")
    assert (detail.decor.decor_no, detail.decor.decor_no_source) == ("120", "120.0")  # never "12"
    assert _keys(world, decor=keys.DECORS.NATURAL_OAK) == (1, [keys.PRODUCTS.OAK_TRAY])
    assert _keys(world, decor="120") == (2, ["TST-DECOR-A", "TST-DECOR-B"])
    assert _keys(world, decor="120.0") == (2, ["TST-DECOR-A", "TST-DECOR-B"])
    assert _keys(world, decor="0120") == (1, [keys.PRODUCTS.OAK_TRAY])  # "0120" is distinct from "120"


def test_taxonomy_family_size_finish_and_status_filters(world: World) -> None:
    assert _keys(world, category_id=world.ref("CAT_SERVEWARE"))[0] == 3
    assert _keys(world, subcategory_id=world.ref("SUB_VENEERED_PANELS")) == (1, [keys.PRODUCTS.WALNUT_BOARD])
    assert _keys(world, family="oak serving tray") == (1, [keys.PRODUCTS.OAK_TRAY])
    assert _keys(world, size="300x450") == (1, [keys.PRODUCTS.OAK_TRAY])  # either orientation
    assert _keys(world, size="244 x 122 cm") == (1, [keys.PRODUCTS.WALNUT_BOARD])
    assert _keys(world, finish="MATTE LACQUER") == (1, [keys.PRODUCTS.OAK_TRAY])
    make_product(world, "TST-DEV", status=ProductStatus.UNDER_DEVELOPMENT)
    assert _keys(world, status=[ProductStatus.UNDER_DEVELOPMENT]) == (1, ["TST-DEV"])
    assert _keys(world, status=[ProductStatus.ACTIVE])[0] == 4
    with pytest.raises(ValidationFailed):
        _keys(world, size="450")


def test_facets_count_each_dimension_with_the_other_filters(world: World) -> None:
    facets = catalogue.product_facets(
        world.actor(keys.USERS.MEERA), ProductFilters(category_id=world.ref("CAT_SERVEWARE"))
    )
    assert facets.total == 3
    assert {(f.label, f.count) for f in facets.categories} == {("Serveware", 3), ("Decorative Boards", 1)}
    assert [(f.value, f.count) for f in facets.thicknesses] == [("10", 1), ("12", 1), ("18", 1)]
    assert {f.value for f in facets.decors} == {"0120", "0310", "0415"}
    assert {(f.value, f.count) for f in facets.statuses} == {("active", 3)}
    narrowed = catalogue.product_facets(world.actor(keys.USERS.MEERA), ProductFilters(thickness="18"))
    assert narrowed.total == 2 and {f.label for f in narrowed.subcategories} == {"Boards", "Veneered panels"}


def test_stats_and_recently_changed(world: World) -> None:
    meera = world.actor(keys.USERS.MEERA)
    stats = catalogue.product_stats(meera)
    assert stats.total == 4 and stats.by_status == {"active": 4, "inactive": 0, "under_development": 0}
    assert stats.updated_last_7_days == 0  # the world catalogue was recorded at D-116
    assert [(c.name, c.count) for c in stats.by_category] == [("Serveware", 3), ("Decorative Boards", 1)]
    make_product(world, "TST-NEW")
    stats = catalogue.product_stats(meera)
    assert stats.updated_last_7_days == 1 and stats.recently_changed[0].product_key == "TST-NEW"
    assert stats.recently_changed[0].updated_by_name == keys.PEOPLE[keys.USERS.PRIYA].name


def test_list_rows_carry_canonical_measures(world: World) -> None:
    page = catalogue.list_products(world.actor(keys.USERS.MEERA), ProductFilters(q=keys.PRODUCTS.OAK_TRAY))
    row = page.items[0]
    assert (row.carton_qty, str(row.thickness_mm), row.decor_no) == (24, "12", "0120")
    assert row.size.length_mm == Decimal("450") and row.path == f"/products/{row.id}"
    assert row.category.name == "Serveware" and row.subcategory is not None and row.subcategory.name == "Trays"
