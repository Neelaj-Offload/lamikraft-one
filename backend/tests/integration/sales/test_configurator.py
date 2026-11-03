"""The quote configurator (LM-43, API-34, UI-60, LP-06.1): filters narrow the options before paging, facets cover the
whole filtered set, ``exact_match`` names a single hit, and each row is priced for the customer with its
order-value recommendation (never labelled MOQ)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.errors import Forbidden
from app.modules.sales import service as sales
from app.modules.sales.configurator import ConfiguratorRequest
from app.seed.world import keys
from tests.integration.sales.http import API, as_, problem
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, KABIR = keys.USERS.MEERA, keys.USERS.KABIR


def test_filters_narrow_options_page_and_exact_match(world: SalesWorld) -> None:
    with world.uow(MEERA) as uow:
        everything = sales.configurator_resolve(uow, ConfiguratorRequest(party_id=world.ref("NORDHAUS"), currency="EUR"))
        trays = sales.configurator_resolve(uow, ConfiguratorRequest(party_id=world.ref("NORDHAUS"), currency="EUR",
                                                                    category_id=world.ref(keys.CATEGORIES.SERVEWARE)))
        exact = sales.configurator_resolve(uow, ConfiguratorRequest(party_id=world.ref("NORDHAUS"), currency="EUR", q="LK-OT-0450"))
        paged = sales.configurator_resolve(uow, ConfiguratorRequest(currency="EUR", limit=1, offset=1))
        literal = sales.configurator_resolve(uow, ConfiguratorRequest(currency="EUR", q="%_"))
    assert everything.total >= trays.total > 0 and len(paged.items) == 1 and paged.total == everything.total
    assert sum(f.count for f in trays.facets.brands) == trays.total == trays.facets.total  # narrowed by the category
    assert next(f.count for f in trays.facets.categories if f.label == "Serveware") == trays.total  # own options stay visible
    assert exact.total == 1 and exact.exact_match == world.ref("OAK_TRAY")
    row = exact.items[0]
    assert row.price is not None and row.price.status == "found" and row.price.unit_price.amount == Decimal("24.0000")  # type: ignore[union-attr]
    assert row.price.price_list_code == keys.PRICE_LISTS.EXP_EUR and not row.price.converted_with_fx
    assert row.recommendation is not None and row.recommendation.quantity is not None
    assert row.recommendation.quantity.value == Decimal("216") and row.recommendation.label.startswith("Order-value recommendation")
    assert literal.total == 0 and literal.exact_match is None
    with world.uow(MEERA) as uow:  # USD has no list: unpriced rows say why (no relabelled EUR figure)
        usd = sales.configurator_resolve(uow, ConfiguratorRequest(currency="USD", q="LK-OT-0450"))
    assert usd.items[0].price is not None and usd.items[0].price.unit_price is None and usd.items[0].price.reason_code
    with pytest.raises(Forbidden), world.uow(KABIR) as uow:  # no sales.quote.read
        sales.configurator_resolve(uow, ConfiguratorRequest(currency="EUR"))


def test_packaging_summary_from_canonical_fields(world: SalesWorld) -> None:
    """FG-QLN-12 / FG-PKG-11: the configurator row's packaging summary reads only the canonical columns
    (``unit_weight_g`` / ``carton_qty`` / ``packing_type``), batched for the page."""
    with world.uow(MEERA) as uow:
        exact = sales.configurator_resolve(uow, ConfiguratorRequest(currency="EUR", q="LK-OT-0450"))
        page = sales.configurator_resolve(uow, ConfiguratorRequest(currency="EUR", limit=50))
    assert exact.items[0].packaging_summary == "450g · 24/ctn · Poly bag"
    assert exact.items[0].product.carton_qty == 24
    summaries = {row.product.id: row.packaging_summary for row in page.items}
    assert summaries[world.ref("OAK_TRAY")] == "450g · 24/ctn · Poly bag"


def test_configurator_over_http(sales_client: TestClient, sales_world: SalesWorld) -> None:
    """API-34: the route is a POST with a JSON body (no Idempotency-Key: it changes nothing), DecimalStr money,
    422 on unknown fields, 403 without ``sales.quote.read``."""
    body = {"party_id": str(sales_world.ref("NORDHAUS")), "currency": "EUR", "q": "LK-OT-0450"}
    res = sales_client.post(f"{API}/sales/quotes/configurator/resolve", json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["exact_match"] == str(sales_world.ref("OAK_TRAY")) and data["currency"] == "EUR"
    row = data["items"][0]
    assert row["price"]["unit_price"] == {"amount": "24.0000", "currency": "EUR"}
    assert row["packaging_summary"] == "450g · 24/ctn · Poly bag"
    assert set(data["facets"]) >= {"categories", "families", "sizes", "thicknesses", "decors", "finishes"}
    problem(sales_client.post(f"{API}/sales/quotes/configurator/resolve", json={**body, "page": 0}), 422, "validation_failed")
    problem(sales_client.post(f"{API}/sales/quotes/configurator/resolve", json=body, headers=as_(KABIR)), 403, "permission_denied")
