"""Import workbench services (API entry points). Jobs are scoped by ``imports.job.read`` / ``.run`` (own: the jobs the
user started); rollback needs ``imports.rollback.execute``. Validation and commit run as ``platform/jobs`` jobs."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, insert, select

from app.core.csv_safe import write_csv
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.http.capabilities import Capability
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.imports import engine
from app.modules.imports.definitions import DEFINITIONS, definition
from app.modules.imports.headers import analyse_headers, suggest_mapping
from app.modules.imports.models import ImportChange, ImportJob, ImportType, RowIssue, RowStatus, StagedRow
from app.modules.imports.readers import read_file
from app.modules.imports.schemas import (
    ChangeRead,
    CommitRequest,
    DuplicateKey,
    FieldRead,
    HeaderRead,
    ImportOptions,
    ImportTypeRead,
    IssueRead,
    JobCreate,
    JobDetail,
    JobSummary,
    MappingUpdate,
    PreviewRead,
    RollbackItem,
    RollbackPlan,
    RollbackRequest,
    RowRead,
)
from app.platform.authz.permissions import Scope
from app.platform.service import query
from app.platform.uow import UnitOfWork

READ = "imports.job.read"
RUN = "imports.job.run"
ROLLBACK = "imports.rollback.execute"
VALIDATE_JOB = "imports.validate"
COMMIT_JOB = "imports.commit"
J = ImportJob


def job_path(job_id: uuid.UUID) -> str:
    return f"/settings/imports/{job_id}"


# ---- types ---------------------------------------------------------------------------------------------------------
@query(READ)
def list_types(uow: UnitOfWork) -> list[ImportTypeRead]:
    return [
        ImportTypeRead(
            import_type=d.import_type,  # type: ignore[arg-type]
            label=d.label,
            description=d.description,
            fields=[FieldRead(name=f.name, required=f.required, aliases=list(f.aliases)) for f in d.fields],
            depends_on=list(d.depends_on),  # type: ignore[arg-type]
            dependency_status=d.dependency_status(uow),
            template_path=f"/api/v1/imports/types/{d.import_type}/template.csv",
        )
        for d in DEFINITIONS.values()
    ]


@query(READ)
def template_csv(uow: UnitOfWork, import_type: ImportType) -> bytes:
    return write_csv([f.name for f in definition(import_type.value).fields], [])


# ---- jobs ----------------------------------------------------------------------------------------------------------
def _names(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from app.platform.identity.models import AppUser

    clean = {i for i in ids if i}
    if not clean:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(clean))).all())


def _summary_fields(job: ImportJob, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": job.id, "import_type": job.import_type, "status": job.status, "file_name": job.file_name,
        "file_sha256": job.file_sha256, "file_format": job.file_format, "row_count": job.row_count,
        "counts": dict(job.counts or {}), "progress": dict(job.progress or {}), "parent_job_id": job.parent_job_id,
        "created_at": job.created_at, "created_by_name": names.get(job.created_by) if job.created_by else None,
        "committed_at": job.committed_at, "rolled_back_at": job.rolled_back_at, "path": job_path(job.id),
    }


def _capabilities(uow: UnitOfWork, job: ImportJob) -> dict[str, Capability]:
    repo = uow.repo(ImportJob)
    can_run = repo.can(job, "run")
    busy = (job.progress or {}).get("state") in ("validating", "committing")

    def cap(ok_state: bool, state_reason: str, allowed: bool = can_run, deny: str = "permission_denied") -> Capability:
        if not allowed:
            return Capability(allowed=False, reason_code=deny)
        if busy:
            return Capability(allowed=False, reason_code="job_busy")
        return Capability(allowed=ok_state, reason_code=None if ok_state else state_reason)

    editable = job.status in ("parsed", "validated")
    can_rollback = uow.actor.can(ROLLBACK) and (
        (uow.actor.scope_for(ROLLBACK) or Scope.OWN) >= Scope.COMPANY or job.created_by == uow.actor.user_id
    )
    has_quarantine = int((job.counts or {}).get("quarantined", 0)) > 0
    return {
        "map": cap(editable, "job_not_editable"),
        "validate": cap(editable, "job_not_editable"),
        "commit": cap(job.status in ("validated", "commit_failed"), "not_validated"),
        "cancel": cap(job.status in ("parsed", "validated", "commit_failed"), "job_finished"),
        "recheck": cap(job.status in ("committed", "validated", "partially_rolled_back") and has_quarantine,
                       "nothing_quarantined"),
        "rollback": cap(job.status in ("committed", "partially_rolled_back"), "not_committed", can_rollback),
    }


def _detail(uow: UnitOfWork, job: ImportJob) -> JobDetail:
    return JobDetail(
        **_summary_fields(job, _names(uow, [job.created_by])),
        sheet_name=job.sheet_name,
        encoding=job.encoding,
        delimiter=job.delimiter,
        mapping=dict(job.mapping or {}),
        options=ImportOptions.model_validate(job.options or {}),
        error_code=job.error_code,
        error_detail=job.error_detail,
        source_file_id=job.file_id,
        source_url=f"/api/v1/files/{job.file_id}/content",
        report_url=f"/api/v1/imports/jobs/{job.id}/issues/report.csv",
        version=job.version,
        capabilities=_capabilities(uow, job),
    )


def _job(uow: UnitOfWork, job_id: uuid.UUID, action: str = "read", *, lock: bool = False) -> ImportJob:
    return uow.repo(ImportJob).get(job_id, action, for_update=lock)


def _stage_rows(uow: UnitOfWork, job: ImportJob, rows: Sequence[tuple[int, dict[str, Any]]]) -> None:
    now = uow.now()
    payload = [
        {
            "id": uuid.uuid7(), "company_id": job.company_id, "job_id": job.id, "row_number": n, "raw": raw,
            "raw_hash": engine.raw_hash(raw), "status": RowStatus.PENDING.value, "created_at": now, "updated_at": now,
        }
        for n, raw in rows
    ]
    for start in range(0, len(payload), 1000):
        uow.session.execute(insert(StagedRow), payload[start : start + 1000])


def create_job(uow: UnitOfWork, data: JobCreate) -> JobDetail:
    """Parse an uploaded CSV/XLSX into staged rows and suggest a column mapping (LM-35 preview follows)."""
    from app.platform.files import service as files
    from app.platform.files.storage import get_storage

    uow.actor.require(RUN)
    obj = files.get_readable(uow, data.file_id)
    if obj.kind not in ("csv", "xlsx", "txt"):
        raise ValidationFailed(
            "Imports read CSV or XLSX files",
            errors=[{"loc": ["body", "file_id"], "msg": "not a CSV or XLSX file", "code": "unsupported_file"}],
        )
    with get_storage().open(obj.storage_key) as fh:
        payload = fh.read()
    if hashlib.sha256(payload).hexdigest() != obj.sha256:  # re-verify the stored bytes
        raise Conflict("The stored file does not match its checksum", code="file_checksum_mismatch")
    sheet = read_file(payload, obj.original_name, sheet_name=data.sheet_name)
    defn = definition(data.import_type.value)
    infos, collisions = analyse_headers(sheet.headers)
    mapping = suggest_mapping(infos, defn.field_spellings(), collisions)
    job = ImportJob(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        import_type=data.import_type.value,
        status="parsed",
        file_id=obj.id,
        file_name=obj.original_name,
        file_sha256=obj.sha256,
        file_size=int(obj.size_bytes),
        file_format=sheet.file_format,
        sheet_name=sheet.sheet_name,
        encoding=sheet.encoding,
        delimiter=sheet.delimiter,
        headers=[{"index": i.index, "original": i.original, "normalised": i.normalised} for i in infos],
        mapping=mapping,
        options=ImportOptions().model_dump(),
        counts={},
        progress={"state": "idle"},
        row_count=len(sheet.rows),
    )
    uow.add(job)
    uow.flush()
    _stage_rows(uow, job, sheet.rows)
    notes = [
        engine.Issue(code, "warning" if code != "FORMULA_NO_VALUE" else "error", message, None, column)
        for _row, column, code, message in sheet.notes
    ]
    issue_rows = []
    for (row_number, column, _code, _message), issue in zip(sheet.notes, notes, strict=True):
        record = engine._issue_rows(job, None, [issue], "parse", {})[0]
        record.update(row_number=row_number, column_original=column)
        issue_rows.append(record)
    for normalised, originals in collisions.items():
        issue_rows += engine._issue_rows(
            job, None,
            [engine.Issue("HEADER_COLLISION", "warning", f"Headers {', '.join(originals)} all normalise to "
                          f"'{normalised}'; map them explicitly", None, ", ".join(originals))],
            "parse", {},
        )
    engine._insert_issues(uow, issue_rows)
    engine.recount(uow, job)
    uow.emit("imports.job.uploaded", aggregate_id=job.id, aggregate_version=job.version,
             payload={"job_id": str(job.id), "import_type": job.import_type})
    uow.audit("imports.job.uploaded", resource_type="imports.job", resource_id=job.id, resource_label=job.file_name,
              details={"sha256": job.file_sha256, "rows": job.row_count})
    return _detail(uow, job)


@query(READ)
def get_job(uow: UnitOfWork, job_id: uuid.UUID) -> JobDetail:
    return _detail(uow, _job(uow, job_id))


@query(READ)
def list_jobs(
    uow: UnitOfWork,
    *,
    import_type: ImportType | None = None,
    status: str | None = None,
    mine: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> Page[JobSummary]:
    """Durable history (UI-87), newest first; filters apply before paging."""
    conds = []
    if import_type:
        conds.append(J.import_type == import_type.value)
    if status:
        conds.append(J.status == status)
    if mine:
        conds.append(J.created_by == uow.actor.user_id)
    stmt = uow.repo(ImportJob).select().where(*conds)
    total = uow.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    jobs = list(uow.session.scalars(stmt.order_by(J.created_at.desc(), J.id.desc()).limit(limit).offset(max(0, offset))))
    names = _names(uow, [j.created_by for j in jobs])
    return Page[JobSummary](items=[JobSummary(**_summary_fields(j, names)) for j in jobs], total=int(total),
                            limit=limit, offset=max(0, offset))


@query(READ)
def preview(uow: UnitOfWork, job_id: uuid.UUID) -> PreviewRead:
    """First 20 rows, the header table (original -> normalised -> field), unmapped required fields, collisions,
    required columns that are blank in every row, natural keys repeated in the file (with row numbers) and earlier
    jobs of the same file (same sha256: a warning, not a block)."""
    job = _job(uow, job_id)
    defn = definition(job.import_type)
    rows = list(uow.session.scalars(select(StagedRow).where(StagedRow.job_id == job.id).order_by(StagedRow.row_number)))
    reverse = engine.reverse_mapping(job)
    required = [f.name for f in defn.fields if f.required]
    by_key: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        prepared = defn.normalise(engine.mapped_values(job, row.raw), job.options or {})
        if prepared.key:
            by_key.setdefault(prepared.key, []).append(
                (row.row_number, json.dumps(prepared.values, sort_keys=True, default=str))
            )
    duplicates = [
        DuplicateKey(key=k, row_numbers=[n for n, _ in v], identical=len({p for _, p in v}) == 1)
        for k, v in by_key.items()
        if len(v) > 1
    ]
    blank_required = [
        f for f in required if f in reverse and rows and all(not str(r.raw.get(reverse[f]) or "").strip() for r in rows)
    ]
    collisions: dict[str, list[str]] = {}
    for h in job.headers:
        collisions.setdefault(h["normalised"], []).append(h["original"])
    same = list(
        uow.session.scalars(
            uow.repo(ImportJob).select().where(J.file_sha256 == job.file_sha256, J.id != job.id).order_by(J.created_at)
        )
    )
    return PreviewRead(
        headers=[
            HeaderRead(index=h["index"], original=h["original"], normalised=h["normalised"],
                       field=(job.mapping or {}).get(h["original"]))
            for h in job.headers
        ],
        rows=[{"row_number": r.row_number, **r.raw} for r in rows[: engine.PREVIEW_ROWS]],
        total_rows=len(rows),
        unmapped_required=[f for f in required if f not in reverse],
        collisions={k: v for k, v in collisions.items() if len(v) > 1 and k},
        blank_required_columns=blank_required,
        duplicate_keys=sorted(duplicates, key=lambda d: d.row_numbers[0]),
        same_file_jobs=[j.id for j in same],
    )


def _require_state(job: ImportJob, allowed: Sequence[str], code: str = "job_not_editable") -> None:
    if job.status not in allowed:
        raise Conflict(f"The import is {job.status}", code=code)
    if (job.progress or {}).get("state") in ("validating", "committing"):
        raise Conflict("The import is busy", code="job_busy")


def set_mapping(uow: UnitOfWork, job_id: uuid.UUID, data: MappingUpdate) -> JobDetail:
    job = _job(uow, job_id, "run", lock=True)
    uow.expect_version(job, data.expected_version)
    _require_state(job, ("parsed", "validated"))
    defn = definition(job.import_type)
    known = {f.name for f in defn.fields}
    originals = {h["original"] for h in job.headers}
    errors = []
    used: dict[str, str] = {}
    for header, field in data.mapping.items():
        if header not in originals:
            errors.append({"loc": ["body", "mapping", header], "msg": "not a column of the file", "code": "unknown_column"})
        elif field is not None and field not in known:
            errors.append({"loc": ["body", "mapping", header], "msg": f"{field} is not a field", "code": "unknown_field"})
        elif field is not None and field in used:
            errors.append({"loc": ["body", "mapping", header], "msg": f"{field} is already mapped from {used[field]}",
                           "code": "field_mapped_twice"})
        elif field is not None:
            used[field] = header
    if errors:
        raise ValidationFailed("The mapping is not valid", errors=errors)
    job.mapping = {h["original"]: data.mapping.get(h["original"]) for h in job.headers}
    if data.options is not None:
        job.options = data.options.model_dump()
    job.status = "parsed"
    job.validation_digest = None
    uow.session.execute(
        StagedRow.__table__.update()
        .where(StagedRow.job_id == job.id, StagedRow.status != RowStatus.RELEASED.value)
        .values(status=RowStatus.PENDING.value, action=None, diff=None)
    )
    uow.session.execute(RowIssue.__table__.delete().where(RowIssue.job_id == job.id, RowIssue.phase == "validate"))
    job.updated_at = uow.now()
    uow.flush()
    engine.recount(uow, job)
    return _detail(uow, job)


def request_validation(uow: UnitOfWork, job_id: uuid.UUID, expected_version: int) -> JobDetail:
    job = _job(uow, job_id, "run", lock=True)
    uow.expect_version(job, expected_version)
    _require_state(job, ("parsed", "validated"))
    job.progress = {"state": "validating"}
    job.updated_at = uow.now()
    uow.flush()
    uow.enqueue(VALIDATE_JOB, {"job_id": str(job.id), "user_id": str(uow.actor.user_id)},
                dedupe_key=f"imports.validate:{job.id}:{job.version}", resource_type="imports.job", resource_id=job.id)
    return _detail(uow, job)


def request_commit(uow: UnitOfWork, job_id: uuid.UUID, data: CommitRequest) -> JobDetail:
    job = _job(uow, job_id, "run", lock=True)
    uow.expect_version(job, data.expected_version)
    _require_state(job, ("validated", "commit_failed"), "not_validated")
    excluded = sum(int((job.counts or {}).get(s, 0)) for s in ("rejected", "quarantined"))
    if excluded and not data.acknowledge_excluded:
        raise Conflict(f"{excluded} rows are rejected or quarantined and will not be imported; acknowledge to continue",
                       code="excluded_rows_not_acknowledged", excluded=excluded)
    busy = uow.session.scalar(
        select(func.count(J.id)).where(J.company_id == job.company_id, J.status == "committing", J.id != job.id)
    )
    if busy:
        raise Conflict("Another import is being committed; try again when it finishes", code="import_in_progress")
    job.status = "committing"
    job.progress = {"state": "committing", "done": 0}
    job.error_code = job.error_detail = None
    job.updated_at = uow.now()
    uow.flush()
    uow.enqueue(COMMIT_JOB, {"job_id": str(job.id), "user_id": str(uow.actor.user_id)},
                dedupe_key=f"imports.commit:{job.id}:{job.version}", resource_type="imports.job", resource_id=job.id)
    return _detail(uow, job)


def cancel_job(uow: UnitOfWork, job_id: uuid.UUID, expected_version: int) -> JobDetail:
    job = _job(uow, job_id, "run", lock=True)
    uow.expect_version(job, expected_version)
    _require_state(job, ("parsed", "validated", "commit_failed"), "job_finished")
    job.status = "cancelled"
    job.updated_at = uow.now()
    uow.flush()
    return _detail(uow, job)


def recheck_quarantine(uow: UnitOfWork, job_id: uuid.UUID) -> JobDetail:
    """A child job from the quarantined rows (same raw data, mapping and options), validated against current data;
    the parent's rows are marked ``released`` (e.g. pricing orphans after the products import, BUG-12)."""
    parent = _job(uow, job_id, "run", lock=True)
    rows = list(
        uow.session.scalars(
            select(StagedRow).where(StagedRow.job_id == parent.id, StagedRow.status == RowStatus.QUARANTINED.value)
            .order_by(StagedRow.row_number)
        )
    )
    if not rows:
        raise Conflict("No rows are quarantined", code="nothing_quarantined")
    child = ImportJob(
        id=uuid.uuid7(), company_id=parent.company_id, import_type=parent.import_type, status="parsed",
        file_id=parent.file_id, file_name=parent.file_name, file_sha256=parent.file_sha256,
        file_size=parent.file_size, file_format=parent.file_format, sheet_name=parent.sheet_name,
        encoding=parent.encoding, delimiter=parent.delimiter, headers=list(parent.headers),
        mapping=dict(parent.mapping), options=dict(parent.options), counts={}, progress={"state": "validating"},
        row_count=len(rows), parent_job_id=parent.id,
    )
    uow.add(child)
    uow.flush()
    _stage_rows(uow, child, [(r.row_number, r.raw) for r in rows])
    for r in rows:
        r.status = RowStatus.RELEASED.value
        r.released_to_job_id = child.id
    uow.flush()
    engine.recount(uow, parent)
    uow.enqueue(VALIDATE_JOB, {"job_id": str(child.id), "user_id": str(uow.actor.user_id)},
                dedupe_key=f"imports.validate:{child.id}:1", resource_type="imports.job", resource_id=child.id)
    return _detail(uow, child)


