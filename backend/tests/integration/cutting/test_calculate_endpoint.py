"""The stateless calculation (API-51) and catalogue autocomplete (LM-79, API-52, LP-09.1): legacy parity of inputs
and outputs, scope of the product search, and the synchronous limit."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.seed.world import keys
from tests.integration.cutting.helpers import API, CUT_LIST, as_, item, problem
from tests.integration.sales.world import SalesWorld


def test_stateless_calculate_parity(client: TestClient) -> None:
    r = client.post(f"{API}/calculate", json={"items": CUT_LIST}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 200, r.text
    body = r.json()
    # legacy outputs per (decor, thickness) group: boards, placed vs required, efficiency, scrap, used/sheet area,
    # per-SKU produced, unfit and per-board placements {sku, x, y, w, h, rotated} plus leftovers
    assert [(g["decor_key"], g["thickness_mm"]) for g in body["groups"]] == [("0120", "18"), ("W-7", "18")]
    for g in body["groups"]:
        assert g["board_count"] == len(g["boards"]) >= 1
        assert {"efficiency_usable_pct", "scrap_pct", "placed_area_mm2", "usable_area_mm2", "raw_area_mm2"} <= set(g)
        for b in g["boards"]:
            assert b["svg_path"] is None
            assert {"x_mm", "y_mm", "along_length_mm", "along_width_mm", "rotated", "sku"} <= set(b["placements"][0])
            assert all(o["length_mm"] and o["width_mm"] for o in b["offcuts"])
    totals = body["totals"]
    assert (totals["required"], totals["placed_required"], totals["produced"], totals["unfit"]) == (13, 13, 13, 0)
    assert body["settings"]["board_length_mm"] == "2440" and body["note"] == "Heuristic layout, not guaranteed optimal"
    # nothing is stored
    assert client.get(f"{API}/plans").json()["total"] == 0
    # identical input gives an identical result hash
    assert client.post(f"{API}/calculate", json={"items": CUT_LIST}).json()["result_hash"] == body["result_hash"]


def test_stateless_calculate_limits_and_permissions(client: TestClient) -> None:
    big = problem(client.post(f"{API}/calculate", json={"items": [item("X", "100", "100", 301)]}), 422, "validation_failed")
    assert big["errors"][0]["code"] == "cutting_sync_limit_exceeded"
    problem(client.post(f"{API}/calculate", json={"items": CUT_LIST}, headers=as_(keys.USERS.KABIR)), 403, "permission_denied")
    floats = client.post(f"{API}/calculate", json={"items": [{**item("F", "100", "100", 1), "length_mm": 100.5}]})
    assert floats.status_code == 422


def test_product_autocomplete_fills_decor_thickness_dimensions(client: TestClient, world: SalesWorld) -> None:
    r = client.get(f"{API}/products", params={"search": keys.PRODUCTS.OAK_TRAY}, headers=as_(keys.USERS.MEERA))
    assert r.status_code == 200, r.text
    rows = r.json()
    oak = next(p for p in rows if p["product_key"] == keys.PRODUCTS.OAK_TRAY)
    assert oak["decor"] == keys.DECORS.NATURAL_OAK and oak["decor_key"] == keys.DECORS.NATURAL_OAK
    assert (oak["thickness_mm"], oak["length_mm"], oak["width_mm"]) == ("12", "450", "300")
    assert oak["grain_locked"] is False
    client.post(f"{API}/grain-locks", json={"decor": keys.DECORS.NATURAL_OAK}, headers=as_(keys.USERS.PRIYA))
    again = client.get(f"{API}/products", params={"search": keys.PRODUCTS.OAK_TRAY}).json()
    assert next(p for p in again if p["product_key"] == keys.PRODUCTS.OAK_TRAY)["grain_locked"] is True
    assert client.get(f"{API}/products", params={"search": "  "}).json() == []
    problem(client.get(f"{API}/products", params={"search": "oak"}, headers=as_(keys.USERS.KABIR)), 403, "permission_denied")
    # the filled row is a valid cut-list item
    plan = client.post(f"{API}/plans", json={"name": "From catalogue", "items": [
        {"product_id": oak["product_id"], "sku": oak["product_key"], "decor": oak["decor"], "thickness_mm": oak["thickness_mm"],
         "length_mm": oak["length_mm"], "width_mm": oak["width_mm"], "quantity": 2}]})
    assert plan.status_code == 201, plan.text
    assert plan.json()["items"][0]["product_id"] == oak["product_id"]
    unknown = problem(client.post(f"{API}/plans", json={"name": "x", "items": [
        {**item("Y", "100", "100", 1), "product_id": "0192a000-0000-7000-8000-000000000009"}]}), 422, "validation_failed")
    assert unknown["errors"][0]["code"] == "product_not_found"
