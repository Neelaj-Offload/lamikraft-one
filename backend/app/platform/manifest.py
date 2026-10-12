"""Module manifests: each platform or domain module declares what it contributes.

A module package exposes ``MANIFEST = ModuleManifest(...)`` in ``<pkg>/manifest.py``. Contributions
are distributed (no central permission/event/settings file to fight over); ``app.registry``
collects and cross-validates them at startup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.platform.authz.permissions import PermissionDef, Scope
from app.platform.authz.policy import ResourcePolicy
from app.platform.events.defs import EventDef, Subscription
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.numbering.defs import SequenceDef


@dataclass
class ModuleManifest:
    name: str
    #: dotted path imported so SQLAlchemy models register with the metadata
    models: tuple[str, ...] = ()
    permissions: list[PermissionDef] = field(default_factory=list)
    #: role template key -> {permission key -> scope}
    template_grants: dict[str, dict[str, Scope]] = field(default_factory=dict)
    events: list[EventDef] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    jobs: list[JobDef] = field(default_factory=list)
    schedules: list[ScheduleDef] = field(default_factory=list)
    sequences: list[SequenceDef] = field(default_factory=list)
    policies: list[ResourcePolicy] = field(default_factory=list)
    #: callables returning (router, prefix) pairs; lazy so imports stay acyclic
    routers: list[Callable[[], Any]] = field(default_factory=list)
    #: agent tools, settings definitions and search providers (typed by their owning platform modules)
    tools: list[Any] = field(default_factory=list)
    settings: list[Any] = field(default_factory=list)
    search_providers: list[Any] = field(default_factory=list)
    #: demo fixture seeds (app.seed.context.SeedDef), run in order by ``lk seed demo``
    seeds: list[Any] = field(default_factory=list)
    #: called once after all manifests are loaded (e.g. register hooks); keep side effects idempotent
    on_load: Callable[[], None] | None = None
