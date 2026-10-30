"""Taxonomy and products imports (LM-28/29/41, LP-04.2, FG-PRD-12, SCN-G1): taxonomy first, defaults, quarantine of
unknown categories, warnings for unknown subcategories, idempotent re-import."""

from __future__ import annotations

import pytest

from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import ProductFilters
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from tests.integration.catalogue.world import World
from tests.integration.imports.helpers import admin, csv_bytes, issues, rows, run, start, validate

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]

TAXONOMY = csv_bytes(
    ["Category", "Sub Category", "Display Order", "Is Active", "Description"],
    [["Kitchen", "", 50, "yes", "Kitchen boards"], ["Kitchen", "Chopping", 10, "", ""],
     ["Kitchen", "Serving", 20, "", ""], ["Bath", "Caddies", 5, "", ""]],
)


def test_categories_before_subcategories(world: World) -> None:
    job = run(world, "category_taxonomy", TAXONOMY, "taxonomy.csv")
    assert job.status == "committed", job
    tree = {c.name: c for c in catalogue.list_categories(admin(world))}
    assert tree["Kitchen"].description == "Kitchen boards" and tree["Kitchen"].display_order == 50
    assert [s.name for s in tree["Kitchen"].subcategories] == ["Chopping", "Serving"]
    assert [s.name for s in tree["Bath"].subcategories] == ["Caddies"]  # category created for its subcategory
    assert job.counts["committed"] == 4


def test_requires_taxonomy_and_applies_defaults(world: World) -> None:
    data = csv_bytes(
        ["product_key", "category", "subcategory", "status", "decor_no", "unit_of_sale"],
        [["IMP-001", "Kitchen", "Chopping", "In Dev", "0120", "Pieces"],
         ["IMP-002", "Kitchen", "", "", "120.0", "pcs"]],
    )
    early = start(world, "products_master", data)
    early = validate(world, early.id)
    assert early.counts.get("quarantined") == 2  # no taxonomy yet
    run(world, "category_taxonomy", TAXONOMY)
    job = run(world, "products_master", data)
    assert job.status == "committed" and job.counts["committed"] == 2
    one = catalogue.get_product_by_key(admin(world), "IMP-001")
    assert one.display_sku == "IMP-001" and one.product_name == "IMP-001"  # defaults to the key
    assert one.status.value == "under_development" and one.unit_of_sale == "pcs"
    assert one.decor.decor_no == "0120" and one.provenance.origin.value == "import"
    two = catalogue.get_product_by_key(admin(world), "IMP-002")
    assert two.decor.decor_no == "120"
    codes = {i.code for i in issues(world, job.id)}
    assert "DECOR_FLOAT_ARTEFACT_NORMALISED" in codes


def test_unknown_category_quarantined(world: World) -> None:
    run(world, "category_taxonomy", TAXONOMY)
    data = csv_bytes(["product_key", "category", "subcategory"],
                     [["IMP-010", "Garden", ""], ["IMP-011", "Kitchen", "Platters"]])
    job = start(world, "products_master", data)
    job = validate(world, job.id)
    by_row = {r.row_number: r for r in rows(world, job.id)}
    assert by_row[2].status == "quarantined" and "CATEGORY_NOT_FOUND" in by_row[2].issue_codes
    assert by_row[3].status == "warning" and "SUBCATEGORY_UNKNOWN" in by_row[3].issue_codes


def test_second_identical_import_is_noop(world: World) -> None:
    run(world, "category_taxonomy", TAXONOMY)
    data = csv_bytes(["product_key", "category", "subcategory", "product_name"],
                     [["IMP-020", "Kitchen", "Chopping", "Board A"], ["IMP-021", "Kitchen", "Serving", "Board B"]])
    first = run(world, "products_master", data)
    assert first.counts["committed"] == 2
    version = catalogue.get_product_by_key(admin(world), "IMP-020").version
    with UnitOfWork(admin(world)) as uow:
        events_before = uow.session.query(DomainEvent).filter(DomainEvent.event_type.like("catalogue.product.%")).count()
    second = run(world, "products_master", data)
    assert second.status == "committed"
    assert second.counts.get("unchanged") == 2 and "committed" not in second.counts
    assert catalogue.get_product_by_key(admin(world), "IMP-020").version == version  # no version bump
    with UnitOfWork(admin(world)) as uow:
        events_after = uow.session.query(DomainEvent).filter(DomainEvent.event_type.like("catalogue.product.%")).count()
    assert events_after == events_before
    page = catalogue.list_products(admin(world), ProductFilters(q="IMP-02"))
    assert page.total == 2  # no duplicates
