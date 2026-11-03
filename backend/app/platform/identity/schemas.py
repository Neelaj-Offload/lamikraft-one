"""Identity request and response models (snake_case JSON; timestamps RFC 3339 UTC)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

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
    #: active, or a sign-in step still to do: mfa_pending (enter a code) or mfa_enrollment_required (set one up)
    stage: Literal["active", "mfa_pending", "mfa_enrollment_required"] = "active"


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


class MembershipSummary(BaseModel):
    id: uuid.UUID
    status: str
    company: CompanyRef
    is_current: bool


class PermissionGrant(BaseModel):
    key: str
    scope: str


class PermissionOverrideView(BaseModel):
    """One open per-user override (grant or revoke; revoke always wins over roles and grants)."""

    id: uuid.UUID
    permission_key: str
    effect: Literal["grant", "revoke"]
    scope: str | None
    reason: str
    expires_at: datetime | None
    #: False once ``expires_at`` has passed (the override no longer applies)
    in_effect: bool
    created_at: datetime
    created_by: uuid.UUID | None


class MeRead(BaseModel):
    user: ProfileView
    #: the membership of the signed-in session, in detail
    membership: MembershipView
    #: every membership of this user in an active company (the current one included)
    memberships: list[MembershipSummary]
    #: effective permissions of the current membership (roles ∪ grants − revokes)
    permissions: list[PermissionGrant]
    #: the open per-user overrides behind those permissions
    overrides: list[PermissionOverrideView]
    preferences: Preferences
    session: SessionView | None
    time_zone: str
    locale: str


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    # the policy (12-256, common list, email/company names) is applied by the service
    new_password: str = Field(min_length=1, max_length=1024)


class PermissionOverridePut(BaseModel):
    """``PUT .../permission-overrides/{key}``: a grant needs a scope, a revoke has none; a reason is required."""

    model_config = ConfigDict(extra="forbid")

    effect: Literal["grant", "revoke"]
    scope: Literal["own", "team", "branch", "company"] | None = None
    reason: str = Field(min_length=1, max_length=500)
    expires_at: datetime | None = None


class PermissionOverrideList(BaseModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    items: list[PermissionOverrideView]


class PreferencesUpdated(BaseModel):
    preferences: Preferences
    changed_fields: list[str]


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


# ---- MFA (Slice 2) -------------------------------------------------------------------------------------------
class MfaCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: a 6-digit authenticator code, or an unused recovery code (``xxxxx-xxxxx``) where allowed
    code: str = Field(min_length=6, max_length=20)


class ReauthRequest(BaseModel):
    """Confirm it is you: either the password, or a code from the authenticator (which also verifies MFA)."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, min_length=1, max_length=1024)
    code: str | None = Field(default=None, min_length=6, max_length=20)


class ReauthResult(BaseModel):
    recent_auth_at: datetime
    auth_strength: Literal["password", "mfa", "demo_link"]


class MfaStatus(BaseModel):
    enrolled: bool
    #: an enrolment was started but not confirmed yet
    pending: bool
    confirmed_at: datetime | None
    recovery_codes_remaining: int
    #: your access requires two-step sign-in (it cannot be removed)
    required: bool
    #: the current session passed a code check
    session_verified: bool


class MfaEnrollment(BaseModel):
    """Shown once: scan the QR code or type the secret into an authenticator app, then confirm with a code."""

    factor_id: uuid.UUID
    secret: str
    otpauth_uri: str
    qr_svg: str


class MfaConfirmed(BaseModel):
    #: shown once; each works once instead of an authenticator code
    recovery_codes: list[str]
    confirmed_at: datetime
    session: SessionInfo | None = None


class RecoveryCodes(BaseModel):
    recovery_codes: list[str]


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


# ---- invitations and password resets (Slice 2) ----------------------------------------------------------------
class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=120)
    full_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=120)
    role_keys: list[str] = Field(min_length=1, max_length=10)
    branch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    default_branch_id: uuid.UUID | None = None
    manager_user_id: uuid.UUID | None = None


class Delivery(BaseModel):
    """How the link reached the person. In demo mode nothing is sent: the message is written to the demo outbox
    and the link is shown once to the administrator who asked for it."""

    mode: Literal["demo_outbox", "email"]
    label: str
    #: demo mode only, shown once: the link to hand over (the token is in the URL fragment)
    manual_link: str | None = None
    #: demo mode only: the .eml file name in the outbox
    outbox_file: str | None = None


