"""The permission vocabulary as code (generated data from docs/architecture/permissions.md).

Role templates: each catalogue row lists its template grants; ``employee`` grants are merged into every
template, and ``admin`` holds every key at its maximum scope (permissions.md §6, §9).
"""

from __future__ import annotations

from app.platform.authz.catalogue_data import PERMISSIONS as _ROWS
from app.platform.authz.permissions import PermissionDef, Scope

TEMPLATE_KEYS: tuple[str, ...] = (
    "employee", "admin", "management", "sales", "operations", "finance", "production", "procurement", "warehouse",
    "catalogue",
)


def permission_defs() -> list[PermissionDef]:
    out = []
    for row in _ROWS:
        out.append(
            PermissionDef(
                key=row["key"],
                description=row["key"].replace(".", " "),
                scopes=tuple(Scope[s] for s in row["scopes"]),
                delegable=row["delegable"],
                requires_mfa=row["mfa"],
                requires_recent_auth=row["ra"],
                field_guard=row["fg"],
                sensitivity="sensitive" if row["sensitive"] else "normal",
                legacy_aliases=tuple(row["legacy"]),
            )
        )
    return out


def template_grants() -> dict[str, dict[str, Scope]]:
    grants: dict[str, dict[str, Scope]] = {t: {} for t in TEMPLATE_KEYS}
    for row in _ROWS:
        for template, scope in row["grants"].items():
            grants[template][row["key"]] = Scope[scope]
        grants["admin"][row["key"]] = max(Scope[s] for s in row["scopes"])
    base = grants["employee"]
    for template in TEMPLATE_KEYS:
        if template in ("employee", "admin"):
            continue
        for key, scope in base.items():
            current = grants[template].get(key)
            grants[template][key] = max(scope, current) if current else scope
    return grants


def catalogue_slice(key: str) -> int:
    for row in _ROWS:
        if row["key"] == key:
            return int(row["slice"])
    raise KeyError(key)
