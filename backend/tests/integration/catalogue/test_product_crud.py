"""Product identity (FG-PRD-01): ``product_key`` is the immutable business key — not accepted on update by the API
schema, refused by the service contract and by the database trigger ``trg_catalogue_product_key_immutable``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.core.errors import ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.models import Product
from app.modules.catalogue.schemas import PackagingIn, ProductCreate, ProductUpdate, SpecificationIn
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def test_product_key_immutable_api_and_db_trigger(world: World) -> None:
    with pytest.raises(ValidationError):  # the update schema has no product_key (extra="forbid")
        ProductUpdate.model_validate({"expected_version": 1, "product_key": "LK-OT-9999"})
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result = catalogue.update_product(uow, world.ref("OAK_TRAY"), ProductUpdate(expected_version=1, finish="Oiled"))
    assert result.product.product_key == keys.PRODUCTS.OAK_TRAY and result.product.version == 2
    with pytest.raises(DBAPIError, match="immutable"), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        uow.session.execute(update(Product).where(Product.id == world.ref("OAK_TRAY")).values(product_key="LK-OT-9999"))
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # other columns still update normally
        uow.session.execute(update(Product).where(Product.id == world.ref("OAK_TRAY")).values(internal_remarks="ok"))
    detail = catalogue.get_product(world.actor(keys.USERS.PRIYA), world.ref("OAK_TRAY"))
    assert detail.product_key == keys.PRODUCTS.OAK_TRAY and detail.internal_remarks == "ok"


@pytest.mark.parametrize(
    ("spec", "packaging", "loc", "code"),
    [
        ({"thickness_mm": "0.0004"}, None, ["specification", "thickness_mm"], "below_precision"),
        ({"length_mm": "0.0004"}, None, ["specification", "length_mm"], "below_precision"),
        ({"length_mm": "1000000000"}, None, ["specification", "length_mm"], "too_large"),
        (None, {"cbm": "0.0000001"}, ["packaging", "cbm"], "below_precision"),
        (None, {"net_weight_kg": "0.00001"}, ["packaging", "net_weight_kg"], "below_precision"),
        (None, {"carton_length_cm": "1000000000"}, ["packaging", "carton_length_cm"], "too_large"),
    ],
)
def test_values_outside_the_column_scale_are_a_422_not_a_db_error(
    world: World, spec: dict[str, str] | None, packaging: dict[str, str] | None, loc: list[str], code: str
) -> None:
    """A positive value below the column scale would be stored as zero and break the positive CHECK (a 500); an
    oversized one would overflow the NUMERIC column. Both are field errors."""
    with pytest.raises(ValidationFailed) as excinfo, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        catalogue.create_product(uow, ProductCreate(
            product_key="TST-SCALE", product_name="Scale", category_id=world.ref("CAT_SERVEWARE"), unit_of_sale="pcs",
            specification=SpecificationIn.model_validate(spec) if spec else None,
            packaging=PackagingIn.model_validate(packaging) if packaging else None,
        ))
    assert [(e["loc"], e["code"]) for e in excinfo.value.extra["errors"]] == [(["body", *loc], code)]
