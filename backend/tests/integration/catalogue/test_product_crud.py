"""Product identity (FG-PRD-01): ``product_key`` is the immutable business key — not accepted on update by the API
schema, refused by the service contract and by the database trigger ``trg_catalogue_product_key_immutable``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, ValidationFailed, VersionConflict
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
            product_key="TST-SCALE", product_name="Scale", category_id=world.ref(keys.CATEGORIES.SERVEWARE), unit_of_sale="pcs",
            specification=SpecificationIn.model_validate(spec) if spec else None,
            packaging=PackagingIn.model_validate(packaging) if packaging else None,
        ))
    assert [(e["loc"], e["code"]) for e in excinfo.value.extra["errors"]] == [(["body", *loc], code)]


# ---- Slice 2: the HTTP form commands (LM-16..18, LM-20, LM-21, API-14..19) -----------------------------------------
def _full_create(world: World, key: str = "TST-FORM-01") -> ProductCreate:
    return ProductCreate.model_validate(
        {
            "product_key": key,
            "product_name": "Form tray",
            "display_sku": "FT-01",
            "brand": "LK",
            "category_id": str(world.ref(keys.CATEGORIES.SERVEWARE)),
            "subcategory_id": str(world.ref(keys.SUBCATEGORIES.TRAYS)),
            "unit_of_sale": "pcs",
            "size_mm": "400 x 250",
            "decor_no": "0120",
            "decor_options": ["0310", "120.0"],
            "finish": "Oiled",
            "status": "under_development",
            "specification": {
                "length_mm": "400", "width_mm": "25 cm", "thickness_mm": "0.80", "board_size_mm": "2440*1220*18",
            },
            "packaging": {"master_carton_qty": "24.0", "unit_weight_kg": "0.45", "unit_packing_type": "Poly bag"},
        }
    )


def test_create_with_all_sections(world: World) -> None:
    from app.modules.catalogue import products

    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result, replayed = products.create_product_command(uow, _full_create(world))
    detail = result.product
    assert not replayed and detail.version == 1 and detail.provenance.origin == "ui"
    assert detail.decor.decor_no == "0120" and detail.decor.decor_options == ["0310", "120"]
    assert any(w.startswith("decor_options[1]:DECOR_FLOAT_ARTEFACT_NORMALISED") for w in result.warnings)
    assert detail.specification is not None and str(detail.specification.width_mm) == "250"
    assert str(detail.specification.thickness_mm) == "0.8"
    assert detail.packaging is not None and detail.packaging.carton_qty == 24
    assert str(detail.packaging.unit_weight_g) == "450"
    assert detail.packaging.packing_type == "Poly bag"
    assert {d.kind.value for d in detail.dimensions} == {"master_size", "board_size"}
    assert detail.capabilities["archive"].allowed and not detail.capabilities["restore"].allowed
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        products.create_product_command(uow, _full_create(world))
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        products.create_product_command(uow, _full_create(world, "TST-FORM-02"))


def test_update_sections_with_version_conflict_409(world: World) -> None:
    from app.modules.catalogue import products

    pid = world.ref("OAK_TRAY")
    detail = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid)
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result, _ = products.update_product_command(
            uow, pid, ProductUpdate(expected_version=detail.version, product_name="Oak tray 450 (oiled)")
        )
    assert result.product.version == detail.version + 1
    with pytest.raises(VersionConflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        products.update_product_command(uow, pid, ProductUpdate(expected_version=detail.version, finish="x"))
    with pytest.raises(VersionConflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        products.put_packaging(
            uow, pid, products.PackagingPut(expected_version=detail.version, packaging=PackagingIn(carton_qty=12))
        )
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        products.update_product_command(uow, pid, ProductUpdate(expected_version=result.product.version, finish="x"))


def test_specification_put_parses_dimensions(world: World) -> None:
    from app.modules.catalogue import products

    pid = world.ref("OAK_TRAY")
    version = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid).version
    spec = SpecificationIn(
        length_mm="45 cm", width_mm="300", thickness_mm="12", size_mm="12\" x 8\"", working_size_mm="300-350",
        plate1_size_mm="Ø 300",
    )
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result = products.put_specification(
            uow, pid, products.SpecificationPut(expected_version=version, specification=spec)
        )
    d = result.product
    assert d.version == version + 1
    assert d.specification is not None and str(d.specification.length_mm) == "450"
    assert d.specification.length_mm_source == "45 cm"
    dims = {x.kind.value: x for x in d.dimensions}
    assert str(dims["spec_size"].length_mm) == "304.8" and str(dims["spec_size"].width_mm) == "203.2"
    assert dims["working_size"].parse_status.value == "unparsed"
    assert str(dims["plate_1_size"].diameter_mm) == "300"


def test_packaging_put_canonicalises_aliases(world: World) -> None:
    from app.modules.catalogue import products

    pid = world.ref("OAK_TRAY")
    version = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid).version
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        result = products.put_packaging(
            uow,
            pid,
            products.PackagingPut(
                expected_version=version,
                packaging=PackagingIn(carton_qty=24, master_carton_qty="24.0", unit_weight_g="450", unit_weight_kg="0.45"),
            ),
        )
    pack = result.product.packaging
    assert pack is not None and pack.carton_qty == 24 and str(pack.unit_weight_g) == "450"
    assert pack.alias_provenance and "carton_qty" in pack.alias_provenance
    with pytest.raises(ValidationFailed) as exc, UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        products.put_packaging(
            uow,
            pid,
            products.PackagingPut(
                expected_version=result.product.version, packaging=PackagingIn(carton_qty=24, master_carton_qty=12)
            ),
        )
    assert exc.value.extra["errors"][0]["code"] == "alias_conflict"


def test_packaging_one_row_per_product(world: World) -> None:
    from sqlalchemy import func, select

    from app.modules.catalogue import products
    from app.modules.catalogue.models import ProductPackaging, ProductSpecification

    pid = world.ref("OAK_TRAY")
    for thickness in ("18", "19"):
        version = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid).version
        with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
            products.put_packaging(
                uow, pid, products.PackagingPut(expected_version=version, packaging=PackagingIn(carton_qty=12))
            )
        version = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid).version
        with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
            products.put_specification(
                uow,
                pid,
                products.SpecificationPut(expected_version=version, specification=SpecificationIn(thickness_mm=thickness)),
            )
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        packs = select(func.count()).select_from(ProductPackaging).where(ProductPackaging.product_id == pid)
        specs = select(func.count()).select_from(ProductSpecification).where(ProductSpecification.product_id == pid)
        assert uow.session.scalar(packs) == 1 and uow.session.scalar(specs) == 1


def test_specification_one_row_per_product(world: World) -> None:
    test_packaging_one_row_per_product(world)


def test_archive_restore_and_no_hard_delete_via_ui(world: World) -> None:
    from app.main import create_app
    from app.modules.catalogue import products
    from app.modules.catalogue.schemas import ProductFilters

    pid = world.ref("MAPLE_TRIVET")
    detail = catalogue.get_product(world.actor(keys.USERS.PRIYA), pid)
    with pytest.raises(Forbidden), UnitOfWork(world.actor(keys.USERS.SAHIL)) as uow:
        products.set_archived(uow, pid, products.ArchiveRequest(expected_version=detail.version), archived=True)
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        archived = products.set_archived(
            uow, pid, products.ArchiveRequest(expected_version=detail.version, reason="discontinued"), archived=True
        )
    assert archived.archived_at is not None and archived.capabilities["restore"].allowed
    assert archived.capabilities["update"].reason_code == "product_archived"
    listed = {p.id for p in catalogue.list_products(world.actor(keys.USERS.PRIYA), ProductFilters()).items}
    assert pid not in listed
    with pytest.raises(Conflict), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        products.update_product_command(uow, pid, ProductUpdate(expected_version=archived.version, finish="x"))
    with UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:
        restored = products.set_archived(
            uow, pid, products.ArchiveRequest(expected_version=archived.version), archived=False
        )
    assert restored.archived_at is None
    history = products.product_history(world.actor(keys.USERS.PRIYA), pid)
    assert [h.action for h in history.items][:2] == ["catalogue.product.restored", "catalogue.product.archived"]
    assert history.items[1].reason == "discontinued"
    # no route deletes a product: archive/restore are the only lifecycle endpoints
    paths = create_app().openapi()["paths"]
    assert all("delete" not in ops for path, ops in paths.items() if path.startswith("/api/v1/catalogue/products"))
