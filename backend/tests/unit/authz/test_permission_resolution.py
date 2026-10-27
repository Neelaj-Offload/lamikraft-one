"""Permission resolution properties (permissions.md §10-§11): revoke wins, scopes take the maximum."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.platform.authz.permissions import Scope
from app.platform.identity.access import Override, next_expiry, resolve_permissions

NOW = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)
KEYS = [
    "sales.quote.read",
    "sales.quote.update",
    "sales.quote.export",
    "sales.quote_price.approve",
    "tasks.task.read",
    "catalogue.product.read",
    "pricing.cost.read",
    "identity.role.manage",
]

key_st = st.sampled_from(KEYS)
scope_st = st.sampled_from(list(Scope))
expiry_st = st.one_of(st.none(), st.integers(min_value=-48, max_value=48).map(lambda h: NOW + timedelta(hours=h, seconds=1)))
grant_st = st.builds(lambda k, s, e: Override(k, "grant", s, e), key_st, scope_st, expiry_st)
revoke_st = st.builds(lambda k, e: Override(k, "revoke", None, e), key_st, expiry_st)
roles_st = st.lists(st.dictionaries(key_st, scope_st, max_size=6), max_size=4)
overrides_st = st.lists(st.one_of(grant_st, revoke_st), max_size=8)

SETTINGS = settings(derandomize=True, max_examples=300, deadline=None)


def _active(overrides: list[Override]) -> list[Override]:
    return [o for o in overrides if o.expires_at is None or o.expires_at > NOW]


@SETTINGS
@given(roles_st, overrides_st)
def test_revoke_wins_and_scope_is_max(roles: list[dict[str, Scope]], overrides: list[Override]) -> None:
    result = resolve_permissions(roles, overrides, now=NOW)
    active = _active(overrides)
    revoked = {o.key for o in active if o.effect == "revoke"}
    for key in KEYS:
        sources = [r[key] for r in roles if key in r] + [o.scope for o in active if o.effect == "grant" and o.key == key]
        if key in revoked:
            assert key not in result  # revoke always wins, over roles and over grants
        elif sources:
            assert result[key] == max(s for s in sources if s is not None)
        else:
            assert key not in result  # nothing appears without a source


@SETTINGS
@given(roles_st, overrides_st, st.randoms(use_true_random=False))
def test_resolution_is_order_independent(roles: list[dict[str, Scope]], overrides: list[Override], rnd: random.Random) -> None:
    shuffled_roles, shuffled_overrides = roles[:], overrides[:]
    rnd.shuffle(shuffled_roles)
    rnd.shuffle(shuffled_overrides)
    assert resolve_permissions(roles, overrides, now=NOW) == resolve_permissions(shuffled_roles, shuffled_overrides, now=NOW)


@SETTINGS
@given(roles_st, overrides_st)
def test_expired_overrides_have_no_effect(roles: list[dict[str, Scope]], overrides: list[Override]) -> None:
    assert resolve_permissions(roles, overrides, now=NOW) == resolve_permissions(roles, _active(overrides), now=NOW)


@SETTINGS
@given(roles_st, st.dictionaries(key_st, scope_st, max_size=6), overrides_st)
def test_adding_a_role_never_removes_or_lowers_unrevoked_keys(
    roles: list[dict[str, Scope]], extra: dict[str, Scope], overrides: list[Override]
) -> None:
    before = resolve_permissions(roles, overrides, now=NOW)
    after = resolve_permissions([*roles, extra], overrides, now=NOW)
    for key, scope in before.items():
        assert after[key] >= scope


@SETTINGS
@given(overrides_st)
def test_next_expiry_is_the_earliest_future_expiry(overrides: list[Override]) -> None:
    future = [o.expires_at for o in overrides if o.expires_at is not None and o.expires_at > NOW]
    assert next_expiry(overrides, now=NOW) == (min(future) if future else None)


def test_examples() -> None:
    sales = {"sales.quote.read": Scope.OWN, "sales.quote.export": Scope.OWN}
    operations = {"sales.quote.read": Scope.COMPANY, "tasks.task.read": Scope.BRANCH}
    assert resolve_permissions([sales, operations], [], now=NOW) == {
        "sales.quote.read": Scope.COMPANY,
        "sales.quote.export": Scope.OWN,
        "tasks.task.read": Scope.BRANCH,
    }
    overrides = [
        Override("sales.quote.export", "grant", Scope.COMPANY),
        Override("sales.quote.export", "revoke", None),
        Override("pricing.cost.read", "grant", Scope.COMPANY, NOW - timedelta(seconds=1)),
    ]
    assert resolve_permissions([sales], overrides, now=NOW) == {"sales.quote.read": Scope.OWN}
