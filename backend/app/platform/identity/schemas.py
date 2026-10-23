"""Identity request and response models (snake_case JSON; timestamps RFC 3339 UTC)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.platform.identity.preferences import Preferences


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    # 1024 caps the request size; the policy (12-256) is applied by the service with the generic message
    password: str = Field(min_length=1, max_length=1024)


class DemoSignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str | None


class CompanyRef(BaseModel):
    id: uuid.UUID
    key: str
    display_name: str
    legal_name: str
    is_demo: bool
    base_currency: str


class SessionView(BaseModel):
    id: uuid.UUID
    auth_method: str
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class SessionInfo(BaseModel):
    """Returned by sign-in; the session token itself travels only in the HttpOnly cookie."""

    user: UserRef
    company: CompanyRef
    membership_id: uuid.UUID
    session: SessionView
    csrf_token: str


class RoleRef(BaseModel):
    key: str
    name: str


class BranchRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    is_head_office: bool


class TeamRef(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    team_role: str


class ManagerRef(BaseModel):
    membership_id: uuid.UUID
    display_name: str


class MembershipView(BaseModel):
    id: uuid.UUID
    status: str
    job_title: str | None
    company: CompanyRef
    roles: list[RoleRef]
    branches: list[BranchRef]
    teams: list[TeamRef]
    manager: ManagerRef | None
    joined_on: str | None


class ProfileView(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str
    full_name: str | None
    locale: str
    time_zone: str | None


class MeRead(BaseModel):
    user: ProfileView
    membership: MembershipView
    preferences: Preferences
    session: SessionView | None
    time_zone: str
    locale: str


class PreferencesUpdated(BaseModel):
    preferences: Preferences
    changed_fields: list[str]


class PermissionGrant(BaseModel):
    key: str
    scope: str


class SessionProfile(BaseModel):
    """Everything the session bootstrap needs from identity, computed for the signed-in actor."""

    user: UserRef
    membership: MembershipView
    company: CompanyRef
    branches: list[BranchRef]
    time_zone: str
    locale: str
    permissions: list[PermissionGrant]
    preferences: Preferences
    session: SessionView | None
