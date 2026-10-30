"""Slice-2 catalogue routes over HTTP: problem+json codes, Idempotency-Key replay, CSV exports through csv_safe,
route declarations, and the 404/403 split for media and taxonomy."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.http.deps import get_actor
from app.platform.authz.context import ActorContext
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

API = "/api/v1/catalogue"
NEW_ROUTES = {
    ("post", "/products"): "catalogue.product.create",
    ("patch", "/products/{product_id}"): "catalogue.product.update",
    ("put", "/products/{product_id}/specification"): "catalogue.product.update",
    ("put", "/products/{product_id}/packaging"): "catalogue.product.update",
    ("post", "/products/{product_id}/archive"): "catalogue.product.archive",
    ("post", "/products/{product_id}/restore"): "catalogue.product.archive",
    ("get", "/products/{product_id}/history"): "catalogue.product.read",
    ("get", "/products/recent"): "catalogue.product.read",
    ("get", "/products/export.csv"): "catalogue.product.export",
    ("get", "/completeness"): "catalogue.product.read",
    ("get", "/products/{product_id}/media"): "catalogue.product.read",
    ("post", "/products/{product_id}/media"): "catalogue.media.manage",
    ("patch", "/media/{media_id}"): "catalogue.media.manage",
    ("post", "/media/{media_id}/make-primary"): "catalogue.media.manage",
    ("delete", "/media/{media_id}"): "catalogue.media.manage",
    ("post", "/media/{media_id}/restore"): "catalogue.media.manage",
    ("post", "/categories"): "catalogue.taxonomy.manage",
    ("post", "/categories/reorder"): "catalogue.taxonomy.manage",
    ("patch", "/categories/{category_id}"): "catalogue.taxonomy.manage",
    ("post", "/categories/{category_id}/subcategories"): "catalogue.taxonomy.manage",
    ("get", "/categories/{category_id}/references"): "catalogue.product.read",
    ("post", "/categories/{category_id}/delete"): "catalogue.taxonomy.manage",
    ("patch", "/subcategories/{subcategory_id}"): "catalogue.taxonomy.manage",
    ("get", "/subcategories/{subcategory_id}/references"): "catalogue.product.read",
    ("post", "/subcategories/{subcategory_id}/delete"): "catalogue.taxonomy.manage",
    ("get", "/taxonomy/validation"): "catalogue.product.read",
    ("get", "/lookups"): "catalogue.lookup.read",
    ("get", "/lookups/types"): "catalogue.lookup.read",
    ("get", "/lookups/export.csv"): "catalogue.lookup.read",
}


@pytest.fixture(scope="module")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI, world: World) -> Iterator[TestClient]:
    def resolve(request: Request) -> ActorContext:
        persona = request.headers.get("x-test-persona", keys.USERS.PRIYA)
        return world.actor(persona).with_(idempotency_key=request.headers.get("idempotency-key"))

    app.dependency_overrides[get_actor] = resolve
    try:
        with TestClient(app, headers={"Origin": get_settings().public_origin}) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    return body


def test_routes_declare_their_permission(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    for (method, path), key in NEW_ROUTES.items():
        op = paths[f"{API}{path}"][method]
        assert op["x-authz"]["kind"] == "permission" and key in op["x-authz"]["permissions"], (method, path)
        assert op["operationId"].startswith("catalogue_")


def test_create_patch_conflict_and_replay(client: TestClient, world: World) -> None:
    body = {
        "product_key": "HTTP-01", "product_name": "=HYPERLINK(\"x\")", "category_id": str(world.ref(keys.CATEGORIES.SERVEWARE)),
        "packaging": {"carton_qty": 24, "master_carton_qty": 12},
    }
    _problem(client.post(f"{API}/products", json=body), 422, "validation_failed")
    body["packaging"] = {"carton_qty": 24}
    first = client.post(f"{API}/products", json=body, headers={"Idempotency-Key": "k-http-01"})
    assert first.status_code == 201, first.text
    again = client.post(f"{API}/products", json=body, headers={"Idempotency-Key": "k-http-01"})
    assert again.status_code == 201 and again.headers.get("Idempotent-Replayed") == "true"
    product = first.json()["product"]
    _problem(client.post(f"{API}/products", json=body), 409, "product_key_exists")
    _problem(client.post(f"{API}/products", json={**body, "product_key": "HTTP-02"},
                         headers={"x-test-persona": keys.USERS.MEERA}), 403, "permission_denied")
    ok = client.patch(f"{API}/products/{product['id']}", json={"expected_version": product["version"], "brand": "LK"})
    assert ok.status_code == 200 and ok.json()["product"]["version"] == product["version"] + 1
    stale = client.patch(f"{API}/products/{product['id']}", json={"expected_version": product["version"], "brand": "X"})
    _problem(stale, 409, "version_conflict")
    _problem(client.patch(f"{API}/products/{product['id']}", json={"expected_version": 2, "product_key": "NEW"}),
             422, "validation_failed")


def test_product_export_is_formula_safe_and_import_compatible(client: TestClient, world: World) -> None:
    client.post(f"{API}/products", json={"product_key": "HTTP-CSV", "product_name": "=1+1",
                                         "category_id": str(world.ref(keys.CATEGORIES.SERVEWARE))})
    r = client.get(f"{API}/products/export.csv", params={"q": "HTTP-CSV"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][:3] == ["product_key", "display_sku", "product_name"]
    assert rows[1][2] == "'=1+1"  # neutralised formula
    _problem(client.get(f"{API}/products/export.csv", headers={"x-test-persona": keys.USERS.MEERA}),
             403, "permission_denied")


def test_taxonomy_delete_refused_while_referenced(client: TestClient, world: World) -> None:
    trays = world.ref(keys.SUBCATEGORIES.TRAYS)
    refs = client.get(f"{API}/subcategories/{trays}/references").json()
    assert refs["total"] >= 1
    body = _problem(client.post(f"{API}/subcategories/{trays}/delete", json={"expected_version": 1}), 409,
                    "taxonomy_referenced")
    assert body["references"]["catalogue_product"] >= 1
    other = client.get(f"{API}/subcategories/00000000-0000-7000-8000-000000000000/references")
    _problem(other, 404, "not_found")


def test_media_routes_404_for_unknown_and_403_for_sales(client: TestClient, world: World) -> None:
    oak = world.ref("OAK_TRAY")
    listed = client.get(f"{API}/products/{oak}/media", headers={"x-test-persona": keys.USERS.MEERA})
    assert listed.status_code == 200 and listed.json()["image"] == []
    attach = client.post(f"{API}/products/{oak}/media", json={"file_id": str(oak), "media_type": "image"},
                         headers={"x-test-persona": keys.USERS.MEERA})
    _problem(attach, 403, "permission_denied")
    _problem(client.post(f"{API}/products/{oak}/media", json={"file_id": str(oak), "media_type": "image"}),
             404, "not_found")  # an unknown file id for an admin
    _problem(client.delete(f"{API}/media/{oak}", params={"expected_version": 1, "reason": "x"}), 404, "not_found")


def test_lookup_routes_need_the_lookup_key(client: TestClient) -> None:
    assert client.get(f"{API}/lookups").json()["total"] == 0
    _problem(client.get(f"{API}/lookups", headers={"x-test-persona": keys.USERS.MEERA}), 403, "permission_denied")
    csv_body = client.get(f"{API}/lookups/export.csv").content.decode("utf-8")
    assert csv_body.lstrip("﻿").startswith('"lookup_type","key_1","key_2"')
