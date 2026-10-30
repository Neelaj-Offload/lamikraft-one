"""Taxonomy rules (FG-TAX-01..06, FG-PRD-05, FG-REL-01, BUG-07) on real PostgreSQL: created categories are active by
default, name keys are unique, products only take a subcategory of their own category (service and composite FK),
an inactive parent hides its children, and the tree follows display order."""

from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Category, Product
from app.modules.catalogue.schemas import CategoryCreate, ProductCreate
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, category_name, subcategory_name

pytestmark = pytest.mark.db


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
