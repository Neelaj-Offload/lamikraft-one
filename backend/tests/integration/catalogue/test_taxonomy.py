"""Taxonomy rules (FG-TAX-01..06, FG-PRD-05, FG-REL-01, BUG-07) on real PostgreSQL: created categories are active by
default, name keys are unique, products only take a subcategory of their own category (service and composite FK),
an inactive parent hides its children, and the tree follows display order."""

from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Category, Product, Subcategory
from app.modules.catalogue.schemas import CategoryCreate, ProductCreate, ProductFilters
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, category_name, subcategory_name

pytestmark = pytest.mark.db
PRIYA = keys.USERS.PRIYA


def _category(world: World, name: str, **kw: object) -> tuple[str, str]:
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        cat = catalogue.create_category(uow, CategoryCreate.model_validate({"name": name, **kw}))
        sub = catalogue.create_subcategory(uow, cat.id, CategoryCreate.model_validate({"name": f"{name} sub"}))
        return str(cat.id), str(sub.id)


def test_created_category_active_by_default(world: World) -> None:
    """BUG-07 (legacy bug §10.1 #7): a created category and subcategory are active and visible without a flag."""
    cat_id, sub_id = _category(world, "Coasters")
    tree = {c.name: c for c in catalogue.list_categories(world.actor(keys.USERS.MEERA))}
    assert tree["Coasters"].is_active and str(tree["Coasters"].id) == cat_id
    assert [(str(s.id), s.is_active, s.effective_active) for s in tree["Coasters"].subcategories] == [(sub_id, True, True)]
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:  # sales cannot manage taxonomy
        catalogue.create_category(uow, CategoryCreate(name="Sales category"))


def test_duplicate_name_keys_conflict(world: World) -> None:
    """FG-TAX: names are unique per company by a normalised key (case and spacing do not make a new category)."""
    serveware = category_name(keys.CATEGORIES.SERVEWARE)
    with pytest.raises(Conflict) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.create_category(uow, CategoryCreate(name=f"  {serveware.upper()} "))
    assert excinfo.value.code == "category_exists"
    with pytest.raises(Conflict) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.create_subcategory(uow, world.ref(keys.CATEGORIES.SERVEWARE), CategoryCreate(name=subcategory_name(keys.SUBCATEGORIES.TRAYS).lower()))
    assert excinfo.value.code == "subcategory_exists"
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # the same subcategory name under another category is fine
        catalogue.create_subcategory(uow, world.ref(keys.CATEGORIES.DECORATIVE_BOARDS), CategoryCreate(name=subcategory_name(keys.SUBCATEGORIES.TRAYS)))


def test_composite_fk_rejects_foreign_subcategory(world: World) -> None:
    """FG-PRD-05 / FG-REL-01: a product's subcategory must belong to its category, in the service and in the database
    (fk_catalogue_product_subcategory_in_category)."""
    with pytest.raises(ValidationFailed) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.create_product(uow, ProductCreate(
            product_key="TST-FOREIGN-SUB", product_name="Foreign subcategory", category_id=world.ref(keys.CATEGORIES.SERVEWARE),
            subcategory_id=world.ref(keys.SUBCATEGORIES.VENEERED_PANELS), unit_of_sale="pcs",
        ))
    assert [e["code"] for e in excinfo.value.extra["errors"]] == ["subcategory_not_in_category"]
    with pytest.raises(DBAPIError, match="fk_catalogue_product_subcategory_in_category"), \
            UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(
            update(Product).where(Product.id == world.ref("OAK_TRAY")).values(subcategory_id=world.ref(keys.SUBCATEGORIES.VENEERED_PANELS))
        )


def test_inactive_parent_hides_its_children(world: World) -> None:
    """FG-TAX: an inactive category is left out of the tree with its subcategories unless include_inactive; its
    children then read as not effectively active, and new products cannot use it."""
    cat_id, _sub_id = _category(world, "Placemats")
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # deactivation UI is Slice 2; set directly here
        uow.session.execute(update(Category).where(Category.name == "Placemats").values(is_active=False))
    meera = world.actor(keys.USERS.MEERA)
    assert "Placemats" not in [c.name for c in catalogue.list_categories(meera)]
    full = {c.name: c for c in catalogue.list_categories(meera, include_inactive=True)}
    assert full["Placemats"].is_active is False
    assert [(s.is_active, s.effective_active) for s in full["Placemats"].subcategories] == [(True, False)]
    with pytest.raises(ValidationFailed) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.create_product(uow, ProductCreate(
            product_key="TST-INACTIVE-CAT", product_name="Inactive", category_id=cat_id, unit_of_sale="pcs",  # type: ignore[arg-type]
        ))
    assert "category_inactive" in [e["code"] for e in excinfo.value.extra["errors"]]


