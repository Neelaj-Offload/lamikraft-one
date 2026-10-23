"""Org tables: company and branch (the tenancy boundary; ``company`` is RLS-exempt), typed settings with their
revision history, the global currency reference (RLS-exempt) and the per-company unit-of-measure master."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    ActorStampMixin,
    ArchivableMixin,
    Base,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    enum_column,
)


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "company"
    __tenant_rls__ = False

    company_key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    default_time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en-IN")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    authz_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("company_key ~ '^[a-z][a-z0-9-]{1,39}$'", name="company_key_format"),
        CheckConstraint("status IN ('active','suspended')", name="status_values"),
    )


class Branch(IdMixin, TimestampMixin, ArchivableMixin, Base):
    __tablename__ = "branch"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_head_office: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("uq_branch_company_code", "company_id", "branch_code", unique=True),
        Index(
            "uq_branch_one_head_office",
            "company_id",
            unique=True,
            postgresql_where=text("is_head_office AND archived_at IS NULL"),
        ),
        CheckConstraint("gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'", name="gstin_format"),
    )


# ---- settings ---------------------------------------------------------------------------------------
class Setting(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, VersionMixin, Base):
    """One typed setting value per (company, branch, key); its schema lives in the ``SettingDef``."""

    __tablename__ = "setting"

    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    __table_args__ = (
        Index(
            "uq_setting_scope_key", "company_id", "branch_id", "key", unique=True, postgresql_nulls_not_distinct=True
        ),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,63}$'", name="key_format"),
    )


class SettingRevision(IdMixin, TenantMixin, Base):
    """Immutable history of every setting write (issued documents can cite the revision they used)."""

    __tablename__ = "setting_revision"
    __append_only__ = True

    setting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("setting.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("uq_setting_revision_version", "setting_id", "version", unique=True),
        Index("ix_setting_revision_key", "company_id", "key", "changed_at"),
    )


# ---- reference data -----------------------------------------------------------------------------------
class Currency(Base):
    """Global ISO currency reference (RLS-exempt; lk_app may only read it)."""

    __tablename__ = "currency"
    __tenant_rls__ = False

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    symbol: Mapped[str] = mapped_column(String(8), nullable=False)
    exponent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z]{3}$'", name="code_format"),
        CheckConstraint("exponent BETWEEN 0 AND 4", name="exponent_range"),
    )


class UomDimension(StrEnum):
    COUNT = "count"
    PACK = "pack"
    MASS = "mass"
    LENGTH = "length"
    AREA = "area"


class Uom(IdMixin, TenantMixin, TimestampMixin, Base):
    """Unit of measure master (conventions §6). Integer units accept whole numbers only.

    Quantity columns elsewhere reference ``(company_id, uom_code)`` -> ``uom(company_id, code)``.
    """

    __tablename__ = "uom"

    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    dimension: Mapped[str] = enum_column(UomDimension, length=10)
    is_integer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_uom_company_id_code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,15}$'", name="code_format"),
        CheckConstraint("dimension IN ('count','pack','mass','length','area')", name="dimension_values"),
    )


class UomAlias(IdMixin, TenantMixin, TimestampMixin, Base):
    """Free-text unit spellings (imports, voice, legacy data) mapped to a canonical code."""

    __tablename__ = "uom_alias"

    alias: Mapped[str] = mapped_column(String(40), nullable=False)
    uom_code: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("uq_uom_alias_company_alias", "company_id", "alias", unique=True),
        ForeignKeyConstraint(
            ["company_id", "uom_code"], ["uom.company_id", "uom.code"], name="fk_uom_alias_uom", ondelete="RESTRICT"
        ),
    )


class UomConversionProvenance(StrEnum):
    STANDARD = "standard"
    PRODUCT_PACKAGING = "product_packaging"
    MANUAL = "manual"
    IMPORT = "import"


class UomConversion(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin, Base):
    """``1 from_code = factor to_code``; product-specific rows win over generic ones. Never guessed."""

    __tablename__ = "uom_conversion"

    from_code: Mapped[str] = mapped_column(String(16), nullable=False)
    to_code: Mapped[str] = mapped_column(String(16), nullable=False)
    factor: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    #: catalogue product id for packaging conversions (no FK: platform cannot reference a module table)
    product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    provenance: Mapped[str] = enum_column(UomConversionProvenance, length=20, default=UomConversionProvenance.MANUAL)

    __table_args__ = (
        Index(
            "uq_uom_conversion_pair",
            "company_id",
            "from_code",
            "to_code",
            "product_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["company_id", "from_code"],
            ["uom.company_id", "uom.code"],
            name="fk_uom_conversion_from_uom",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "to_code"],
            ["uom.company_id", "uom.code"],
            name="fk_uom_conversion_to_uom",
            ondelete="RESTRICT",
        ),
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint("from_code <> to_code", name="distinct_units"),
        CheckConstraint(
            "provenance IN ('standard','product_packaging','manual','import')", name="provenance_values"
        ),
    )
