"""Test-support router (mounted because the suite runs with LK_ENV=test)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import origin_headers, test_sign_in

pytestmark = pytest.mark.db


def test_sign_in_by_fixture_key_creates_a_real_session(client: TestClient, world: SeedContext) -> None:
    r = test_sign_in(client, "meera")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(world.refs[keys.USERS.MEERA])
    assert client.cookies.get("lk_session") and client.cookies.get("lk_csrf")
    assert client.get("/api/v1/identity/me").status_code == 200


def test_sign_in_by_ids_and_unknown_users(client: TestClient, world: SeedContext) -> None:
    r = client.post(
        "/api/v1/_test/sign-in",
        json={"company_id": str(world.company_id), "user_id": str(world.refs[keys.USERS.KABIR])},
        headers=origin_headers(),
    )
    assert r.status_code == 200
    headers = {**origin_headers(), "X-CSRF-Token": client.cookies.get("lk_csrf") or ""}  # a live session needs CSRF
    assert client.post("/api/v1/_test/sign-in", json={"user_key": "NOBODY"}, headers=headers).status_code == 404
    both = client.post(
        "/api/v1/_test/sign-in",
        json={"user_key": "MEERA", "company_id": str(world.company_id), "user_id": str(world.refs["MEERA"])},
        headers=headers,
    )
    assert both.status_code == 422


def test_fixtures_returns_the_seeded_references(client: TestClient, world: SeedContext) -> None:
    r = client.get("/api/v1/_test/fixtures")
    assert r.status_code == 200
    body = r.json()
    assert body["company_id"] == str(world.company_id)
    assert body["refs"][keys.USERS.SAHIL] == str(world.refs[keys.USERS.SAHIL])
    assert set(body["facts"]["branches"]) == {keys.BRANCHES.HO, keys.BRANCHES.FAC}
    # the constants the e2e specs read (apps/web/e2e/support/world.ts)
    assert body["facts"]["expected"]["SCENARIO_C_TOTAL"] == keys.EXPECTED.SCENARIO_C_TOTAL
    assert body["facts"]["expected"]["SCENARIO_C_QTY"] == keys.EXPECTED.SCENARIO_C_QTY
    assert body["facts"]["quotes"]["SCENARIO_C_NEW"] == keys.QUOTES.SCENARIO_C_NEW
    assert body["facts"]["enquiries"]["MAISON"] == keys.ENQUIRIES.MAISON


def test_clock_moves_business_time(client: TestClient, world: SeedContext, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    test_sign_in(client, keys.USERS.MEERA)
    from tests.integration.identity.fixtures import csrf_headers

    r = client.post("/api/v1/_test/clock", json={"at": "2026-10-12T09:00:00Z"}, headers=csrf_headers(client))
    assert r.status_code == 200 and r.json() == {"at": "2026-10-12T09:00:00Z", "scope": "global"}
    assert frozen_clock.now().isoformat() == "2026-10-12T09:00:00+00:00"
    boot = client.get("/api/v1/session/bootstrap").json()
    assert boot["server_now"] == "2026-10-12T09:00:00Z"
    assert boot["greeting_period"] == "afternoon"  # 14:30 IST
    naive = client.post("/api/v1/_test/clock", json={"at": "2026-10-12T09:00:00"}, headers=csrf_headers(client))
    assert naive.status_code == 422
