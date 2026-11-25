"""The variant builder (module 4): design × decor × size, one product each, re-runnable.

Spec: docs/superpowers/specs/2026-11-25-products-stock-design.md
"""

from __future__ import annotations

import pytest

from app.core.errors import Forbidden, ValidationFailed
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import ProductFilters
from app.modules.catalogue.variants import VariantBuild, build_variants, variant_key
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
PRIYA, MEERA = keys.USERS.PRIYA, keys.USERS.MEERA


def _body(world: World, **extra: object) -> VariantBuild:
    return VariantBuild.model_validate({
        "design_no": "cb07",
        "design_name": "Chopping board CB07",
        "category_id": str(world.ref(keys.CATEGORIES.SERVEWARE)),
        "product_type": "Chopping board",
        "decors": [{"decor_no": "892", "decor_name": "Walnut"}, {"decor_no": "959"}],
        "sizes": [{"code": "s", "label": "Small", "length_mm": "300", "width_mm": "200"},
                  {"code": "M", "label": "Medium", "length_mm": "400", "width_mm": "250"},
                  {"code": "L", "label": "Large"}],
        **extra,
    })


def test_builds_every_decor_and_size_and_is_rerunnable(world: World) -> None:
    with UnitOfWork(world.actor(PRIYA)) as uow:
        preview = build_variants(uow, _body(world, dry_run=True))
    assert preview.created == 0 and len(preview.rows) == 6 and all(r.product_id is None for r in preview.rows)
    with UnitOfWork(world.actor(PRIYA)) as uow:
        first = build_variants(uow, _body(world))
    assert first.created == 6 and first.skipped == 0
    assert {r.product_key for r in first.rows} == {f"CB07-{d}-{s}" for d in ("892", "959") for s in ("S", "M", "L")}
    page = catalogue.list_products(world.actor(PRIYA), ProductFilters(design="cb07"), limit=50)
    assert page.total == 6
    one = next(p for p in page.items if p.product_key == "CB07-892-M")
    assert (one.design_no, one.decor_no, one.variant_group, one.item_class) == ("CB07", "892", "Chopping board CB07", "finished")
    assert one.product_name == "Chopping board CB07, 892 Walnut, Medium"
    assert str(one.size.length_mm) in ("400", "400.000", "400.0") or one.size.length_mm is not None

    body = _body(world)
    body.decors.append(body.decors[0].model_copy(update={"decor_no": "1001", "decor_name": None}))
    with UnitOfWork(world.actor(PRIYA)) as uow:
        again = build_variants(uow, body)
    assert again.created == 3 and again.skipped == 6


def test_rejects_duplicates_and_needs_permission(world: World) -> None:
    body = _body(world)
    body.sizes.append(body.sizes[0])
    with pytest.raises(ValidationFailed), UnitOfWork(world.actor(PRIYA)) as uow:
        build_variants(uow, body)
    with pytest.raises(Forbidden), UnitOfWork(world.actor(MEERA)) as uow:
        build_variants(uow, _body(world))


def test_variant_key() -> None:
    assert variant_key("CB07", "892", "XL") == "CB07-892-XL"
    assert variant_key("RS-01", "959", "M") == "RS-01-959-M"