class InvitationView(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str
    status: Literal["open", "accepted", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime
    send_count: int
    last_sent_at: datetime
    invited_by_name: str | None


class InvitationIssued(BaseModel):
    invitation: InvitationView
    delivery: Delivery


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class InvitationPreview(BaseModel):
    """What the invite page shows before the person sets a password (no secrets)."""

    email: str
    display_name: str
    company_name: str
    expires_at: datetime
    #: the person already has a Lamikraft password (from another company): they confirm it instead of choosing one
    has_password: bool


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class PasswordResetRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)


class PasswordResetComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class PasswordResetIssued(BaseModel):
    """An administrator-issued reset: a one-time link (24 h), never a password."""

    user_id: uuid.UUID
    expires_at: datetime
    delivery: Delivery


class SessionListItem(BaseModel):
    id: uuid.UUID
    auth_method: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    mfa_verified: bool
    #: the session this request came from
    current: bool


class SessionList(BaseModel):
    items: list[SessionListItem]


class RevokedCount(BaseModel):
    revoked: int


# ---- delegation (Slice 2) ----------------------------------------------------------------------------------
class CapabilityView(BaseModel):
    allowed: bool
    reason_code: str | None = None


class DelegationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: omit to delegate your own reach; another member's needs identity.delegation.manage
    delegator_user_id: uuid.UUID | None = None
    delegate_user_id: uuid.UUID
    permission_keys: list[str] = Field(min_length=1, max_length=40)
    include_approvals: bool = False
    #: omit to start now
    starts_at: datetime | None = None
    ends_at: datetime
    reason: Literal["leave", "travel", "workload", "other"]
    note: str | None = Field(default=None, max_length=500)


class DelegationView(BaseModel):
    id: uuid.UUID
    delegator_user_id: uuid.UUID
    delegator_name: str
    delegate_user_id: uuid.UUID
    delegate_name: str
    permission_keys: list[str]
    include_approvals: bool
    starts_at: datetime
    ends_at: datetime
    reason: Literal["leave", "travel", "workload", "other"]
    note: str | None
    status: Literal["scheduled", "active", "ended", "cancelled"]
    cancelled_at: datetime | None
    version: int
    capabilities: dict[str, CapabilityView]


class DelegationList(BaseModel):
    items: list[DelegationView]
    #: keys that may be delegated at all (the delegator must hold them; the delegate too, for them to apply)
    delegable_keys: list[str]


# ---- roles, catalogue and the simulator (Slice 2) -------------------------------------------------------------
ScopeName = Literal["own", "team", "branch", "company"]


class PermissionInfo(BaseModel):
    key: str
    module: str
    resource: str
    action: str
    description: str
    allowed_scopes: list[ScopeName]
    delegable: bool
    requires_mfa: bool
    requires_recent_auth: bool
    field_guard: bool
    sensitive: bool


class PermissionCatalogue(BaseModel):
    items: list[PermissionInfo]


class RoleEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=5, max_length=120)
    effect: Literal["grant", "deny"] = "grant"
    #: required for a grant; ignored for a deny
    scope: ScopeName | None = None


class RoleEntryView(BaseModel):
    key: str
    effect: Literal["grant", "deny"]
    scope: ScopeName | None


