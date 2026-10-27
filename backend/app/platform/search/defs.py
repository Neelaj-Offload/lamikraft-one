"""Search provider contract (platform search, docs/PLAN.md shared kernel; legacy §10.2 #6 no regex).

Domain modules declare providers in ``ModuleManifest.search_providers``; ``app.platform.search`` runs the
providers the actor may read, groups hits and records recent searches. Providers must search through
``ScopedRepository`` (its scope clause plus escaped ILIKE / trigram terms) and never index or return restricted
fields. ``search`` returns the best ``limit`` hits already ordered in SQL (rank descending, ties by title)
before the LIMIT, so a page of a group never drops a better hit; the optional ``count`` gives the group total.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork


@dataclass(frozen=True)
class SearchHit:
    resource_type: str  # e.g. "catalogue.product"
    resource_id: uuid.UUID
    title: str  # "LK-OT-0450 · Oak serving tray 450"
    subtitle: str | None
    path: str  # canonical web route, e.g. "/products/<id>"
    rank: int = 0  # higher first; ties broken by title


@dataclass(frozen=True)
class SearchProvider:
    resource_type: str
    group: str  # display group: "Products", "Parties", "Quotes", ...
    permission: str  # read permission the actor must hold (any scope); rows are still scope-filtered
    search: Callable[[UnitOfWork, str, int], list[SearchHit]]  # (uow, query, limit) -> hits, best first
    #: (uow, query) -> number of matching records the actor may read; None: the group shows no total
    count: Callable[[UnitOfWork, str], int] | None = None
