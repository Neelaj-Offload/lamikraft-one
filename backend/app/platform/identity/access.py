"""Effective permissions: pure resolution rules, the legacy alias table and the per-epoch cache.

Resolution (permissions.md §10), applied to an **active** membership:
1. union of the grants of every assigned role plus the ``employee`` base, taking the maximum scope per key;
2. unexpired per-user grants raise a key to the higher scope;
3. every key with an unexpired per-user revoke is removed — **revoke always wins**, over roles and grants.
Delegation (Slice 2) only extends record reach and never adds keys.

Results are cached per ``(membership_id, authz_epoch)``; every change to roles, overrides, memberships,
teams or branches increments ``company.authz_epoch``, and a cached result also expires at the next
override expiry it depends on.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from app.platform.authz.permissions import Scope


@dataclass(frozen=True)
class Override:
    key: str
    effect: str  # grant | revoke
    scope: Scope | None
    expires_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now


def resolve_permissions(
    role_grants: Iterable[Mapping[str, Scope]], overrides: Iterable[Override], *, now: datetime
) -> dict[str, Scope]:
    """Union of role grants (max scope) plus unexpired user grants, minus unexpired user revokes."""
    perms: dict[str, Scope] = {}
    for grants in role_grants:
        for key, scope in grants.items():
            current = perms.get(key)
            perms[key] = scope if current is None else max(current, scope)
    active = [o for o in overrides if o.active(now)]
    for o in active:
        if o.effect == "grant" and o.scope is not None:
            current = perms.get(o.key)
            perms[o.key] = o.scope if current is None else max(current, o.scope)
    for o in active:
        if o.effect == "revoke":
            perms.pop(o.key, None)
    return perms


def next_expiry(overrides: Iterable[Override], *, now: datetime) -> datetime | None:
    """The earliest future expiry among overrides (a cached resolution is stale from then on)."""
    future = [o.expires_at for o in overrides if o.expires_at is not None and o.expires_at > now]
    return min(future) if future else None


# ---- legacy alias table (permissions.md §8) --------------------------------------------------------
@dataclass(frozen=True)
class LegacyAlias:
    legacy_key: str
    permission_key: str
    scope: Scope | None = None
    scope_from_key: str | None = None
    fallback_scope: Scope | None = None
    note: str | None = None


def _fixed(legacy: str, keys: tuple[str, ...], scope: Scope, note: str | None = None) -> list[LegacyAlias]:
    return [LegacyAlias(legacy, key, scope=scope, note=note) for key in keys]


_EDIT = ("sales.quote.update", "sales.quote.transition", "sales.quote.issue", "sales.quote.archive")

LEGACY_ALIASES: tuple[LegacyAlias, ...] = tuple(
    [
        *_fixed("view_all_quotes", ("sales.quote.read",), Scope.COMPANY),
        *_fixed("view_own_quotes", ("sales.quote.read",), Scope.OWN),
        *_fixed("create_quotes", ("sales.quote.create",), Scope.COMPANY),
        *_fixed("edit_all_quotes", _EDIT, Scope.COMPANY),
        *_fixed("edit_own_quotes", _EDIT, Scope.OWN),
        *_fixed("delete_quotes", ("sales.quote.delete",), Scope.COMPANY, "service allows never-issued drafts only"),
        LegacyAlias(
            "override_price",
            "sales.quote_price.override",
            scope_from_key="sales.quote.update",
            fallback_scope=Scope.OWN,
            note="the expanded scope of sales.quote.update (own if none)",
        ),
        LegacyAlias(
            "export_quotes",
            "sales.quote.export",
            scope_from_key="sales.quote.read",
            note="the expanded scope of sales.quote.read",
        ),
        *_fixed("view_products", ("catalogue.product.read", "pricing.price.read"), Scope.COMPANY),
        *_fixed(
            "edit_products",
            (
                "catalogue.product.create",
                "catalogue.product.update",
                "catalogue.product.archive",
                "catalogue.media.manage",
                "pricing.price_list.manage",
            ),
            Scope.COMPANY,
        ),
        *_fixed(
            "manage_users",
            (
                "identity.user.read",
                "identity.user.manage",
                "identity.role.read",
                "identity.role.manage",
                "identity.permission.manage",
            ),
            Scope.COMPANY,
        ),
        *_fixed("import_data", ("imports.job.read", "imports.job.run"), Scope.COMPANY),
        *_fixed("view_costing", ("pricing.cost.read", "pricing.price_list.read"), Scope.COMPANY),
        *_fixed("manage_categories", ("catalogue.taxonomy.manage",), Scope.COMPANY),
    ]
)


def legacy_alias_map(aliases: Iterable[LegacyAlias] = LEGACY_ALIASES) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for alias in aliases:
        mapping.setdefault(alias.legacy_key, []).append(alias.permission_key)
    return {k: sorted(v) for k, v in sorted(mapping.items())}


def expand_legacy(legacy_keys: Iterable[str], aliases: Iterable[LegacyAlias] = LEGACY_ALIASES) -> dict[str, Scope]:
    """Expand legacy permission names into keys and scopes (used for legacy role defaults and overrides)."""
    wanted = set(legacy_keys)
    rows = [a for a in aliases if a.legacy_key in wanted]
    out: dict[str, Scope] = {}
    for a in rows:
        if a.scope is not None:
            out[a.permission_key] = max(out.get(a.permission_key, a.scope), a.scope)
    for a in rows:
        if a.scope_from_key is not None:
            scope = out.get(a.scope_from_key, a.fallback_scope)
            if scope is not None:
                out[a.permission_key] = max(out.get(a.permission_key, scope), scope)
    return out


def legacy_holds(grants: Mapping[str, Scope], legacy_key: str, aliases: Iterable[LegacyAlias] = LEGACY_ALIASES) -> bool:
    """permissions.md §12: a fixed-scope alias holds at exactly that scope; a derived alias holds when present."""
    rows = [a for a in aliases if a.legacy_key == legacy_key]
    if not rows:
        raise KeyError(legacy_key)
    for a in rows:
        held = grants.get(a.permission_key)
        if a.scope is not None and held != a.scope:
            return False
        if a.scope is None and held is None:
            return False
    return True


# ---- per-epoch cache -------------------------------------------------------------------------------
@dataclass(frozen=True)
class AccessSnapshot:
    permissions: Mapping[str, Scope]
    role_keys: tuple[str, ...]
    branch_ids: frozenset[uuid.UUID]
    team_peer_user_ids: frozenset[uuid.UUID]
    valid_until: datetime | None = None

    @classmethod
    def build(
        cls,
        permissions: Mapping[str, Scope],
        role_keys: Iterable[str],
        branch_ids: Iterable[uuid.UUID],
        team_peer_user_ids: Iterable[uuid.UUID],
        valid_until: datetime | None,
    ) -> AccessSnapshot:
        return cls(
            permissions=MappingProxyType(dict(permissions)),
            role_keys=tuple(sorted(set(role_keys))),
            branch_ids=frozenset(branch_ids),
            team_peer_user_ids=frozenset(team_peer_user_ids),
            valid_until=valid_until,
        )


class AccessCache:
    def __init__(self, max_entries: int = 4096) -> None:
        self._data: OrderedDict[tuple[uuid.UUID, int], AccessSnapshot] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, membership_id: uuid.UUID, epoch: int, now: datetime) -> AccessSnapshot | None:
        with self._lock:
            snap = self._data.get((membership_id, epoch))
            if snap is None:
                return None
            if snap.valid_until is not None and now >= snap.valid_until:
                del self._data[(membership_id, epoch)]
                return None
            self._data.move_to_end((membership_id, epoch))
            return snap

    def put(self, membership_id: uuid.UUID, epoch: int, snap: AccessSnapshot) -> None:
        with self._lock:
            self._data[(membership_id, epoch)] = snap
            self._data.move_to_end((membership_id, epoch))
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


ACCESS_CACHE = AccessCache()