class RoleSummary(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    kind: Literal["system_template", "custom"]
    inherits: RoleRef | None
    is_assignable: bool
    archived: bool
    member_count: int
    grant_count: int
    deny_count: int
    version: int


class RoleList(BaseModel):
    items: list[RoleSummary]


class SourceView(BaseModel):
    """Why a key is (or is not) in effect."""

    kind: Literal["role", "inherited", "employee_base", "override_grant", "override_revoke", "role_deny", "delegation"]
    label: str
    role_key: str | None = None
    scope: ScopeName | None = None
    expires_at: datetime | None = None


class EffectiveKey(BaseModel):
    key: str
    #: the resolved scope; None when the key is not in effect (see ``sources`` for why)
    scope: ScopeName | None
    sources: list[SourceView]


class RoleDetail(BaseModel):
    role: RoleSummary
    entries: list[RoleEntryView]
    #: root → this role
    chain: list[RoleRef]
    effective: list[EffectiveKey]
    capabilities: dict[str, CapabilityView]


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=41, pattern=r"^[a-z][a-z0-9_]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    inherits_role_id: uuid.UUID | None = None
    entries: list[RoleEntryIn] = Field(default_factory=list, max_length=300)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    inherits_role_id: uuid.UUID | None = None
    #: true to drop the parent role (``inherits_role_id`` null alone means "unchanged")
    clear_inherits: bool = False
    #: replaces the role's own entries when given
    entries: list[RoleEntryIn] | None = Field(default=None, max_length=300)


class EffectiveAccess(BaseModel):
    """The role simulator: what a member (or a role on its own) can do, and where each right comes from."""

    subject: Literal["member", "role"]
    user_id: uuid.UUID | None
    display_name: str | None
    role_keys: list[str]
    membership_status: str | None
    granted: list[EffectiveKey]
    #: keys a role or the member would otherwise have, removed by a role deny or a per-user revoke
    removed: list[EffectiveKey]
    #: delegated reach (never extra keys): key -> the people whose records it reaches
    delegated: list[EffectiveKey]


class AccessCheck(BaseModel):
    """"Can X do Y?" with the reasons."""

    permission_key: str
    allowed: bool
    scope: ScopeName | None
    needed_scope: ScopeName
    reasons: list[str]
    sources: list[SourceView]


# ---- user administration (Slice 2) ---------------------------------------------------------------------------
class UserListItem(BaseModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    #: "Name (inactive)" once deactivated (attribution survives)
    display_name: str
    email: str | None
    job_title: str | None
    status: Literal["invited", "active", "suspended", "deactivated"]
    roles: list[RoleRef]
    mfa_enrolled: bool
    last_login_at: datetime | None


class UserList(BaseModel):
    items: list[UserListItem]
    total: int
    limit: int
    offset: int


class UserDetail(BaseModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str | None
    display_name: str
    full_name: str | None
    job_title: str | None
    department: str | None
    status: Literal["invited", "active", "suspended", "deactivated"]
    roles: list[RoleRef]
    branches: list[BranchRef]
    default_branch_id: uuid.UUID | None
    teams: list[TeamRef]
    manager: ManagerRef | None
    mfa_enrolled: bool
    mfa_required: bool
    last_login_at: datetime | None
    joined_on: str | None
    deactivated_at: datetime | None
    deactivation_reason: str | None
    invitations: list[InvitationView]
    overrides: list[PermissionOverrideView]
    #: membership version: send it back as ``expected_version``
    version: int
    is_self: bool
    capabilities: dict[str, CapabilityView]


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    full_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=80)
    manager_user_id: uuid.UUID | None = None
    clear_manager: bool = False
    default_branch_id: uuid.UUID | None = None


class RolesPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_keys: list[str] = Field(min_length=1, max_length=10)


class BranchesPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_ids: list[uuid.UUID] = Field(max_length=20)


class DeactivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    #: the member who takes over open owned work (modules reassign through the deactivation event)
    reassign_to_user_id: uuid.UUID | None = None


# ---- leave (absence) and access requests (Slice 2) -------------------------------------------------------------
class AbsenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["leave", "holiday", "training", "other"] = "leave"
    starts_on: date
    ends_on: date
    #: who should pick up your open work while you are away (a hint for the Inbox and briefings)
    cover_user_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class AbsenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class AbsenceView(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    kind: Literal["leave", "holiday", "training", "other"]
    starts_on: date
    ends_on: date
    status: Literal["requested", "approved", "rejected", "cancelled"]
    note: str | None
    cover_user_id: uuid.UUID | None
    cover_name: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    version: int
    capabilities: dict[str, CapabilityView]


class AbsenceList(BaseModel):
    items: list[AbsenceView]


class AccessRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_key: str = Field(min_length=5, max_length=120)
    scope: Literal["own", "team", "branch", "company"] = "own"
    reason: str = Field(min_length=1, max_length=500)
    duration_days: int = Field(default=7, ge=1, le=90)


class AccessRequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)
    #: the approver may shorten the grant
    duration_days: int | None = Field(default=None, ge=1, le=90)


class AccessRequestView(BaseModel):
    id: uuid.UUID
    requester_user_id: uuid.UUID
    requester_name: str
    permission_key: str
    scope: Literal["own", "team", "branch", "company"]
    reason: str
    duration_days: int
    status: Literal["pending", "approved", "rejected", "withdrawn"]
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    grant_expires_at: datetime | None
    created_at: datetime
    version: int
    capabilities: dict[str, CapabilityView]


class AccessRequestList(BaseModel):
    items: list[AccessRequestView]
