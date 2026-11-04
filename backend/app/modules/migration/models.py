"""Migration tables (Slice 5): runs, quarantine issues, rerunnable ID maps, candidate party links, the exact legacy
document archive, opening-balance batches and backup records.

- ``migration_run``: one dry run or apply over one source directory; ``source_digest`` is the sha256 over the
  sorted (file name, file sha256) list, ``report`` the reconciliation report (counts, totals by currency, links, file
  hashes). Runs are history: never deleted.
- ``migration_issue``: every quarantined, rejected or noteworthy source row of a run, with the original row values
  (``raw``) and its row reference (file, row number, source key). Never capped.
- ``migration_id_map``: the rerunnable mapping ``UNIQUE(company_id, source_entity, source_key)`` -> business key and,
  after an apply, the target table and id. A rerun updates the row in place (``last_run_id``) and never duplicates it.
- ``migration_party_candidate``: legacy free-text customer names grouped by normalised name and country, with a
  suggested party for review. Nothing is merged automatically; a person links, creates or rejects.
- ``migration_legacy_record``: issued legacy documents (quotes with lines and revisions, custom products, challans,
  user attribution, settings) kept exactly as exported; ``payload`` and its hash are immutable (trigger).
- ``migration_opening_batch`` / ``_line``: opening stock from an authorised count, staged and approved separately;
  posting belongs to the inventory module (``app.modules.migration.opening.register_opening_poster``).
- ``migration_backup``: ``lk backup create`` and ``lk backup restore-rehearsal`` facts, one row per company in the
  backed-up database (a backup covers the whole database; RLS keeps each company's row to itself).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, TimestampMixin, VersionMixin


class RunKind(StrEnum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueSeverity(StrEnum):
    ERROR = "error"
    QUARANTINE = "quarantine"
    WARNING = "warning"
    INFO = "info"


class MapStatus(StrEnum):
    PLANNED = "planned"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    APPLIED = "applied"


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    LINKED = "linked"
    NEW_PARTY = "new_party"
    REJECTED = "rejected"


class OpeningStatus(StrEnum):
    STAGED = "staged"
    APPROVED = "approved"
    POSTED = "posted"
    REJECTED = "rejected"


class OpeningLineStatus(StrEnum):
    VALID = "valid"
    QUARANTINED = "quarantined"


class BackupStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class RehearsalOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class MigrationRun(TenantEntity, Base):
    __tablename__ = "migration_run"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RunStatus.RUNNING.value)
    #: the export directory's base name (never the full server path)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    #: the export's own manifest (``export_manifest.json``: authorised_by, exported_at, source_system) or {}
    export_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: [{"file", "entity", "format", "sha256", "bytes", "rows"}]
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: entity -> {"source_rows", "accepted", "quarantined", "rejected", "warnings"}
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: the apply's verified backup (``migration_backup.backup_id``)
    backup_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (Index("ix_migration_run_company_started", "company_id", "started_at"),)


class MigrationIssue(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "migration_issue"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="CASCADE"), nullable=False
    )
    entity: Mapped[str] = mapped_column(String(40), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: physical row (CSV/XLSX: the header is row 1; JSON: 1-based document index)
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: the original row exactly as exported (credentials removed)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_migration_issue_run", "run_id", "severity", "entity"),
        Index("ix_migration_issue_run_code", "run_id", "code"),
    )


class MigrationIdMap(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "migration_id_map"

    source_entity: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(400), nullable=False)
    business_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=MapStatus.PLANNED.value)
    #: sha256 of the canonical source row: a rerun sees "unchanged" or "changed"
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_table: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    first_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=False
    )
    last_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=False
    )
    applied_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("company_id", "source_entity", "source_key", name="uq_migration_id_map_source"),
        Index("ix_migration_id_map_business", "company_id", "source_entity", "business_key"),
    )


class PartyCandidate(TenantEntity, VersionMixin, Base):
    __tablename__ = "migration_party_candidate"

    #: normalised name (casefold, punctuation and legal-form noise removed) and the ISO country or ""
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)
    country_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    legacy_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legacy_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: every spelling seen, with counts: [{"name", "count"}]
    variants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: [{"entity", "source_key", "document_number"}] (first 50)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    suggested_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="SET NULL"), nullable=True
    )
    #: exact_name | name_tokens | none
    match_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CandidateStatus.PROPOSED.value)
    linked_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("parties_party.id", ondelete="RESTRICT"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name_key", "country_key", name="uq_migration_party_candidate_key"),
        Index("ix_migration_party_candidate_status", "company_id", "status"),
    )


class LegacyRecord(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "migration_legacy_record"

    source_entity: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(400), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: the exported document exactly (a quote carries its lines and revisions); immutable
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    legacy_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    recomputed_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    has_discrepancy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    party_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_party_candidate.id", ondelete="SET NULL"), nullable=True
    )
    applied_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "source_entity", "source_key", name="uq_migration_legacy_record_source"
        ),
        Index("ix_migration_legacy_record_number", "company_id", "source_entity", "document_number"),
    )


class OpeningBatch(TenantEntity, VersionMixin, Base):
    __tablename__ = "migration_opening_batch"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_run.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OpeningStatus.STAGED.value)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: uom -> total quantity (text decimals)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: the inventory posting reference once posted
    posting_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (Index("ix_migration_opening_batch_company", "company_id", "created_at"),)


class OpeningLine(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "migration_opening_line"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("migration_opening_batch.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_key: Mapped[str] = mapped_column(String(200), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("catalogue_product.id", ondelete="RESTRICT"), nullable=True
    )
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OpeningLineStatus.VALID.value)
    issue_code: Mapped[str | None] = mapped_column(String(60), nullable=True)

    __table_args__ = (Index("ix_migration_opening_line_batch", "batch_id", "status"),)


class BackupRecord(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "migration_backup"

    #: ``bk-YYYYMMDDTHHMMSSZ-xxxxxx`` (the backup directory name)
    backup_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    database: Mapped[str] = mapped_column(String(80), nullable=False)
    alembic_revision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dump_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dump_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    rehearsal_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rehearsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: [{"check", "passed", "detail"}]
    rehearsal_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    rehearsal_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("company_id", "backup_id", name="uq_migration_backup_backup_id"),
        Index("ix_migration_backup_company_started", "company_id", "started_at"),
    )


ENUMS: tuple[tuple[str, str, type[StrEnum]], ...] = (
    ("migration_run", "kind", RunKind),
    ("migration_run", "status", RunStatus),
    ("migration_issue", "severity", IssueSeverity),
    ("migration_id_map", "status", MapStatus),
    ("migration_party_candidate", "status", CandidateStatus),
    ("migration_opening_batch", "status", OpeningStatus),
    ("migration_opening_line", "status", OpeningLineStatus),
    ("migration_backup", "status", BackupStatus),
    ("migration_backup", "rehearsal_outcome", RehearsalOutcome),
)

__all__ = [
    "ENUMS",
    "BackupRecord",
    "BackupStatus",
    "CandidateStatus",
    "IssueSeverity",
    "LegacyRecord",
    "MapStatus",
    "MigrationIdMap",
    "MigrationIssue",
    "MigrationRun",
    "OpeningBatch",
    "OpeningLine",
    "OpeningLineStatus",
    "OpeningStatus",
    "PartyCandidate",
    "RehearsalOutcome",
    "RunKind",
    "RunStatus",
]
