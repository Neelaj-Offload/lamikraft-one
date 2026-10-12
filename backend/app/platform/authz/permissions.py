"""Permission vocabulary: ``<module>.<resource>.<action>`` with scopes own < team < branch < company."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum


class Scope(IntEnum):
    OWN = 1
    TEAM = 2
    BRANCH = 3
    COMPANY = 4

    @classmethod
    def parse(cls, value: str | Scope) -> Scope:
        if isinstance(value, Scope):
            return value
        return cls[value.upper()]

    @property
    def label(self) -> str:
        return self.name.lower()


ALL_SCOPES: tuple[Scope, ...] = (Scope.OWN, Scope.TEAM, Scope.BRANCH, Scope.COMPANY)
COMPANY_ONLY: tuple[Scope, ...] = (Scope.COMPANY,)

#: The closed verb vocabulary (docs/architecture/permissions.md). New verbs need an ADR.
VERBS: frozenset[str] = frozenset(
    {
        "read", "create", "update", "archive", "delete", "transition", "approve", "export",
        "manage", "run", "execute", "post", "issue", "use", "assign", "override", "send",
        "reverse", "decide", "dismiss", "import", "correct", "promote", "reserve", "receive",
    }
)

_KEY = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class PermissionDef:
    key: str
    description: str
    scopes: tuple[Scope, ...] = COMPANY_ONLY
    delegable: bool = False
    requires_mfa: bool = False
    requires_recent_auth: bool = False
    field_guard: bool = False
    sensitivity: str = "normal"  # normal | sensitive | critical
    legacy_aliases: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise ValueError(f"permission key {self.key!r} must be <module>.<resource>.<action>")
        verb = self.key.rsplit(".", 1)[1]
        if verb not in VERBS:
            raise ValueError(f"permission {self.key!r} uses verb {verb!r} outside the closed vocabulary")
        if not self.scopes:
            raise ValueError(f"permission {self.key!r} must allow at least one scope")

    @property
    def module(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def max_scope(self) -> Scope:
        return max(self.scopes)
