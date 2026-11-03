"""PARITY LM-96 / API-66 / LP-11.1 / API-24: grouped global search over the seeded world with deep links,
filtered by each person's permissions and record scope; recent searches keep the newest ten per person."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.seed.world import keys
from tests.integration.identity.fixtures import api_app, client, origin_headers, world  # noqa: F401

pytestmark = pytest.mark.db


def _as(app, key: str) -> TestClient:  # type: ignore[no-untyped-def]
    c = TestClient(app, base_url="http://testserver")
    assert c.post("/api/v1/_test/sign-in", json={"user_key": key}, headers=origin_headers()).status_code == 200
    return c


def _groups(c: TestClient, q: str, **params: object) -> dict[str, dict]:  # type: ignore[type-arg]
    r = c.get("/api/v1/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return {g["resource_type"]: g for g in r.json()["groups"]}


def test_grouped_scoped_results_with_deep_links(client: TestClient, world) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    meera = _as(client.app, "MEERA")
    oak = _groups(meera, "oak")
    assert "catalogue.product" in oak
    product = oak["catalogue.product"]
    assert product["group"] == "Products" and product["hits"]
    assert all(h["path"].startswith("/") and "://" not in h["path"] for h in product["hits"])  # in-app deep links
    assert any(keys.PRODUCTS.OAK_TRAY in h["title"] for h in product["hits"])

    people = _groups(meera, keys.PEOPLE["NEHA"].name.split()[0])
    assert people["org.person"]["hits"][0]["title"] == keys.PEOPLE["NEHA"].name
    assert "@" not in str(people["org.person"]["hits"][0])  # never contact details

    # types restricts the groups; offset pages one group only
    only = _groups(meera, "oak", types="catalogue.product")
    assert set(only) == {"catalogue.product"}
    assert meera.get("/api/v1/search", params={"q": "oak", "offset": 5}).status_code == 422

    # the restricted warehouse assistant sees no party group (no parties.party.read); totals are scoped too
    kabir = _as(client.app, "KABIR")
    first_party = keys.PARTY_NAMES["NORDHAUS"].split()[0]
    assert "parties.party" not in _groups(kabir, first_party)
    assert "parties.party" in _groups(_as(client.app, "SAHIL"), first_party)


def test_last_ten_kept_per_user(client: TestClient, world, frozen_clock) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    meera = _as(client.app, "MEERA")
    headers = {**origin_headers(), "X-CSRF-Token": meera.cookies.get("lk_csrf") or ""}
    for i in range(12):
        frozen_clock.advance(seconds=1)
        assert meera.post("/api/v1/search/recent", json={"query": f"oak {i}"}, headers=headers).status_code == 201
    frozen_clock.advance(seconds=1)
    meera.post("/api/v1/search/recent", json={"query": "OAK 5"}, headers=headers)  # a repeat moves to the top
    recent = [r["query"] for r in meera.get("/api/v1/search/recent").json()]
    assert len(recent) == 10 and recent[0] == "OAK 5" and "oak 0" not in recent and "oak 1" not in recent
    neha = _as(client.app, "NEHA")
    assert neha.get("/api/v1/search/recent").json() == []
