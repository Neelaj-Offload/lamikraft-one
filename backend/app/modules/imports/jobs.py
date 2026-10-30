"""Background jobs of the import workbench (``platform/jobs``).

Both jobs run as the system actor only to locate the job, then rebuild the user who asked for the work
(``actor_for_member``): every write is permission-checked as that user. The commit runs each 500-row batch in its own
unit of work, so committed batches survive a failure; the job then ends ``commit_failed`` and can be resumed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.modules.imports import engine
from app.modules.imports.definitions import definition
from app.modules.imports.models import ImportJob
from app.platform.authz.actors import actor_for_member
from app.platform.jobs.defs import JobDef
from app.platform.uow import UnitOfWork

log = get_logger("lk.imports")


def _user_actor(company_id: uuid.UUID, payload: dict[str, Any]) -> Any:
    return actor_for_member(company_id, uuid.UUID(payload["user_id"]), channel="job")


def _company(ctx: Any, job_id: uuid.UUID) -> uuid.UUID:
    company = ctx.uow.session.scalar(select(ImportJob.company_id).where(ImportJob.id == job_id))
    if company is None:
        raise LookupError(f"import job {job_id} not found")
    return company


def run_validation(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.UUID(payload["job_id"])
    actor = _user_actor(_company(ctx, job_id), payload)
    try:
        with UnitOfWork(actor) as uow:
            job = uow.repo(ImportJob).get(job_id, "run", for_update=True)
            engine.validate_job(uow, job)
            uow.emit("imports.job.validated", aggregate_id=job.id, aggregate_version=job.version,
                     payload={"job_id": str(job.id), "import_type": job.import_type})
            return {"counts": dict(job.counts)}
    except Exception as exc:  # the job must not stay "validating": record the failure, never retry blindly
        log.warning("imports.validation_failed", job_id=str(job_id), error=type(exc).__name__)
        with UnitOfWork(actor) as uow:
            job = uow.repo(ImportJob).get(job_id, "run", for_update=True)
            job.progress = {"state": "idle"}
            job.error_code = getattr(exc, "code", None) or type(exc).__name__
            job.error_detail = str(exc)[:1000]
            job.updated_at = uow.now()
        return {"error": job.error_code}


def run_commit(ctx: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.UUID(payload["job_id"])
    actor = _user_actor(_company(ctx, job_id), payload)
    with UnitOfWork(actor) as uow:
        job = uow.repo(ImportJob).get(job_id, "run")
        row_ids = engine.committable_row_ids(uow, job, definition(job.import_type))
        total = len(row_ids)
    failure: Exception | None = None
    for start in range(0, total, engine.BATCH_SIZE):
        try:
            with UnitOfWork(actor) as uow:
                engine.commit_batch(uow, job_id, row_ids[start : start + engine.BATCH_SIZE])
        except Exception as exc:  # the batch rolled back; earlier batches stay committed
            failure = exc
            log.warning("imports.commit_batch_failed", job_id=str(job_id), batch_start=start, error=type(exc).__name__)
            break
    with UnitOfWork(actor) as uow:
        job = uow.repo(ImportJob).get(job_id, "run", for_update=True)
        engine.recount(uow, job)
        if failure is not None:
            job.status = "commit_failed"
            job.error_code = getattr(failure, "code", None) or type(failure).__name__
            job.error_detail = str(failure)[:1000]
            job.progress = {"state": "idle"}
            uow.emit("imports.job.failed", aggregate_id=job.id, aggregate_version=job.version,
                     payload={"job_id": str(job.id), "import_type": job.import_type, "error_code": job.error_code})
        else:
            job.status = "committed"
            job.committed_at, job.committed_by = uow.now(), actor.user_id
            job.progress = {"state": "idle", "done": total}
            uow.emit("imports.job.committed", aggregate_id=job.id, aggregate_version=job.version,
                     payload={"job_id": str(job.id), "import_type": job.import_type,
                              "has_quarantine": int(job.counts.get("quarantined", 0)) > 0})
            uow.audit("imports.job.committed", resource_type="imports.job", resource_id=job.id,
                      resource_label=job.file_name, details={"counts": dict(job.counts)})
        job.updated_at = uow.now()
        return {"status": job.status, "counts": dict(job.counts)}


JOBS = (
    JobDef("imports.validate", run_validation, queue="default", max_attempts=3, lease_seconds=900),
    JobDef("imports.commit", run_commit, queue="default", max_attempts=1, lease_seconds=1800),
)
