"""Legacy alias expansion, the per-epoch access cache, keyed hashes and rate-limit windows (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.platform.authz.permissions import Scope
from app.platform.identity import ratelimit
from app.platform.identity.access import (
    LEGACY_ALIASES,
    AccessCache,
    AccessSnapshot,
    expand_legacy,
    legacy_alias_map,
    legacy_holds,
)
from app.platform.identity.tokens import keyed_hash, matches, new_token, sha256
from app.registry import build_registry

NOW = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)


def test_alias_table_matches_the_registry_and_covers_fourteen() -> None:
    assert legacy_alias_map(LEGACY_ALIASES) == build_registry().legacy_alias_map()
    assert len(legacy_alias_map()) == 14


def test_legacy_sales_defaults_expand_to_own_scope() -> None:
    granted = expand_legacy({"view_own_quotes", "create_quotes", "edit_own_quotes", "override_price", "export_quotes", "view_products"})
    assert granted["sales.quote.read"] == Scope.OWN
    assert granted["sales.quote.update"] == Scope.OWN and granted["sales.quote.archive"] == Scope.OWN
    assert granted["sales.quote_price.override"] == Scope.OWN  # follows sales.quote.update
    assert granted["sales.quote.export"] == Scope.OWN  # follows sales.quote.read
    assert granted["sales.quote.create"] == Scope.COMPANY and granted["catalogue.product.read"] == Scope.COMPANY


def test_legacy_management_defaults_expand_to_company_scope() -> None:
    granted = expand_legacy({"view_all_quotes", "edit_all_quotes", "override_price", "export_quotes", "view_costing"})
    assert granted["sales.quote_price.override"] == Scope.COMPANY
    assert granted["sales.quote.export"] == Scope.COMPANY
    assert granted["pricing.cost.read"] == Scope.COMPANY


def test_derived_alias_fallbacks() -> None:
    assert expand_legacy({"override_price"}) == {"sales.quote_price.override": Scope.OWN}  # own if no update scope
    assert expand_legacy({"export_quotes"}) == {}  # no read scope, nothing to bound the export by


def test_expanded_legacy_permissions_hold_again() -> None:
    names = {"view_own_quotes", "create_quotes", "edit_own_quotes", "override_price", "export_quotes", "view_products"}
    granted = expand_legacy(names)
    held = {name for name in legacy_alias_map() if legacy_holds(granted, name)}
    assert held == names


def test_access_cache_respects_epoch_expiry_and_size() -> None:
    cache = AccessCache(max_entries=2)
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    snap = AccessSnapshot.build({"x.y.read": Scope.OWN}, ["sales"], [], [], NOW + timedelta(hours=1))
    cache.put(a, 1, snap)
    assert cache.get(a, 1, NOW) is snap
    assert cache.get(a, 2, NOW) is None  # another epoch
    assert cache.get(a, 1, NOW + timedelta(hours=1)) is None  # an override expired
    cache.put(a, 1, snap)
    cache.put(b, 1, snap)
    cache.put(c, 1, snap)
    assert cache.get(a, 1, NOW) is None and cache.get(c, 1, NOW) is snap  # least recently used evicted
    assert snap.permissions == {"x.y.read": Scope.OWN}


def test_tokens_and_keyed_hashes() -> None:
    token = new_token()
    assert len(token) >= 43 and token != new_token()
    assert matches(token, sha256(token)) and not matches(token + "x", sha256(token)) and not matches(None, sha256(token))
    assert keyed_hash("email", "a@b.test") != keyed_hash("ip", "a@b.test")  # domain separated
    assert keyed_hash("email", "a@b.test") == keyed_hash("email", "a@b.test")
    assert len(keyed_hash("email", "a@b.test")) == 32


def test_rate_limit_windows_are_ten_minutes() -> None:
    start = ratelimit._window_start(datetime(2026, 10, 12, 3, 27, 59, tzinfo=UTC))
    assert start == datetime(2026, 10, 12, 3, 20, tzinfo=UTC)
    assert ratelimit._window_start(datetime(2026, 10, 12, 3, 30, tzinfo=UTC)) == datetime(2026, 10, 12, 3, 30, tzinfo=UTC)
    assert ratelimit.LOCK_BASE * 2**4 == ratelimit.LOCK_CAP == timedelta(hours=4)  # the fifth lock reaches the cap
