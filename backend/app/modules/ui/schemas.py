"""Session bootstrap and poll payloads (api-conventions §8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.platform.identity.preferences import UiPreferences
from app.platform.identity.schemas import (
    BranchRef,
    CompanyRef,
    PermissionGrant,
    RoleRef,
    SessionView,
    TeamRef,
)

NavKey = Literal["today", "inbox", "sales", "products", "operations", "finance", "settings"]
GreetingPeriod = Literal["morning", "afternoon", "evening"]


class NavItem(BaseModel):
    key: NavKey
    path: str
    label: str


class BootstrapUser(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str | None


class BootstrapMembership(BaseModel):
    id: uuid.UUID
    display_name: str
    job_title: str | None
    role_names: list[str]
    roles: list[RoleRef]
    teams: list[TeamRef]
    branch_ids: list[uuid.UUID]
    is_demo: bool


class BootstrapPreferences(BaseModel):
    version: int
    ui: UiPreferences


class IntegrationModes(BaseModel):
    """Configured provider modes so the UI can label Demo / Not connected features truthfully."""

    ai: Literal["demo", "live"]
    whatsapp: Literal["demo", "live"]
    email: Literal["demo", "smtp"]


class SessionBootstrap(BaseModel):
    user: BootstrapUser
    membership: BootstrapMembership
    company: CompanyRef
    branches: list[BranchRef]
    time_zone: str
    locale: str
    server_now: datetime
    greeting_period: GreetingPeriod
    permissions: list[PermissionGrant]
    preferences: BootstrapPreferences
    nav: list[NavItem]
    #: readiness of every navigation area (an area is implemented when one of its modules is installed)
    features: dict[str, bool]
    integration_modes: IntegrationModes
    #: module-contributed sections (Inbox counts, current briefing version, ...); see app.platform.bootstrap
    sections: dict[str, Any]
    session: SessionView | None
    csrf_token: str


class UiPoll(BaseModel):
    sections: dict[str, Any]
