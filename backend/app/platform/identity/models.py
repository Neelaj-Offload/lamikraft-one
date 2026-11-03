"""Core identity tables. ``app_user`` is global (RLS-exempt); memberships are tenant-scoped.

Users are never hard-deleted so historical attribution survives. A ``historical`` user has no
credentials and represents a legacy person migrated only for attribution.

Access model (docs/architecture/permissions.md §9-§10):
- ``permission`` is the global catalogue synced from code (RLS-exempt);
- ``role`` rows are per-company system templates (custom roles arrive in Slice 2) with ``role_permission`` grants;
- ``membership_role`` / ``membership_branch`` attach roles and branches to a membership;
- ``user_permission_override`` adds per-user grants or revokes (revoke always wins);
- ``legacy_permission_alias`` maps the 14 legacy permissions (global reference data synced from code);
- ``user_preference`` holds the typed personal preference sections (user-level, RLS-exempt).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import ArchivableMixin, Base, IdMixin, TenantMixin, TimestampMixin, VersionMixin


def in_values(column: str, values: type[StrEnum]) -> str:
    """SQL text for a ``column IN (...)`` CHECK built from a StrEnum (the migration uses the same values)."""
    return f"{column} IN (" + ",".join(f"'{v.value}'" for v in values) + ")"


class ScopeLabel(StrEnum):
    OWN = "own"
    TEAM = "team"
    BRANCH = "branch"
    COMPANY = "company"


class RoleKind(StrEnum):
    SYSTEM_TEMPLATE = "system_template"
    CUSTOM = "custom"


class GrantEffect(StrEnum):
    GRANT = "grant"
    DENY = "deny"


class OverrideEffect(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"


class AppUser(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "app_user"
    __tenant_rls__ = False

    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(254), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-IN")
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_app_user_email_normalized", "email_normalized", unique=True),
        CheckConstraint("status IN ('invited','active','disabled','historical')", name="status_values"),
        CheckConstraint("status <> 'historical' OR password_hash IS NULL", name="historical_no_credentials"),
    )


class Membership(IdMixin, TenantMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "membership"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    employee_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(80), nullable=True)
    manager_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=True
    )
    default_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    work_time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("uq_membership_company_user", "company_id", "user_id", unique=True),
        Index(
            "uq_membership_employee_code",
            "company_id",
            "employee_code",
            unique=True,
            postgresql_where="employee_code IS NOT NULL",
        ),
        CheckConstraint("status IN ('invited','active','suspended','deactivated')", name="status_values"),
    )


# ---- permission catalogue (global, synced from code) ---------------------------------------------
class Permission(Base):
    __tablename__ = "permission"
    __tenant_rls__ = False

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    resource: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    allowed_scopes: Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False)
    delegable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_recent_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    field_guard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default=Sensitivity.NORMAL.value)
    slice_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(in_values("sensitivity", Sensitivity), name="sensitivity_values"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]*[.][a-z][a-z0-9_]*[.][a-z][a-z0-9_]*$'", name="key_format"),
    )


class LegacyPermissionAlias(Base):
    """The single mapping of the 14 legacy permissions (permissions.md §8), synced from code.

    ``scope`` is a fixed expansion scope; ``scope_from_key`` means "the expanded scope of that key"
    (``fallback_scope`` when the key is absent; no grant when both are absent).
    """

    __tablename__ = "legacy_permission_alias"
    __tenant_rls__ = False

    legacy_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    permission_key: Mapped[str] = mapped_column(
        String(120), ForeignKey("permission.key", ondelete="RESTRICT"), primary_key=True
    )
    scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    scope_from_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fallback_scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        CheckConstraint("(scope IS NULL) <> (scope_from_key IS NULL)", name="one_scope_source"),
        CheckConstraint("scope IS NULL OR " + in_values("scope", ScopeLabel), name="scope_values"),
        CheckConstraint(
            "fallback_scope IS NULL OR " + in_values("fallback_scope", ScopeLabel), name="fallback_scope_values"
        ),
    )


# ---- roles (per company) ---------------------------------------------------------------------------
class Role(IdMixin, TenantMixin, TimestampMixin, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "role"

    role_key: Mapped[str] = mapped_column(String(41), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=RoleKind.SYSTEM_TEMPLATE.value)
    template_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_assignable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: custom roles inherit a parent role of the same company (no cycles, at most 4 levels; checked by the service)
    inherits_role_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("uq_role_company_key", "company_id", "role_key", unique=True),
        CheckConstraint("role_key ~ '^[a-z][a-z0-9_]{1,40}$'", name="role_key_format"),
        CheckConstraint(in_values("kind", RoleKind), name="kind_values"),
        CheckConstraint("inherits_role_id IS NULL OR inherits_role_id <> id", name="no_self_inheritance"),
        CheckConstraint("kind = 'custom' OR inherits_role_id IS NULL", name="templates_do_not_inherit"),
    )


class RolePermission(TenantMixin, Base):
    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        String(120), ForeignKey("permission.key", ondelete="RESTRICT"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    effect: Mapped[str] = mapped_column(String(10), nullable=False, default=GrantEffect.GRANT.value)

    __table_args__ = (
        CheckConstraint(in_values("scope", ScopeLabel), name="scope_values"),
        CheckConstraint(in_values("effect", GrantEffect), name="effect_values"),
    )


class MembershipRole(TenantMixin, Base):
    __tablename__ = "membership_role"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("role.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_membership_role_role", "company_id", "role_id"),)


class MembershipBranch(TenantMixin, Base):
    __tablename__ = "membership_branch"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="CASCADE"), primary_key=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserPermissionOverride(IdMixin, TenantMixin, TimestampMixin, VersionMixin, ArchivableMixin, Base):
    __tablename__ = "user_permission_override"

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("membership.id", ondelete="RESTRICT"), nullable=False
    )
    permission_key: Mapped[str] = mapped_column(
        String(120), ForeignKey("permission.key", ondelete="RESTRICT"), nullable=False
    )
    effect: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_user_permission_override_open",
            "membership_id",
            "permission_key",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index("ix_user_permission_override_membership", "company_id", "membership_id"),
        CheckConstraint(in_values("effect", OverrideEffect), name="effect_values"),
        CheckConstraint("scope IS NULL OR " + in_values("scope", ScopeLabel), name="scope_values"),
        CheckConstraint("(effect = 'grant') = (scope IS NOT NULL)", name="scope_only_for_grant"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_present"),
    )


# ---- preferences (user-level) ----------------------------------------------------------------------
class UserPreference(TimestampMixin, VersionMixin, Base):
    """Typed personal preference sections; validated by ``app.platform.identity.preferences`` on write."""

    __tablename__ = "user_preference"
    __tenant_rls__ = False

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    ui: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    locale: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    briefing: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    voice: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assistant: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
