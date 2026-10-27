"""Navigation filtering, area readiness, greeting periods and poll ETags (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.ui.service import NAV_AREAS, area_readiness, etag_matches, etag_of, greeting_period, nav_for
from app.registry import build_registry

ALL_READY = dict.fromkeys((a.key for a in NAV_AREAS), True)


def _keys(nav: list) -> list[str]:  # type: ignore[type-arg]
    return [n.key for n in nav]


def test_every_member_gets_today_inbox_and_settings() -> None:
    assert _keys(nav_for([], ALL_READY)) == ["today", "inbox", "settings"]


def test_areas_follow_permission_prefixes() -> None:
    assert _keys(nav_for(["sales.quote.read"], ALL_READY)) == ["today", "inbox", "sales", "settings"]
    assert _keys(nav_for(["catalogue.product.read", "inventory.stock.read"], ALL_READY)) == [
        "today", "inbox", "products", "operations", "settings",
    ]
    assert _keys(nav_for(["finance.invoice.read"], ALL_READY)) == ["today", "inbox", "finance", "settings"]
    # a prefix must match a whole module name
    assert _keys(nav_for(["salesforce.thing.read", "catalogues.x.read"], ALL_READY)) == ["today", "inbox", "settings"]


def test_paths_and_labels_match_the_web_route_manifest() -> None:
    nav = nav_for(["sales.quote.read", "catalogue.product.read", "challans.challan.read", "finance.invoice.read"], ALL_READY)
    assert [(n.key, n.path, n.label) for n in nav] == [
        ("today", "/today", "Today"),
        ("inbox", "/inbox", "Inbox"),
        ("sales", "/sales", "Sales"),
        ("products", "/products", "Products"),
        ("operations", "/operations", "Operations"),
        ("finance", "/finance", "Finance"),
        ("settings", "/settings", "Settings"),
    ]


def test_unimplemented_areas_are_hidden() -> None:
    ready = area_readiness({"identity", "ui", "sales"})
    assert ready == {
        "today": True, "inbox": True, "sales": True, "products": False, "operations": False, "finance": False, "settings": True,
    }
    assert _keys(nav_for(["sales.quote.read", "catalogue.product.read"], ready)) == ["today", "inbox", "sales", "settings"]
    installed = {m.name for m in build_registry().manifests}
    assert area_readiness(installed)["today"] is True


@pytest.mark.parametrize(
    ("utc_hour", "zone", "expected"),
    [
        (3, "Asia/Kolkata", "morning"),  # 08:55 IST, D0
        (6, "Asia/Kolkata", "morning"),  # 11:55 IST
        (7, "Asia/Kolkata", "afternoon"),  # 12:55 IST
        (11, "Asia/Kolkata", "afternoon"),  # 16:55 IST
        (12, "Asia/Kolkata", "evening"),  # 17:55 IST
        (22, "Asia/Kolkata", "evening"),  # 03:55 IST the next day, before 05:00
        (3, "Europe/Berlin", "morning"),  # 05:25 CEST
        (3, "America/New_York", "evening"),  # 23:25 EDT the previous day
    ],
)
def test_greeting_period_uses_the_local_hour(utc_hour: int, zone: str, expected: str) -> None:
    assert greeting_period(datetime(2026, 10, 12, utc_hour, 25, tzinfo=UTC), zone) == expected


def test_greeting_period_boundaries() -> None:
    zone = "UTC"
    assert greeting_period(datetime(2026, 10, 12, 4, 59, tzinfo=UTC), zone) == "evening"
    assert greeting_period(datetime(2026, 10, 12, 5, 0, tzinfo=UTC), zone) == "morning"
    assert greeting_period(datetime(2026, 10, 12, 11, 59, tzinfo=UTC), zone) == "morning"
    assert greeting_period(datetime(2026, 10, 12, 12, 0, tzinfo=UTC), zone) == "afternoon"
    assert greeting_period(datetime(2026, 10, 12, 16, 59, tzinfo=UTC), zone) == "afternoon"
    assert greeting_period(datetime(2026, 10, 12, 17, 0, tzinfo=UTC), zone) == "evening"


def test_etags_are_stable_and_content_sensitive() -> None:
    a = etag_of({"sections": {"inbox": {"open": 2}, "briefing": {"version": 1}}})
    b = etag_of({"sections": {"briefing": {"version": 1}, "inbox": {"open": 2}}})
    c = etag_of({"sections": {"inbox": {"open": 3}, "briefing": {"version": 1}}})
    assert a == b != c and a.startswith('"') and a.endswith('"')
    assert etag_matches(a, a) and etag_matches(f"W/{a}", a) and etag_matches(f'"x", {a}', a) and etag_matches("*", a)
    assert not etag_matches(None, a) and not etag_matches(c, a)