def test_tree_follows_display_order(world: World) -> None:
    """FG-TAX: categories (and subcategories) are listed by display order, then name."""
    _category(world, "Aardvark range", display_order=99)
    _category(world, "Zebra range", display_order=-1)
    names = [c.name for c in catalogue.list_categories(world.actor(keys.USERS.MEERA))]
    assert names[0] == "Zebra range" and names[-1] == "Aardvark range"
    assert names.index(category_name(keys.CATEGORIES.SERVEWARE)) < names.index(category_name(keys.CATEGORIES.DECORATIVE_BOARDS))


# ---- Slice 2: taxonomy management (LM-40..42, FG-TAX-04..06, BUG-16, API-21/22/29, SCN-G3) -------------------------
def _tax_cat(world: World, key: str):  # type: ignore[no-untyped-def]
    return next(c for c in catalogue.list_categories(world.actor(PRIYA), include_inactive=True) if c.id == world.ref(key))


def test_crud_reorder_and_activation(world: World) -> None:
    from app.modules.catalogue import taxonomy

    with UnitOfWork(world.actor(PRIYA)) as uow:
        created = taxonomy.create_category(
            uow, CategoryCreate(name="Kitchen", description="Kitchen boards", source_catalog_page_start="12",
                                source_catalog_page_end="18")
        )
    assert created.is_active and created.description == "Kitchen boards"
    assert (created.source_catalog_page_start, created.source_catalog_page_end) == ("12", "18")
    with UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.create_subcategory(uow, created.id, CategoryCreate(name="Chopping"))
    ids = [c.id for c in catalogue.list_categories(world.actor(PRIYA), include_inactive=True)]
    new_order = [created.id, *[i for i in ids if i != created.id]]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        tree = taxonomy.reorder(uow, taxonomy.ReorderRequest(ordered_ids=new_order))
    assert [c.id for c in tree] == new_order and tree[0].display_order == 10
    with pytest.raises(ValidationFailed), UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.reorder(uow, taxonomy.ReorderRequest(ordered_ids=new_order[:1]))
    row = next(c for c in catalogue.list_categories(world.actor(PRIYA), include_inactive=True) if c.id == created.id)
    with UnitOfWork(world.actor(PRIYA)) as uow:
        version = uow.session.get(Category, created.id).version  # type: ignore[union-attr]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        cat = taxonomy.update_category(uow, created.id, taxonomy.TaxonomyUpdate(expected_version=version, is_active=False))
    assert cat.is_active is False and row.is_active is True
    assert created.id not in {c.id for c in catalogue.list_categories(world.actor(PRIYA))}
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        taxonomy.update_category(uow, created.id, taxonomy.TaxonomyUpdate(expected_version=version + 1, is_active=True))


def test_hierarchy_respects_inactive_parent(world: World) -> None:
    from app.modules.catalogue import taxonomy

    cat_id = world.ref(keys.CATEGORIES.SERVEWARE)
    with UnitOfWork(world.actor(PRIYA)) as uow:
        version = uow.session.get(Category, cat_id).version  # type: ignore[union-attr]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.update_category(uow, cat_id, taxonomy.TaxonomyUpdate(expected_version=version, is_active=False))
    tree = catalogue.list_categories(world.actor(PRIYA), include_inactive=True)
    serveware = next(c for c in tree if c.id == cat_id)
    assert serveware.subcategories and all(not s.effective_active for s in serveware.subcategories)
    assert all(s.is_active for s in serveware.subcategories)  # own flags unchanged
    assert cat_id not in {c.id for c in catalogue.list_categories(world.actor(PRIYA))}


def test_live_counts_computed(world: World) -> None:
    serveware = _tax_cat(world, keys.CATEGORIES.SERVEWARE)
    live = catalogue.list_products(
        world.actor(PRIYA), ProductFilters(
            category_id=serveware.id
        )
    ).total
    assert serveware.product_count == live
    assert sum(s.product_count for s in serveware.subcategories) == live


