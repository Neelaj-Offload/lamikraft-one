"""The lane's HTTP routes end to end (FastAPI app, problem+json, DecimalStr, Idempotency-Key, route declarations).

The identity lane owns session authentication; here the authenticated actor dependency resolves the persona named in
the ``x-test-persona`` header, exactly as a session would resolve it (permissions from the role template).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas

pytestmark = pytest.mark.db

API = "/api/v1"
EXPECTED_OPERATIONS = {
    ("get", "/catalogue/products"): "catalogue_list_products",
    ("get", "/catalogue/products/facets"): "catalogue_get_product_facets",
    ("get", "/catalogue/products/stats"): "catalogue_get_product_stats",
    ("get", "/catalogue/products/completeness"): "catalogue_get_product_completeness",
    ("get", "/catalogue/products/lookup"): "catalogue_get_product_by_key",
    ("get", "/catalogue/products/{product_id}"): "catalogue_get_product",
    ("get", "/catalogue/categories"): "catalogue_list_categories",
    ("get", "/parties/parties"): "parties_list_parties",
    ("post", "/parties/parties"): "parties_create_party",
    ("get", "/parties/parties/lookup"): "parties_get_party_by_number",
    ("get", "/parties/parties/{party_id}"): "parties_get_party",
    ("patch", "/parties/parties/{party_id}"): "parties_update_party",
    ("get", "/pricing/price-lists"): "pricing_list_price_lists",
    ("get", "/pricing/price-lists/{price_list_id}"): "pricing_get_price_list",
    ("get", "/pricing/price-lists/{price_list_id}/items"): "pricing_list_price_list_items",
    ("get", "/pricing/products/{product_id}/prices"): "pricing_list_product_prices",
    ("get", "/pricing/products/{product_id}/costs"): "pricing_list_product_costs",
    ("get", "/pricing/resolve"): "pricing_resolve_price",
    ("get", "/commercial/rule-sets"): "commercial_list_rule_sets",
    ("get", "/commercial/rule-sets/{rule_set_id}"): "commercial_get_rule_set",
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI, world: World) -> Iterator[TestClient]:
    worlds = {"": world}

    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.MEERA)
        which = worlds[request.headers.get("x-test-world", "")]
        return which.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))

    app.dependency_overrides[get_actor] = resolve
    app.state.test_worlds = worlds
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _as(persona: str, **extra: str) -> dict[str, str]:
    return {"x-test-persona": persona, **extra}


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code


def test_operation_ids_and_route_declarations(app: FastAPI) -> None:
    spec = app.openapi()
    for (method, path), operation_id in EXPECTED_OPERATIONS.items():
        op = spec["paths"][f"{API}{path}"][method]
        assert op["operationId"] == operation_id
        assert op["x-authz"]["kind"] == "permission"
    assert spec["paths"][f"{API}/parties/parties"]["post"]["x-authz"]["permissions"] == ["parties.party.create"]
    assert spec["paths"][f"{API}/pricing/products/{{product_id}}/costs"]["get"]["x-authz"]["permissions"] == ["pricing.cost.read"]


def test_catalogue_routes(client: TestClient, world: World) -> None:
    r = client.get(f"{API}/catalogue/products", params={"thickness": "18", "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 1 and body["limit"] == 1
    assert isinstance(body["items"][0]["thickness_mm"], str)
    r = client.get(f"{API}/catalogue/products", params={"q": "tray", "status": ["active", "inactive"]})
    assert [p["product_key"] for p in r.json()["items"]] == [keys.PRODUCTS.OAK_TRAY]
    _problem(client.get(f"{API}/catalogue/products", params={"thickness": "thin"}), 422, "validation_failed")
    oak = client.get(f"{API}/catalogue/products/{world.ref('OAK_TRAY')}").json()
    assert oak["packaging"]["cbm"] == "0.047520" and oak["packaging"]["carton_qty"] == 24
    assert oak["specification"]["thickness_mm"] == "12" and oak["decor"]["decor_no"] == "0120"
    assert [s["key"] for s in oak["sections"]][:3] == ["overview", "specifications", "packaging"]
    by_key = client.get(f"{API}/catalogue/products/lookup", params={"product_key": keys.PRODUCTS.OAK_TRAY})
    assert by_key.json()["id"] == str(world.ref("OAK_TRAY"))
    for path in ("products/facets", "products/stats", "products/completeness", "categories"):
        assert client.get(f"{API}/catalogue/{path}").status_code == 200
    _problem(client.get(f"{API}/catalogue/products/{uuid.uuid7()}"), 404, "not_found")
    other = build_personas()
    client.app.state.test_worlds["other"] = other  # type: ignore[attr-defined]
    _problem(client.get(f"{API}/catalogue/products/{world.ref('OAK_TRAY')}",
                        headers={"x-test-world": "other", "x-test-persona": keys.USERS.SAHIL}), 404, "not_found")


def test_party_routes_scope_idempotency_and_versions(client: TestClient, world: World) -> None:
    listed = client.get(f"{API}/parties/parties").json()
    assert sorted(p["party_number"] for p in listed["items"]) == [keys.PARTIES.NORDHAUS, keys.PARTIES.MAISON, keys.PARTIES.BERG]
    _problem(client.get(f"{API}/parties/parties/{world.ref('THORNBURY')}"), 404, "not_found")
    nordhaus = client.get(f"{API}/parties/parties/{world.ref('NORDHAUS')}", headers=_as(keys.USERS.RAVI)).json()
    _problem(client.patch(f"{API}/parties/parties/{world.ref('NORDHAUS')}", headers=_as(keys.USERS.RAVI),
                          json={"expected_version": nordhaus["version"], "display_name": "x"}), 403, "permission_denied")

    body = {"legal_name": "Fjord Interiør AS", "country_code": "no", "default_currency": "EUR", "roles": ["customer"],
            "customer_type": "standard"}
    key = str(uuid.uuid7())
    first = client.post(f"{API}/parties/parties", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text
    replay = client.post(f"{API}/parties/parties", json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 201 and replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["id"] == first.json()["id"] and first.json()["party_number"] == "P-00005"
    assert client.get(f"{API}/parties/parties").json()["total"] == 4  # created once
    _problem(client.post(f"{API}/parties/parties", json={**body, "legal_name": "Other AS"}, headers={"Idempotency-Key": key}),
             422, "idempotency_key_reused")

    party = first.json()
    updated = client.patch(f"{API}/parties/parties/{party['id']}",
                           json={"expected_version": party["version"], "display_name": "Fjord"})
    assert updated.status_code == 200 and updated.json()["version"] == party["version"] + 1
    _problem(client.patch(f"{API}/parties/parties/{party['id']}",
                          json={"expected_version": party["version"], "display_name": "Stale"}), 409, "version_conflict")
    _problem(client.post(f"{API}/parties/parties", json={**body, "default_currency": 5.0}), 422, "validation_failed")
    lookup = client.get(f"{API}/parties/parties/lookup", params={"party_number": keys.PARTIES.NORDHAUS})
    assert lookup.json()["legal_name"] == keys.PARTY_NAMES["NORDHAUS"]


def test_pricing_and_commercial_routes(client: TestClient, world: World) -> None:
    r = client.get(f"{API}/pricing/resolve", params={
        "product_id": str(world.ref("OAK_TRAY")), "currency": "EUR", "uom": "pcs", "party_id": str(world.ref("NORDHAUS")),
    })
    assert r.status_code == 200
    resolution = r.json()
    assert resolution["unit_price"] == keys.PRICES.OAK_TRAY_EUR and resolution["tier"] == "standard"
    assert resolution["price_list_code"] == keys.PRICE_LISTS.EXP_EUR
    _problem(client.get(f"{API}/pricing/resolve", params={
        "product_id": str(world.ref("OAK_TRAY")), "currency": "GBP", "uom": "pcs", "party_id": str(world.ref("THORNBURY")),
    }), 404, "not_found")
    lists = client.get(f"{API}/pricing/price-lists").json()
    assert lists["total"] == 3
    items = client.get(f"{API}/pricing/price-lists/{world.ref('PL_EXP_EUR')}/items").json()
    assert {i["unit_price"] for i in items["items"]} == {"18.0000", "9.5000", "24.0000"}
    prices = client.get(f"{API}/pricing/products/{world.ref('OAK_TRAY')}/prices").json()
    assert prices["current_cost"] is None and prices["redacted_fields"] == ["current_cost"]
    _problem(client.get(f"{API}/pricing/products/{world.ref('OAK_TRAY')}/costs"), 403, "permission_denied")
    assert client.get(f"{API}/pricing/products/{world.ref('OAK_TRAY')}/costs", headers=_as(keys.USERS.SAHIL)).json() == []
    _problem(client.get(f"{API}/commercial/rule-sets"), 403, "permission_denied")
    rule_sets = client.get(f"{API}/commercial/rule-sets", headers=_as(keys.USERS.SAHIL)).json()
    assert rule_sets[0]["params"]["thresholds"]["EUR"] == {"minimum_order_value": "5000.00", "surcharge_amount": "400.00"}
