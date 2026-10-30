"""Import workbench tables: jobs, staged source rows, row issues (never capped) and the change log used by rollback.

A job stores its source file in ``platform/files`` (``file_object`` id + sha256) and every parsed row verbatim in
``imports_staged_row.raw`` (original header -> cell text), so history, quarantine recheck and the before/after review
never need the file again. ``imports_change`` records each entity write with its before/after field values and the
entity version after the write: rollback restores only those fields and only while the version is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, TimestampMixin, VersionMixin


class ImportType(StrEnum):
    CATEGORY_TAXONOMY = "category_taxonomy"
    PRODUCTS_MASTER = "products_master"
    PRICING = "pricing"
    PACKAGING = "packaging"
    SPECIFICATIONS = "specifications"
    MEDIA = "media"
    LOOKUP_REFERENCE = "lookup_reference"


class JobStatus(StrEnum):
    PARSED = "parsed"
    VALIDATED = "validated"
    COMMITTING = "committing"
    COMMITTED = "committed"
    COMMIT_FAILED = "commit_failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"
    PARTIALLY_ROLLED_BACK = "partially_rolled_back"


class RowStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    WARNING = "warning"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    DUPLICATE_IDENTICAL = "duplicate_identical"
    COMMITTED = "committed"
    UNCHANGED = "unchanged"
    RELEASED = "released"


class RowAction(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    UNCHANGED = "unchanged"


class Severity(StrEnum):
    ERROR = "error"
    QUARANTINE = "quarantine"
    WARNING = "warning"
    INFO = "info"


class ChangeOp(StrEnum):
    INSERT = "insert"
    UPDATE = "update"


class ImportJob(TenantEntity, VersionMixin, Base):
    __tablename__ = "imports_job"

    import_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("file_object.id", ondelete="RESTRICT"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encoding: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delimiter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    #: [{"index", "original", "normalised"}] in sheet order
    headers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    #: original header -> field name (or null to ignore the column)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports_job.id", ondelete="RESTRICT"), nullable=True
    )
    validation_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    rollback_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        Index("ix_imports_job_company_created", "company_id", "created_at"),
        Index("ix_imports_job_sha256", "company_id", "file_sha256"),
        Index(
            "uq_imports_job_one_writer",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'committing'"),
        ),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("file_format IN ('csv','xlsx')", name="file_format_values"),
    )


class StagedRow(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "imports_staged_row"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports_job.id", ondelete="CASCADE"), nullable=False
    )
    #: physical sheet row (the header is row 1)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    natural_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=RowStatus.PENDING.value)
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    target_version_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released_to_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "row_number", name="uq_imports_staged_row_number"),
        Index("ix_imports_staged_row_status", "job_id", "status"),
        Index("ix_imports_staged_row_key", "job_id", "natural_key"),
    )


class RowIssue(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "imports_row_issue"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports_job.id", ondelete="CASCADE"), nullable=False
    )
    staged_row_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports_staged_row.id", ondelete="CASCADE"), nullable=True
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_original: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: "parse" and "validate" issues are rebuilt by their step; "commit" issues are kept
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="validate")

    __table_args__ = (Index("ix_imports_row_issue_job", "job_id", "severity", "code"),)


class ImportChange(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "imports_change"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("imports_job.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    staged_row_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    entity_table: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    op: Mapped[str] = mapped_column(String(20), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    changed_fields: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_imports_change_seq"),
        Index("ix_imports_change_entity", "entity_table", "entity_id"),
    )


__all__ = [
    "ChangeOp",
    "ImportChange",
    "ImportJob",
    "ImportType",
    "JobStatus",
    "RowAction",
    "RowIssue",
    "RowStatus",
    "Severity",
    "StagedRow",
]