def test_rename_alias_and_delete_or_reassign(world: World) -> None:
    from app.modules.catalogue import taxonomy

    trays = world.ref(keys.SUBCATEGORIES.TRAYS)
    serveware = world.ref(keys.CATEGORIES.SERVEWARE)
    oak = world.ref("OAK_TRAY")
    # rename: the old name becomes an alias and product search follows the new name
    with UnitOfWork(world.actor(PRIYA)) as uow:
        sub_version = uow.session.get(Subcategory, trays).version  # type: ignore[union-attr]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.update_subcategory(uow, trays, taxonomy.TaxonomyUpdate(expected_version=sub_version, name="Serving trays"))
    with UnitOfWork(world.actor(PRIYA)) as uow:
        resolved, via_alias = taxonomy.resolve_subcategory(uow, serveware, subcategory_name(keys.SUBCATEGORIES.TRAYS))
    assert resolved is not None and resolved.id == trays and via_alias
    found = catalogue.list_products(
        world.actor(PRIYA), ProductFilters(
            q="serving trays"
        )
    )
    assert oak in {p.id for p in found.items}
    with pytest.raises(Conflict), UnitOfWork(world.actor(PRIYA)) as uow:  # a former name is reserved in the scope
        taxonomy.create_subcategory(uow, serveware, CategoryCreate(name=subcategory_name(keys.SUBCATEGORIES.TRAYS)))
    # delete: blocked while referenced, with per-table counts
    with UnitOfWork(world.actor(PRIYA)) as uow:
        refs = taxonomy.subcategory_references(uow, trays)
    counts = {r.table: r.count for r in refs.references}
    assert counts.get("catalogue_product", 0) >= 1 and refs.aliases == [subcategory_name(keys.SUBCATEGORIES.TRAYS)]
    with UnitOfWork(world.actor(PRIYA)) as uow:
        version = uow.session.get(Subcategory, trays).version  # type: ignore[union-attr]
    with pytest.raises(Conflict) as blocked, UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.delete_subcategory(uow, trays, taxonomy.TaxonomyDelete(expected_version=version))
    assert blocked.value.code == "taxonomy_referenced"
    target = taxonomy.ReassignTarget(category_id=serveware, subcategory_id=world.ref(keys.SUBCATEGORIES.BOARDS))
    with pytest.raises(Conflict) as stale, UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.delete_subcategory(
            uow, trays, taxonomy.TaxonomyDelete(expected_version=version, reassign_to=target,
                                                expected_reference_counts={"catalogue_product": 999})
        )
    assert stale.value.code == "references_changed"
    with UnitOfWork(world.actor(PRIYA)) as uow:
        result = taxonomy.delete_subcategory(
            uow, trays, taxonomy.TaxonomyDelete(expected_version=version, reassign_to=target,
                                                expected_reference_counts=counts)
        )
    assert result.reassigned == counts
    moved = catalogue.get_product(world.actor(PRIYA), oak)
    assert moved.subcategory is not None and moved.subcategory.id == world.ref(keys.SUBCATEGORIES.BOARDS)
    # a category with subcategories cannot be deleted by reassigning products only (no handler for subcategories)
    with UnitOfWork(world.actor(PRIYA)) as uow:
        cat_version = uow.session.get(Category, serveware).version  # type: ignore[union-attr]
        cat_refs = {r.table: r.count for r in taxonomy.category_references(uow, serveware).references}
    with pytest.raises(Conflict) as unsupported, UnitOfWork(world.actor(PRIYA)) as uow:
        taxonomy.delete_category(
            uow, serveware, taxonomy.TaxonomyDelete(
                expected_version=cat_version,
                reassign_to=taxonomy.ReassignTarget(category_id=world.ref(keys.CATEGORIES.DECORATIVE_BOARDS)),
                expected_reference_counts=cat_refs,
            )
        )
    assert unsupported.value.code == "reassign_unsupported"


def test_validation_report(world: World) -> None:
    from app.modules.catalogue import taxonomy

    with UnitOfWork(world.actor(PRIYA)) as uow:
        catalogue.create_product(
            uow,
            ProductCreate(product_key="TST-UNRESOLVED", product_name="x", category_id=world.ref(keys.CATEGORIES.SERVEWARE),
                          subcategory_source="Platters"),
        )
        taxonomy.create_category(uow, CategoryCreate(name="Empty shelf"))
    report = taxonomy.validation_report(world.actor(PRIYA))
    assert report.counts["SUBCATEGORY_UNRESOLVED"] == 1
    assert next(i for i in report.items if i.code == "SUBCATEGORY_UNRESOLVED").value == "Platters"
    assert "Empty shelf" in {i.value for i in report.items if i.code == "CATEGORY_EMPTY"}
