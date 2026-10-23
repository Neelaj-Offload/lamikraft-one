"""Source readers: how tasks/briefings (and the agent) read business records without importing modules.

Each domain module registers a reader for the resource types it owns (``register_reader`` in its
manifest ``on_load``). Rules treat events as triggers and re-read authoritative state through these
readers, so a stale or replayed event can never manufacture an update. Readers run inside the caller's
unit of work; visibility is still decided by the resource's ResourcePolicy (``visible_ids``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


@dataclass(frozen=True)
class MoneyFact:
    amount: str  # decimal string from the owning module's persisted calculation
    currency: str


@dataclass(frozen=True)
class SourceFacts:
    source_type: str  # e.g. "sales.quote"
    source_id: uuid.UUID
    version: int | None
    label: str  # "LK-QT-2026-0008 · Nordhaus Interiors GmbH"
    status: str
    owner_user_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    required_permission: str  # read permission for visibility, e.g. "sales.quote.read"
    canonical_path: str  # web route, e.g. "/sales/quotes/<id>"
    is_closed: bool = False
    updated_at: datetime | None = None
    #: deadlines in UTC keyed by name (valid_until_end, reply_due, ...)
    deadlines: dict[str, datetime] = field(default_factory=dict)
    #: safe display facts (numbers, names, counts as strings); never restricted values
    facts: dict[str, Any] = field(default_factory=dict)
    money: list[MoneyFact] = field(default_factory=list)
    #: optional imagery hint for the UI (decor swatch key or file id)
    media_hint: str | None = None


Reader = Callable[["UnitOfWork", uuid.UUID], SourceFacts | None]
_READERS: dict[str, Reader] = {}


def register_reader(source_type: str, reader: Reader) -> None:
    _READERS[source_type] = reader


def read(uow: UnitOfWork, source_type: str, source_id: uuid.UUID) -> SourceFacts | None:
    reader = _READERS.get(source_type)
    return reader(uow, source_id) if reader else None


def has_reader(source_type: str) -> bool:
    return source_type in _READERS


def visible_ids(uow: UnitOfWork, source_type: str, action: str = "read") -> Select[Any]:
    """Ids of ``source_type`` records the unit of work's actor may see (via the ResourcePolicy)."""
    from sqlalchemy import select

    from app.platform.authz.policy import get_policy, scope_clause

    policy = get_policy(source_type)
    return select(policy.model.id).where(scope_clause(uow.actor, policy, action))  # type: ignore[attr-defined]