# ---- review --------------------------------------------------------------------------------------------------------
def _issue_conditions(job: ImportJob, severity: str | None, code: str | None, column: str | None) -> list[Any]:
    conds: list[Any] = [RowIssue.job_id == job.id]
    if severity:
        conds.append(RowIssue.severity == severity)
    if code:
        conds.append(RowIssue.code == code)
    if column:
        conds.append(RowIssue.column_original == column)
    return conds


@query(READ)
def list_issues(
    uow: UnitOfWork, job_id: uuid.UUID, *, severity: str | None = None, code: str | None = None,
    column: str | None = None, limit: int = 50, offset: int = 0,
) -> Page[IssueRead]:
    job = _job(uow, job_id)
    conds = _issue_conditions(job, severity, code, column)
    total = uow.session.scalar(select(func.count(RowIssue.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = uow.session.scalars(
        select(RowIssue).where(*conds).order_by(RowIssue.row_number.nulls_first(), RowIssue.id)
        .limit(limit).offset(max(0, offset))
    )
    return Page[IssueRead](
        items=[IssueRead(id=i.id, row_number=i.row_number, column=i.column_original, field=i.field, code=i.code,
                         severity=i.severity, message=i.message, raw_value=i.raw_value, phase=i.phase) for i in rows],
        total=int(total), limit=limit, offset=max(0, offset),
    )


REPORT_COLUMNS = ("row_number", "column", "field", "code", "severity", "message", "value")


@query(READ)
def issues_report_csv(uow: UnitOfWork, job_id: uuid.UUID) -> bytes:
    """Every issue (uncapped, LM-38) with its sheet row number; written through ``core.csv_safe``."""
    job = _job(uow, job_id)
    rows = uow.session.scalars(
        select(RowIssue).where(RowIssue.job_id == job.id).order_by(RowIssue.row_number.nulls_first(), RowIssue.id)
    )
    return write_csv(
        REPORT_COLUMNS,
        ([i.row_number, i.column_original, i.field, i.code, i.severity, i.message, i.raw_value] for i in rows),
    )


@query(READ)
def list_rows(
    uow: UnitOfWork, job_id: uuid.UUID, *, status: str | None = None, action: str | None = None,
    limit: int = 50, offset: int = 0,
) -> Page[RowRead]:
    """Before/after review: staged rows with their status, action and field diff."""
    job = _job(uow, job_id)
    conds: list[Any] = [StagedRow.job_id == job.id]
    if status:
        conds.append(StagedRow.status == status)
    if action:
        conds.append(StagedRow.action == action)
    total = uow.session.scalar(select(func.count(StagedRow.id)).where(*conds)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = list(uow.session.scalars(
        select(StagedRow).where(*conds).order_by(StagedRow.row_number).limit(limit).offset(max(0, offset))
    ))
    codes: dict[uuid.UUID, list[str]] = {}
    if rows:
        for staged_id, code in uow.session.execute(
            select(RowIssue.staged_row_id, RowIssue.code).where(RowIssue.staged_row_id.in_([r.id for r in rows]))
        ).all():
            codes.setdefault(staged_id, []).append(code)
    return Page[RowRead](
        items=[RowRead(id=r.id, row_number=r.row_number, status=r.status, action=r.action, natural_key=r.natural_key,
                       diff=r.diff, raw=r.raw, issue_codes=sorted(set(codes.get(r.id, [])))) for r in rows],
        total=int(total), limit=limit, offset=max(0, offset),
    )


@query(READ)
def list_changes(uow: UnitOfWork, job_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> Page[ChangeRead]:
    job = _job(uow, job_id)
    total = uow.session.scalar(select(func.count(ImportChange.id)).where(ImportChange.job_id == job.id)) or 0
    limit = max(1, min(limit, MAX_LIMIT))
    rows = uow.session.scalars(
        select(ImportChange).where(ImportChange.job_id == job.id).order_by(ImportChange.seq).limit(limit)
        .offset(max(0, offset))
    )
    return Page[ChangeRead](
        items=[ChangeRead(seq=c.seq, entity_table=c.entity_table, entity_id=c.entity_id, op=c.op,
                          changed_fields=list(c.changed_fields), before=c.before, after=c.after,
                          reverted_at=c.reverted_at) for c in rows],
        total=int(total), limit=limit, offset=max(0, offset),
    )


# ---- rollback ------------------------------------------------------------------------------------------------------
def _rollback_job(uow: UnitOfWork, job_id: uuid.UUID, *, lock: bool = False) -> ImportJob:
    job = _job(uow, job_id, lock=lock)
    uow.actor.require(ROLLBACK)
    scope = uow.actor.scope_for(ROLLBACK) or Scope.OWN
    if scope < Scope.COMPANY and job.created_by != uow.actor.user_id:
        raise Forbidden(code="permission_denied", permission=ROLLBACK)
    return job


def _plan(uow: UnitOfWork, job: ImportJob) -> RollbackPlan:
    items = engine.rollback_items(uow, job)
    return RollbackPlan(
        job_id=job.id,
        plan_hash=engine.plan_hash(items),
        reversible=sum(1 for i in items if i["status"] == "reversible"),
        blocked=sum(1 for i in items if i["status"] == "blocked"),
        already_removed=sum(1 for i in items if i["status"] == "already_removed"),
        items=[RollbackItem.model_validate(i) for i in items],
    )


def rollback_plan(uow: UnitOfWork, job_id: uuid.UUID) -> RollbackPlan:
    """What a rollback would do: reversible, already removed, or blocked (later edit, referenced, pricing history)."""
    job = _rollback_job(uow, job_id)
    if job.status not in ("committed", "partially_rolled_back"):
        raise Conflict("Only committed imports can be rolled back", code="not_committed")
    return _plan(uow, job)


def rollback(uow: UnitOfWork, job_id: uuid.UUID, data: RollbackRequest) -> JobDetail:
    """One transaction; the plan is recomputed and must match the reviewed hash (409 otherwise)."""
    from app.platform.identity.errors import ReauthRequired

    job = _rollback_job(uow, job_id, lock=True)
    recent = uow.actor.recent_auth_at
    if not uow.actor.is_system and (recent is None or uow.now() - recent > timedelta(minutes=10)):
        raise ReauthRequired()  # imports.rollback.execute requires a recent sign-in
    if job.status not in ("committed", "partially_rolled_back"):
        raise Conflict("Only committed imports can be rolled back", code="not_committed")
    plan = _plan(uow, job)
    if plan.plan_hash != data.plan_hash:
        raise Conflict("The rollback plan changed since it was reviewed", code="rollback_plan_changed")
    if data.mode == "all" and plan.blocked:
        raise Conflict(f"{plan.blocked} changes cannot be reversed; use reversible_only", code="rollback_blocked")
    changes = {
        c.seq: c for c in uow.session.scalars(select(ImportChange).where(ImportChange.job_id == job.id))
    }
    for item in plan.items:
        if item.status == "blocked":
            continue
        change = changes[item.seq]
        if item.status == "reversible":
            engine.revert_change(uow, change)
        engine.mark_reverted(uow, change)
    job.status = "partially_rolled_back" if plan.blocked else "rolled_back"
    job.rollback_mode = data.mode
    job.rolled_back_at, job.rolled_back_by = uow.now(), uow.actor.user_id
    job.updated_at = uow.now()
    uow.flush()
    uow.emit("imports.job.rolled_back", aggregate_id=job.id, aggregate_version=job.version,
             payload={"job_id": str(job.id), "import_type": job.import_type, "mode": data.mode})
    uow.audit("imports.job.rolled_back", resource_type="imports.job", resource_id=job.id, resource_label=job.file_name,
              details={"mode": data.mode, "reversed": plan.reversible, "blocked": plan.blocked})
    return _detail(uow, job)


def file_access(uow: UnitOfWork, obj: object) -> bool | None:
    """Import source files are readable by whoever may read a job that used them."""
    file_id = getattr(obj, "id", None)
    exists = uow.session.scalar(select(func.count(J.id)).where(J.company_id == uow.actor.company_id, J.file_id == file_id))
    if not exists:
        return None
    if not uow.actor.can(READ):
        return False
    return bool(uow.session.scalar(select(func.count()).select_from(
        uow.repo(ImportJob).select().where(J.file_id == file_id).subquery()
    )))

