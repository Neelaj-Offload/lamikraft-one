"""Own profile and typed preference sections (self-service, no permission key needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.platform.audit.models import AuditLog
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import csrf_headers, system, test_sign_in

pytestmark = pytest.mark.db

PREFS = "/api/v1/identity/me/preferences"


def test_me_describes_the_member(client: TestClient, world: SeedContext) -> None:
    assert test_sign_in(client, keys.USERS.MEERA).status_code == 200
    me = client.get("/api/v1/identity/me").json()
    person = keys.PEOPLE[keys.USERS.MEERA]
    assert me["user"]["email"] == person.email and me["user"]["display_name"] == person.name
    membership = me["membership"]
    assert [r["key"] for r in membership["roles"]] == ["sales"]
    assert [b["code"] for b in membership["branches"]] == [keys.BRANCHES.HO]
    assert [(t["key"], t["team_role"]) for t in membership["teams"]] == [(keys.TEAMS.EXP_SALES, "member")]
    assert membership["manager"]["display_name"] == keys.PEOPLE[keys.USERS.SAHIL].name
    assert membership["company"]["key"] == keys.COMPANY_KEY
    assert me["time_zone"] == keys.ZONE and me["locale"] == "en-IN"
    assert me["preferences"]["version"] == 0
    assert me["preferences"]["ui"] == {
        "theme": "system",
        "motion": "full",
        "sidebar_collapsed": False,
        "context_rail_open": True,
        "density": "comfortable",
        "shortcuts_enabled": True,
    }
    assert me["session"]["auth_method"] == "test_support"


def test_patch_preferences_merges_sections_and_sets_the_ui_cookie(client: TestClient, world: SeedContext) -> None:
    test_sign_in(client, keys.USERS.NEHA)
    r = client.patch(
        PREFS,
        json={"ui": {"theme": "dark", "density": "compact"}, "briefing": {"detail_level": "brief"}, "locale": {"time_zone": "Europe/Berlin"}},
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["changed_fields"]) == ["briefing.detail_level", "locale.time_zone", "ui.density", "ui.theme"]
    prefs = body["preferences"]
    assert prefs["version"] == 1 and prefs["ui"]["theme"] == "dark" and prefs["ui"]["motion"] == "full"
    assert prefs["briefing"] == {"language": "en", "detail_level": "brief"}
    ui_cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("lk_ui="))
    assert "theme=dark&motion=full" in ui_cookie.replace('"', "")
    assert client.get("/api/v1/identity/me").json()["time_zone"] == "Europe/Berlin"

    second = client.patch(PREFS, json={"ui": {"motion": "reduced"}, "expected_version": 1}, headers=csrf_headers(client))
    assert second.status_code == 200 and second.json()["preferences"]["version"] == 2
    assert second.json()["preferences"]["ui"]["theme"] == "dark"
    stale = client.patch(PREFS, json={"ui": {"motion": "full"}, "expected_version": 1}, headers=csrf_headers(client))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    cleared = client.patch(PREFS, json={"locale": {"time_zone": None}}, headers=csrf_headers(client))
    assert cleared.json()["preferences"]["locale"]["time_zone"] is None
    unchanged = client.patch(PREFS, json={"ui": {"theme": "dark"}}, headers=csrf_headers(client))
    assert unchanged.json()["changed_fields"] == [] and unchanged.json()["preferences"]["version"] == 3

    with UnitOfWork(system(world.company_id)) as uow:
        audited = list(uow.session.scalars(select(AuditLog).where(AuditLog.action == "identity.preferences.updated")))
    assert len(audited) == 3 and all("changed_fields" in (a.details or {}) for a in audited)


def test_preferences_never_weaken_policy(client: TestClient, world: SeedContext) -> None:
    test_sign_in(client, keys.USERS.MEERA)
    r = client.patch(PREFS, json={"briefing": {"undismissable_kinds": []}}, headers=csrf_headers(client))
    assert r.status_code == 422 and r.json()["code"] == "mandatory_control"
    assert r.json()["fields"] == ["undismissable_kinds"]
    r = client.patch(PREFS, json={"roles": ["admin"]}, headers=csrf_headers(client))
    assert r.status_code == 422 and r.json()["code"] == "mandatory_control"
    unknown = client.patch(PREFS, json={"ui": {"font": "comic"}}, headers=csrf_headers(client))
    assert unknown.status_code == 422 and unknown.json()["code"] == "validation_failed"
    bad_zone = client.patch(PREFS, json={"locale": {"time_zone": "Mars/Olympus"}}, headers=csrf_headers(client))
    assert bad_zone.status_code == 422
    bad_theme = client.patch(PREFS, json={"ui": {"theme": "neon"}}, headers=csrf_headers(client))
    assert bad_theme.status_code == 422


def test_preferences_need_a_session(client: TestClient, world: SeedContext) -> None:
    from tests.integration.identity.fixtures import origin_headers

    r = client.patch(PREFS, json={"ui": {"theme": "dark"}}, headers=origin_headers())
    assert r.status_code == 401
