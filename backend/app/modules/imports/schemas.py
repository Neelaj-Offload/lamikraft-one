"""Import workbench request and read models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.http.capabilities import Capability
from app.modules.imports.models import ImportType


class FieldRead(BaseModel):
    name: str
    required: bool
    aliases: list[str]


class ImportTypeRead(BaseModel):
    import_type: ImportType
    label: str
    description: str
    fields: list[FieldRead]
    depends_on: list[ImportType]
    #: live counts of what this type depends on (e.g. categories before products)
    dependency_status: dict[str, Any]
    template_path: str


class JobCreate(BaseModel):
    """Start an import from a file uploaded with ``POST /api/v1/files?purpose=import`` (CSV or XLSX)."""

    model_config = ConfigDict(extra="forbid")

    import_type: ImportType
    file_id: uuid.UUID
    sheet_name: str | None = Field(default=None, max_length=200)


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: blank cells keep the current value (``ignore``) or clear it (``clear``, products master text fields)
    blank_cells: Literal["ignore", "clear"] = "ignore"
    #: strip the "120.0" float artefact from decor identifiers (with a warning); never applied to product_key
    decor_float_artefact_rule: bool = True
    #: confirmed defaults for blank pricing columns (blank rows are quarantined without them)
    default_price_type: Literal["domestic", "export", "sample", "distributor"] | None = None
    default_currency: Literal["INR", "EUR", "USD", "GBP"] | None = None
    #: slash dates are read day-first unless set to MDY
    date_order: Literal["DMY", "MDY"] = "DMY"


class MappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    #: original header -> field name, or null to ignore the column (unmapped columns go to source_extra)
    mapping: dict[str, str | None]
    options: ImportOptions | None = None


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    #: required when rejected or quarantined rows will be left out
    acknowledge_excluded: bool = False


class HeaderRead(BaseModel):
    index: int
    original: str
    normalised: str
    field: str | None


class DuplicateKey(BaseModel):
    key: str
    row_numbers: list[int]
    identical: bool


class PreviewRead(BaseModel):
    headers: list[HeaderRead]
    rows: list[dict[str, Any]]
    total_rows: int
    unmapped_required: list[str]
    collisions: dict[str, list[str]]
    blank_required_columns: list[str]
    duplicate_keys: list[DuplicateKey]
    same_file_jobs: list[uuid.UUID]


class JobSummary(BaseModel):
    id: uuid.UUID
    import_type: ImportType
    status: str
    file_name: str
    file_sha256: str
    file_format: str
    row_count: int
    counts: dict[str, int]
    progress: dict[str, Any]
    parent_job_id: uuid.UUID | None
    created_at: datetime
    created_by_name: str | None
    committed_at: datetime | None
    rolled_back_at: datetime | None
    path: str


class JobDetail(JobSummary):
    sheet_name: str | None
    encoding: str | None
    delimiter: str | None
    mapping: dict[str, str | None]
    options: ImportOptions
    error_code: str | None
    error_detail: str | None
    source_file_id: uuid.UUID
    source_url: str
    report_url: str
    version: int
    capabilities: dict[str, Capability]


class IssueRead(BaseModel):
    id: uuid.UUID
    row_number: int | None
    column: str | None
    field: str | None
    code: str
    severity: str
    message: str
    raw_value: str | None
    phase: str


class RowRead(BaseModel):
    id: uuid.UUID
    row_number: int
    status: str
    action: str | None
    natural_key: str | None
    #: field -> [before, after]
    diff: dict[str, Any] | None
    raw: dict[str, Any]
    issue_codes: list[str]


class ChangeRead(BaseModel):
    seq: int
    entity_table: str
    entity_id: uuid.UUID
    op: str
    changed_fields: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reverted_at: datetime | None


class RollbackItem(BaseModel):
    seq: int
    entity_table: str
    entity_id: uuid.UUID
    op: str
    status: Literal["reversible", "already_removed", "blocked"]
    reason_code: str | None = None
    detail: str | None = None


class RollbackPlan(BaseModel):
    job_id: uuid.UUID
    plan_hash: str
    reversible: int
    blocked: int
    already_removed: int
    items: list[RollbackItem]


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "reversible_only"]
    plan_hash: str = Field(min_length=64, max_length=64)


class DemoResetPreview(BaseModel):
    company_name: str
    is_demo: bool
    counts: dict[str, int]
    blocking_references: dict[str, int]
    allowed: bool
    reason_code: str | None
    #: the phrase to type, and a token valid for five minutes
    phrase: str
    token: str | None
    expires_at: datetime | None


class DemoResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=500)
    phrase: str = Field(min_length=1, max_length=300)


class DemoResetResult(BaseModel):
    deleted: dict[str, int]
