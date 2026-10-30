"""Session bootstrap and UI poll.

Navigation lists only authorised, implemented areas (api-conventions §8): Today, Inbox and Settings for every
active member; Sales, Products, Operations and Finance when the area is implemented (one of its backend
modules is installed) **and** the actor holds at least one key of the area's modules (the same prefixes as
``apps/web/src/lib/routes.ts``). ``features`` reports the readiness of every area. Global keys drive
navigation only; records stay guarded by their services. The greeting period comes from the Clock in the
actor's resolved time zone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.platform.bootstrap import build_sections
from app.platform.identity import service as identity
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

from .schemas import (
    BootstrapMembership,
    BootstrapPreferences,
    BootstrapUser,
    IntegrationModes,
    NavItem,
    SessionBootstrap,
    UiPoll,
)


@dataclass(frozen=True)
class NavArea:
    key: str
    path: str
    label: str
    #: backend modules behind the area; empty means always available (Today, Inbox, Settings)
    modules: tuple[str, ...] = ()

    @property
    def prefixes(self) -> tuple[str, ...]:
        return tuple(f"{m}." for m in self.modules)


NAV_AREAS: tuple[NavArea, ...] = (
    NavArea("today", "/today", "Today"),
    NavArea("inbox", "/inbox", "Inbox"),
    NavArea("sales", "/sales", "Sales", ("sales",)),
    NavArea("products", "/products", "Products", ("catalogue",)),
    NavArea("operations", "/operations", "Operations", ("challans", "cutting", "inventory", "procurement", "production", "logistics")),
    NavArea("finance", "/finance", "Finance", ("finance",)),
    NavArea("settings", "/settings", "Settings"),
)


def installed_module_names() -> frozenset[str]:
    from app.registry import get_registry

    return frozenset(m.name for m in get_registry().manifests)


def area_readiness(installed: Iterable[str] | None = None) -> dict[str, bool]:
    names = frozenset(installed) if installed is not None else installed_module_names()
    return {a.key: not a.modules or any(m in names for m in a.modules) for a in NAV_AREAS}


def nav_for(permission_keys: Iterable[str], ready: dict[str, bool] | None = None) -> list[NavItem]:
    keys = list(permission_keys)
    ready = ready if ready is not None else area_readiness()
    out = []
    for area in NAV_AREAS:
        if not ready.get(area.key, False):
            continue
        if not area.modules or any(k.startswith(area.prefixes) for k in keys):
            out.append(NavItem(key=area.key, path=area.path, label=area.label))  # type: ignore[arg-type]
    return out


def greeting_period(now: datetime, time_zone: str) -> str:
    """morning 05:00–11:59, afternoon 12:00–16:59, evening otherwise (local time)."""
    hour = now.astimezone(ZoneInfo(time_zone)).hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    return "evening"


@command()
def bootstrap(uow: UnitOfWork) -> SessionBootstrap:
    profile = identity.session_profile(uow)
    now = uow.now()
    settings = get_settings()
    csrf = identity.rotate_csrf(uow)
    ready = area_readiness()
    return SessionBootstrap(
        user=BootstrapUser(id=profile.user.id, display_name=profile.user.display_name, email=profile.user.email),
        membership=BootstrapMembership(
            id=profile.membership.id,
            display_name=profile.user.display_name,
            job_title=profile.membership.job_title,
            role_names=[r.name for r in profile.membership.roles],
            roles=profile.membership.roles,
            teams=profile.membership.teams,
            branch_ids=[b.id for b in profile.membership.branches],
            is_demo=profile.company.is_demo,
        ),
        company=profile.company,
        branches=profile.branches,
        time_zone=profile.time_zone,
        locale=profile.locale,
        server_now=now,
        greeting_period=greeting_period(now, profile.time_zone),  # type: ignore[arg-type]
        permissions=profile.permissions,
        preferences=BootstrapPreferences(version=profile.preferences.version, ui=profile.preferences.ui),
        nav=nav_for((p.key for p in profile.permissions), ready),
        features=ready,
        integration_modes=IntegrationModes(ai=settings.ai_mode, whatsapp=settings.whatsapp_mode, email=settings.email_mode),
        sections=build_sections(uow),
        session=profile.session,
        csrf_token=csrf,
    )


@query()
def poll(uow: UnitOfWork) -> UiPoll:
    return UiPoll(sections=build_sections(uow, poll_only=True))


def etag_of(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    return f'"{digest[:32]}"'


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = [c.strip().removeprefix("W/") for c in if_none_match.split(",")]
    return "*" in candidates or etag in candidates
