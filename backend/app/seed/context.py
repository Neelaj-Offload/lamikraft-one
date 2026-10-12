"""Seed orchestration contract for the canonical fixture world (docs/architecture/fixtures.md).

Each module contributes ``SeedDef``s in its manifest (``seeds=[...]``). ``lk seed demo`` runs them in
``order`` against one demo company, moving the clock to each fact's timestamp so history is real
(created through services, events emitted and processed). Seeds share references through
``SeedContext.refs`` using the fixture keys (``MEERA``, ``NORDHAUS``, ``OAK_TRAY``, ``PRIOR_WON`` ...);
tests import the same keys, never literals.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock

IST = ZoneInfo("Asia/Kolkata")
#: D0 — Monday 2026-10-12 08:55 IST (03:25Z)
D0 = datetime(2026, 10, 12, 8, 55, tzinfo=IST)


@dataclass
class SeedContext:
    company_id: uuid.UUID
    clock: FrozenClock
    #: fixture key -> id (users, parties, products, price lists, quotes, proposals ...)
    refs: dict[str, uuid.UUID] = field(default_factory=dict)
    #: free-form facts later seeds need (e.g. issued numbers)
    facts: dict[str, Any] = field(default_factory=dict)
    slice_max: int = 1

    def at(self, when: datetime) -> None:
        self.clock.set(when)

    def ref(self, key: str) -> uuid.UUID:
        try:
            return self.refs[key]
        except KeyError as exc:
            raise KeyError(f"fixture key {key} not seeded yet (check seed order)") from exc


@dataclass(frozen=True)
class SeedDef:
    name: str
    order: int  # identity 10, parties 20, catalogue 30, pricing 40, sales 50, approvals 60, tasks/briefings 80
    run: Callable[[SeedContext], None]
    slice_no: int = 1
