"""Import workbench API (``/api/v1/imports``): types and templates, jobs (upload -> preview -> mapping -> validate ->
review -> commit -> recheck -> rollback), the issue report, history and the demo-only catalogue reset."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.imports import demo_reset, service
from app.modules.imports.models import ImportType
from app.modules.imports.schemas import (
    ChangeRead,
    CommitRequest,
    DemoResetPreview,
    DemoResetRequest,
    DemoResetResult,
    ImportTypeRead,
    IssueRead,
    JobCreate,
    JobDetail,
    JobSummary,
    MappingUpdate,
    PreviewRead,
    RollbackPlan,
    RollbackRequest,
    RowRead,
    VersionBody,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/imports", tags=["imports"])
READ = requires("imports.job.read")
RUN = requires("imports.job.run")
ROLLBACK = requires("imports.rollback.execute")
DEMO = requires("system.demo_data.delete")
CSV = "text/csv; charset=utf-8"
_CSV_RESPONSE = {200: {"content": {CSV: {"schema": {"type": "string"}}}}}


def _csv(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=CSV, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store",
    })


@router.get("/types", openapi_extra=READ)
def list_import_types(actor: Actor) -> list[ImportTypeRead]:
    """The seven types with fields, aliases, dependencies and their current status (import taxonomy first)."""
    return service.list_types(actor)


@router.get("/types/{import_type}/template.csv", openapi_extra=READ, response_class=Response, responses=_CSV_RESPONSE)
def get_import_template(actor: Actor, import_type: ImportType) -> Response:
    return _csv(service.template_csv(actor, import_type), f"{import_type.value}_template.csv")


@router.post("/jobs", status_code=201, openapi_extra=RUN)
def create_import_job(actor: Actor, body: JobCreate) -> JobDetail:
    """Parse a CSV/XLSX uploaded through ``POST /api/v1/files?purpose=import`` into staged rows."""
    with UnitOfWork(actor) as uow:
        return service.create_job(uow, body)


@router.get("/jobs", openapi_extra=READ)
def list_import_jobs(
    actor: Actor,
    import_type: ImportType | None = None,
    status: Annotated[str | None, Query(max_length=30)] = None,
    mine: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[JobSummary]:
    return service.list_jobs(actor, import_type=import_type, status=status, mine=mine, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", openapi_extra=READ)
def get_import_job(actor: Actor, job_id: uuid.UUID) -> JobDetail:
    return service.get_job(actor, job_id)


@router.get("/jobs/{job_id}/preview", openapi_extra=READ)
def get_import_preview(actor: Actor, job_id: uuid.UUID) -> PreviewRead:
    return service.preview(actor, job_id)


@router.put("/jobs/{job_id}/mapping", openapi_extra=RUN)
def update_import_mapping(actor: Actor, job_id: uuid.UUID, body: MappingUpdate) -> JobDetail:
    """Set the column mapping and options; any earlier validation is discarded."""
    with UnitOfWork(actor) as uow:
        return service.set_mapping(uow, job_id, body)


@router.post("/jobs/{job_id}/validate", status_code=202, openapi_extra=RUN)
def run_import_validation(actor: Actor, job_id: uuid.UUID, body: VersionBody) -> JobDetail:
    """Queue validation of every row; poll the job until ``progress.state`` is ``idle``."""
    with UnitOfWork(actor) as uow:
        return service.request_validation(uow, job_id, body.expected_version)


@router.get("/jobs/{job_id}/rows", openapi_extra=READ)
def list_import_rows(
    actor: Actor,
    job_id: uuid.UUID,
    status: Annotated[str | None, Query(max_length=30)] = None,
    action: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RowRead]:
    return service.list_rows(actor, job_id, status=status, action=action, limit=limit, offset=offset)


@router.get("/jobs/{job_id}/issues", openapi_extra=READ)
def list_import_issues(
    actor: Actor,
    job_id: uuid.UUID,
    severity: Annotated[str | None, Query(max_length=20)] = None,
    code: Annotated[str | None, Query(max_length=60)] = None,
    column: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IssueRead]:
    return service.list_issues(actor, job_id, severity=severity, code=code, column=column, limit=limit, offset=offset)


@router.get("/jobs/{job_id}/issues/report.csv", openapi_extra=READ, response_class=Response, responses=_CSV_RESPONSE)
def export_import_issues(actor: Actor, job_id: uuid.UUID) -> Response:
    """Every issue with its sheet row number, column, code and value (uncapped, formula-safe)."""
    return _csv(service.issues_report_csv(actor, job_id), f"import-{job_id}-report.csv")


@router.get("/jobs/{job_id}/changes", openapi_extra=READ)
def list_import_changes(
    actor: Actor,
    job_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ChangeRead]:
    return service.list_changes(actor, job_id, limit=limit, offset=offset)


@router.post("/jobs/{job_id}/commit", status_code=202, openapi_extra=RUN)
def run_import_commit(actor: Actor, job_id: uuid.UUID, body: CommitRequest) -> JobDetail:
    """Queue the commit (500-row transactional batches); also resumes a failed commit."""
    with UnitOfWork(actor) as uow:
        return service.request_commit(uow, job_id, body)


@router.post("/jobs/{job_id}/cancel", openapi_extra=RUN)
def update_import_cancel(actor: Actor, job_id: uuid.UUID, body: VersionBody) -> JobDetail:
    with UnitOfWork(actor) as uow:
        return service.cancel_job(uow, job_id, body.expected_version)


@router.post("/jobs/{job_id}/quarantine/recheck", status_code=201, openapi_extra=RUN)
def create_import_recheck(actor: Actor, job_id: uuid.UUID) -> JobDetail:
    """A child job from the quarantined rows, validated against current data (the parent rows are released)."""
    with UnitOfWork(actor) as uow:
        return service.recheck_quarantine(uow, job_id)


@router.get("/jobs/{job_id}/rollback-plan", openapi_extra=ROLLBACK)
def get_import_rollback_plan(actor: Actor, job_id: uuid.UUID) -> RollbackPlan:
    with UnitOfWork(actor) as uow:
        return service.rollback_plan(uow, job_id)


@router.post("/jobs/{job_id}/rollback", openapi_extra=ROLLBACK)
def run_import_rollback(actor: Actor, job_id: uuid.UUID, body: RollbackRequest) -> JobDetail:
    """Reverse the import in one transaction; later edits and referenced records are never undone."""
    with UnitOfWork(actor) as uow:
        return service.rollback(uow, job_id, body)


@router.get("/demo-reset/preview", openapi_extra=DEMO)
def get_demo_reset_preview(actor: Actor) -> DemoResetPreview:
    """Counts, blocking references, the confirmation phrase and a five-minute token (demo companies only)."""
    with UnitOfWork(actor) as uow:
        return demo_reset.preview(uow)


@router.post("/demo-reset", openapi_extra=DEMO)
def run_demo_reset(actor: Actor, body: DemoResetRequest) -> DemoResetResult:
    with UnitOfWork(actor) as uow:
        return demo_reset.execute(uow, body)
