"""Declarative base, naming convention and column mixins.

Conventions (docs/architecture/conventions.md):
- ``id`` is a UUIDv7 primary key; business keys are separate columns.
- Tenant tables carry ``company_id`` and get forced row-level security in their migration.
- Business timestamps are stamped from the injected Clock by the unit of work, never DB ``now()``.
- Editable drafts carry ``version`` (SQLAlchemy ``version_id_col``) for optimistic concurrency.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }

    #: Set True on tables that must reject UPDATE/DELETE (audit, ledgers, issued revisions).
    __append_only__: bool = False
    #: Set False on platform-internal tables that are deliberately exempt from tenant RLS.
    __tenant_rls__: bool = True
    #: Set True to have the unit of work write an audit diff on changes.
    __audited__: bool = False


def new_id() -> uuid.UUID:
    return uuid.uuid7()


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)


class TenantMixin:
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class BranchMixin:
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("branch.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActorStampMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.version}  # type: ignore[attr-defined]


class ArchivableMixin:
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )


class TenantEntity(IdMixin, TenantMixin, TimestampMixin, ActorStampMixin):
    """The common shape of a tenant-owned business record."""


def money_column(nullable: bool = False) -> Any:
    return mapped_column(Numeric(18, 4), nullable=nullable)


def currency_column(nullable: bool = False, default: str | None = None) -> Any:
    return mapped_column(CHAR(3), nullable=nullable, default=default)


def quantity_column(nullable: bool = False) -> Any:
    return mapped_column(Numeric(18, 6), nullable=nullable)


def dimension_column(nullable: bool = True) -> Any:
    return mapped_column(Numeric(12, 3), nullable=nullable)


def enum_column(values: type, length: int = 40, nullable: bool = False, default: Any = None) -> Any:
    """A varchar column whose allowed values come from a Python StrEnum (CHECK added in migration)."""
    return mapped_column(String(length), nullable=nullable, default=default, info={"enum": values})


DecimalT = Decimal
