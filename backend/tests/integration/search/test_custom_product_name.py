"""BUG-08 / SCN-G5 / FG-CP-08: global search finds custom products by ``product_name`` (the legacy search used a
non-existent ``name`` column), scoped to what the actor may read; quotes and samples are searchable too."""

from __future__ import annotations

import pytest

from app.modules.sales import service as sales
from app.modules.sales.schemas import CustomProductCreate
from app.platform.search import service as search
from app.seed.world import keys
from tests.integration.catalogue.world import member_actors, personas  # noqa: F401
from tests.integration.sales.world import SalesWorld, world  # noqa: F401

pytestmark = pytest.mark.db


def test_global_search_finds_custom_product_name(world: SalesWorld) -> None:  # noqa: F811
    with world.uow(keys.USERS.MEERA) as uow:
        custom = sales.create_custom_product(uow, CustomProductCreate(product_name="Mango wood cheese board", decor_no="0777"))
        code = custom.custom_code
    q = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(keys.USERS.MEERA) as uow:
        results = search.search(uow, "cheese board")
        by_code = search.search(uow, code)
        quotes = search.search(uow, q.quote_number)
    group = next(g for g in results.groups if g.resource_type == "sales.custom_product")
    assert [h.title for h in group.hits] == [f"{code} · Mango wood cheese board"] and group.hits[0].path == f"/sales/custom-products/{custom.id}"
    assert next(g for g in by_code.groups if g.resource_type == "sales.custom_product").hits[0].resource_id == custom.id
    assert next(g for g in quotes.groups if g.resource_type == "sales.quote").hits[0].resource_id == q.id
    with world.uow(keys.USERS.NEHA) as uow:  # another owner's custom product never appears
        assert all(g.resource_type != "sales.custom_product" for g in search.search(uow, "cheese board").groups)
