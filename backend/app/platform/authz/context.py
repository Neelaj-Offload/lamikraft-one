"""ActorContext: the server-built identity every command, query, job and agent tool runs as.

It is constructed only by the platform (session resolution, job execution, channel linking).
Agents act as their user and never with more authority; a model can never set or elevate it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from app.core.errors import Forbidden
from app.platform.authz.permissions import Scope

ActorType = Literal["user", "agent", "system", "integration", "cli"]
AuthStrength = Literal["password", "mfa", "channel_linked", "system", "demo_link"]
Channel = Literal["web", "voice", "whatsapp", "api", "job", "cli", "test"]

_EMPTY: Mapping[str, Scope] = MappingProxyType({})


@dataclass(frozen=True)
class ActorContext:
    actor_type: ActorType
    company_id: uuid.UUID | None
    user_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None
    display_name: str = ""
    branch_ids: frozenset[uuid.UUID] = frozenset()
    team_peer_user_ids: frozenset[uuid.UUID] = frozenset()
    permissions: Mapping[str, Scope] = field(default_factory=lambda: _EMPTY)
    #: permission key -> user ids whose owned records the actor may act on via delegation
    delegated: Mapping[str, frozenset[uuid.UUID]] = field(default_factory=lambda: MappingProxyType({}))
    is_system: bool = False
    session_id: uuid.UUID | None = None
    auth_strength: AuthStrength = "password"
    recent_auth_at: datetime | None = None
    channel: Channel = "web"
    correlation_id: str | None = None
    request_id: str | None = None
    locale: str = "en-IN"
    time_zone: str = "Asia/Kolkata"
    authz_epoch: int = 0
    idempotency_key: str | None = None
    agent_run_id: uuid.UUID | None = None
    on_behalf_of_user_id: uuid.UUID | None = None

    # ---- permission checks ---------------------------------------------------------------
    def scope_for(self, key: str) -> Scope | None:
        if self.is_system:
            return Scope.COMPANY
        return self.permissions.get(key)

    def can(self, key: str, at_least: Scope = Scope.OWN) -> bool:
        if self.is_system:
            return True
        scope = self.permissions.get(key)
        if scope is not None and scope >= at_least:
            return True
        return at_least == Scope.OWN and bool(self.delegated.get(key))

    def require(self, key: str, at_least: Scope = Scope.OWN) -> None:
        if not self.can(key, at_least):
            raise Forbidden(code="permission_denied", permission=key)

    def has_any(self, prefix: str) -> bool:
        if self.is_system:
            return True
        return any(k.startswith(prefix) for k in self.permissions)

    # ---- constructors ----------------------------------------------------------------------
    @classmethod
    def system(cls, company_id: uuid.UUID | None, *, reason: str = "system", correlation_id: str | None = None) -> ActorContext:
        return cls(
            actor_type="system",
            company_id=company_id,
            display_name=f"System ({reason})",
            is_system=True,
            auth_strength="system",
            channel="job",
            correlation_id=correlation_id,
        )

    def with_(self, **changes: object) -> ActorContext:
        return replace(self, **changes)  # type: ignore[arg-type]

    @property
    def is_authenticated_user(self) -> bool:
        return self.user_id is not None and not self.is_system
