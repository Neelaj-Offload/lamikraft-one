"""GET /api/v1/session/bootstrap (api-conventions §8): identity, zone, greeting, permissions, nav, sections, CSRF."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.platform.bootstrap import _SECTIONS, UiSection, register_ui_section
from app.seed.context import SeedContext
from app.seed.world import keys
from tests.integration.identity.fixtures import test_sign_in

pytestmark = pytest.mark.db

BOOT = "/api/v1/session/bootstrap"


ALL_AREA_MODULES = frozenset(
    {"sales", "catalogue", "challans", "cutting", "inventory", "procurement", "production", "logistics", "finance"}
)
EVERY_AREA = ["today", "inbox", "sales", "products", "operations", "finance", "settings"]


@pytest.fixture
def all_areas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend every area's module is installed so navigation reflects permissions alone."""
    from app.modules.ui import service as ui_service

    monkeypatch.setattr(ui_service, "installed_module_names", lambda: ALL_AREA_MODULES | {"ui", "identity", "agents"})


@pytest.fixture
def probe_sections() -> Iterator[None]:
    """Two contributed sections: one healthy (in poll), one failing (must not break the bootstrap)."""
    saved = dict(_SECTIONS)
    register_ui_section(UiSection("probe_counts", lambda uow: {"user_id": str(uow.actor.user_id)}, in_poll=True))
    register_ui_section(UiSection("probe_broken", lambda uow: 1 / 0, in_poll=False))  # type: ignore[arg-type,return-value]
    yield
    _SECTIONS.clear()
    _SECTIONS.update(saved)


def test_signed_out_is_a_clean_401(client: TestClient, world: SeedContext) -> None:
    r = client.get(BOOT)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "unauthenticated"


def test_sales_persona_bootstrap(client: TestClient, world: SeedContext, probe_sections: None, all_areas: None) -> None:
    test_sign_in(client, keys.USERS.MEERA)
    r = client.get(BOOT)
    assert r.status_code == 200, r.text
    body = r.json()
    person = keys.PEOPLE[keys.USERS.MEERA]
    assert body["user"] == {"id": str(world.refs["MEERA"]), "display_name": person.name, "email": person.email}
    assert body["membership"]["display_name"] == person.name
    assert body["membership"]["role_names"] == ["Sales"] and body["membership"]["is_demo"] is True
    assert body["company"]["key"] == keys.COMPANY_KEY and body["company"]["display_name"] == keys.COMPANY_DISPLAY_NAME
    assert [b["code"] for b in body["branches"]] == [keys.BRANCHES.HO, keys.BRANCHES.FAC]
    assert body["time_zone"] == keys.ZONE and body["locale"] == "en-IN"
    assert body["server_now"] == "2026-10-12T03:25:00Z"  # D0 08:55 IST
    assert body["greeting_period"] == "morning"
    grants = {p["key"]: p["scope"] for p in body["permissions"]}
    assert grants["sales.quote.read"] == "own" and grants["briefings.briefing.read"] == "own"
    assert "sales.quote.delete" not in grants and not any(k.startswith("identity.") for k in grants)
    assert [n["key"] for n in body["nav"]] == ["today", "inbox", "sales", "products", "operations", "settings"]
    assert body["nav"][2] == {"key": "sales", "path": "/sales", "label": "Sales"}
    assert body["features"] == {**dict.fromkeys(EVERY_AREA, True), "assistant": "agents.assistant.use" in grants, "voice": False}
    assert body["features"]["assistant"] is True  # Meera may use the assistant (agents installed)
    assert body["preferences"]["version"] == 0 and body["preferences"]["ui"]["theme"] == "system"
    assert body["integration_modes"] == {"ai": "demo", "whatsapp": "demo", "email": "demo"}
    assert body["sections"]["probe_counts"] == {"user_id": str(world.refs["MEERA"])}
    assert body["sections"]["probe_broken"] == {"status": "unavailable"}
    assert body["session"]["auth_method"] == "test_support"
    assert body["csrf_token"] == client.cookies.get("lk_csrf")


