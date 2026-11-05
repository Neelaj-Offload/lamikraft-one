"""Wire shapes of the migration API (read-only runs, quarantine, candidates, opening batches, backup facts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.http.capabilities import Capability


class MigrationRunSummary(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    source_label: str
    source_digest: str
    issue_count: int
    quarantined_count: int
    error_count: int
    started_at: datetime
    finished_at: datetime | None
    started_by_name: str
    backup_id: str | None
    error_code: str | None
    path: str


class MigrationRunDetail(MigrationRunSummary):
    export_manifest: dict[str, Any]
    files: list[dict[str, Any]]
    options: dict[str, Any]
    counts: dict[str, Any]
    #: the reconciliation report (counts, totals by currency, links, file hashes, id maps, ...)
    report: dict[str, Any]
    error_detail: str | None
    issues_csv_path: str


class MigrationIssueRead(BaseModel):
    id: uuid.UUID
    entity: str
    source_file: str | None
    row_number: int | None
    source_key: str | None
    code: str
    severity: str
    message: str
    field: str | None
    raw_value: str | None
    raw: dict[str, Any] | None


class IssueFacet(BaseModel):
    value: str
    count: int


class IssueFacets(BaseModel):
    severity: list[IssueFacet]
    entity: list[IssueFacet]
    code: list[IssueFacet]


class CandidatePartyRef(BaseModel):
    id: uuid.UUID
    party_number: str
    display_name: str
    country_code: str
    path: str


class CandidateRead(BaseModel):
    id: uuid.UUID
    legacy_name: str
    legacy_country: str | None
    name_key: str
    country_key: str
    variants: list[dict[str, Any]]
    occurrences: int
    sources: list[dict[str, Any]]
    match_kind: str
    score: Decimal
    status: str
    suggested_party: CandidatePartyRef | None
    linked_party: CandidatePartyRef | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    version: int
    capabilities: dict[str, Capability]


class CandidateDecision(StrEnum):
    LINK = "link"
    NEW_PARTY = "new_party"
    REJECT = "reject"
    REOPEN = "reopen"


class CandidateDecide(BaseModel):
    expected_version: int = Field(ge=1)
    decision: CandidateDecision
    #: required for ``link``: a party of the same company
    party_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class OpeningBatchRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    status: str
    source_digest: str
    line_count: int
    quarantined_count: int
    totals: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None
    approved_by_name: str | None
    posted_at: datetime | None
    posting_ref: str | None
    poster_available: bool


class RehearsalCheck(BaseModel):
    check: str
    passed: bool
    detail: str | None = None


class BackupRead(BaseModel):
    backup_id: str
    status: str
    database: str
    alembic_revision: str | None
    started_at: datetime
    finished_at: datetime | None
    dump_bytes: int | None
    dump_sha256: str | None
    storage_files: int | None
    storage_bytes: int | None
    storage_sha256: str | None
    manifest_sha256: str | None
    table_count: int | None
    row_total: int | None
    error_code: str | None
    rehearsal_outcome: str | None
    rehearsed_at: datetime | None
    rehearsal_seconds: Decimal | None
    rehearsal_checks: list[RehearsalCheck]


class BackupFacts(BaseModel):
    """Settings › Backups: the latest backup, the latest rehearsal and recent history (read-only; CLI-only actions)."""

    last_backup: BackupRead | None
    last_rehearsal: BackupRead | None
    history: list[BackupRead]
    max_age_hours_for_apply: int


__all__ = [
    "BackupFacts",
    "BackupRead",
    "CandidateDecide",
    "CandidateDecision",
    "CandidateRead",
    "IssueFacet",
    "IssueFacets",
    "MigrationIssueRead",
    "OpeningBatchRead",
    "CandidatePartyRef",
    "RehearsalCheck",
    "MigrationRunDetail",
    "MigrationRunSummary",
]