def test_restricted_warehouse_persona_sees_no_sales(client: TestClient, world: SeedContext, all_areas: None) -> None:
    test_sign_in(client, keys.USERS.KABIR)
    body = client.get(BOOT).json()
    nav = [n["key"] for n in body["nav"]]
    assert "sales" not in nav and "finance" not in nav
    assert nav[:2] == ["today", "inbox"] and nav[-1] == "settings"
    assert "products" in nav  # warehouse holds catalogue.product.read
    assert "operations" in nav  # and branch stock keys
    assert not any(p["key"].startswith("sales.") for p in body["permissions"])


@pytest.mark.parametrize(
    ("user_key", "expected"),
    [
        (keys.USERS.SAHIL, EVERY_AREA),
        (keys.USERS.ANANYA, EVERY_AREA),
        (keys.USERS.PRIYA, EVERY_AREA),
        (keys.USERS.RAVI, ["today", "inbox", "sales", "products", "operations", "settings"]),
        (keys.USERS.ARJUN, ["today", "inbox", "sales", "products", "operations", "settings"]),
    ],
)
def test_nav_follows_permissions(
    client: TestClient, world: SeedContext, all_areas: None, user_key: str, expected: list[str]
) -> None:
    test_sign_in(client, user_key)
    assert [n["key"] for n in client.get(BOOT).json()["nav"]] == expected


def test_greeting_follows_the_users_zone(client: TestClient, world: SeedContext, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    test_sign_in(client, keys.USERS.MEERA)
    from tests.integration.identity.fixtures import csrf_headers

    client.patch("/api/v1/identity/me/preferences", json={"locale": {"time_zone": "America/New_York"}, "expected_version": 0}, headers=csrf_headers(client))
    body = client.get(BOOT).json()
    assert body["time_zone"] == "America/New_York"
    assert body["greeting_period"] == "evening"  # 23:25 on Sunday in New York
    frozen_clock.set(datetime(2026, 10, 12, 10, 0, tzinfo=UTC))
    assert client.get(BOOT).json()["greeting_period"] == "morning"  # 06:00 in New York (activity extends the session)
    frozen_clock.set(datetime(2026, 10, 12, 17, 0, tzinfo=UTC))
    assert client.get(BOOT).json()["greeting_period"] == "afternoon"  # 13:00 in New York


def test_nav_hides_areas_that_are_not_implemented(
    client: TestClient, world: SeedContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ui import service as ui_service

    monkeypatch.setattr(ui_service, "installed_module_names", lambda: frozenset({"identity", "ui", "sales", "catalogue"}))
    test_sign_in(client, keys.USERS.PRIYA)  # admin: every key, so only readiness can hide an area
    body = client.get(BOOT).json()
    assert [n["key"] for n in body["nav"]] == ["today", "inbox", "sales", "products", "settings"]
    assert body["features"] == {
        "today": True, "inbox": True, "sales": True, "products": True, "operations": False, "finance": False, "settings": True,
        "assistant": False, "voice": False,  # no agents module installed: no assistant even for an admin
    }


def test_a_database_error_in_one_section_leaves_the_rest_of_the_bootstrap_intact(client: TestClient, world: SeedContext) -> None:
    """Review finding: a SQL error in a section aborted the whole transaction (500, CSRF rotation lost). Each section
    now runs in its own savepoint, so only that section is unavailable, in the bootstrap and in the poll."""
    from sqlalchemy import text

    saved = dict(_SECTIONS)
    register_ui_section(UiSection("probe_sql_error", lambda uow: uow.session.execute(text("SELECT 1/0")).scalar(), in_poll=True))  # type: ignore[arg-type,return-value,misc]
    register_ui_section(UiSection("probe_zz_after", lambda uow: {"rows": uow.session.execute(text("SELECT 1")).scalar()}, in_poll=True))
    try:
        test_sign_in(client, keys.USERS.MEERA)
        before = client.cookies.get("lk_csrf")
        r = client.get(BOOT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sections"]["probe_sql_error"] == {"status": "unavailable"}
        assert body["sections"]["probe_zz_after"] == {"rows": 1}
        assert body["csrf_token"] != before and client.cookies.get("lk_csrf") == body["csrf_token"]  # rotation committed
        polled = client.get("/api/v1/ui/poll")
        assert polled.status_code == 200, polled.text
        assert polled.json()["sections"]["probe_sql_error"] == {"status": "unavailable"}
        assert polled.json()["sections"]["probe_zz_after"] == {"rows": 1}
    finally:
        _SECTIONS.clear()
        _SECTIONS.update(saved)
