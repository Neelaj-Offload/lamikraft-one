"""Running an import end to end the way the workbench does (upload -> job -> mapping -> validate -> commit)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.csv_safe import write_csv
from app.modules.imports import service
from app.modules.imports.schemas import CommitRequest, JobCreate, JobDetail, MappingUpdate
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, upload_file
from tests.support import drain


def csv_bytes(headers: list[str], rows: list[list[Any]]) -> bytes:
    """A plain CSV (not formula-guarded: imports must cope with raw spreadsheets)."""
    lines = [",".join(headers)] + [",".join("" if v is None else str(v) for v in r) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def admin(world: World) -> ActorContext:
    """Priya with a fresh sign-in (rollback and the demo reset need a recent authentication)."""
    from app.core.clock import get_clock

    return world.actor(keys.USERS.PRIYA).with_(recent_auth_at=get_clock().now() - timedelta(minutes=1))


def start(world: World, import_type: str, data: bytes, name: str = "import.csv", actor: ActorContext | None = None) -> JobDetail:
    actor = actor or admin(world)
    file_id = upload_file(actor, data, name, "import")
    with UnitOfWork(actor) as uow:
        return service.create_job(uow, JobCreate(import_type=import_type, file_id=file_id))  # type: ignore[arg-type]


def validate(world: World, job_id: uuid.UUID, actor: ActorContext | None = None) -> JobDetail:
    actor = actor or admin(world)
    job = service.get_job(actor, job_id)
    with UnitOfWork(actor) as uow:
        service.request_validation(uow, job_id, job.version)
    drain()
    return service.get_job(actor, job_id)


def remap(world: World, job_id: uuid.UUID, mapping: dict[str, str | None], **options: Any) -> JobDetail:
    actor = admin(world)
    job = service.get_job(actor, job_id)
    body = MappingUpdate(expected_version=job.version, mapping={**job.mapping, **mapping},
                         options=job.options.model_copy(update=options) if options else None)
    with UnitOfWork(actor) as uow:
        return service.set_mapping(uow, job_id, body)


def commit(world: World, job_id: uuid.UUID, *, acknowledge: bool = True, actor: ActorContext | None = None) -> JobDetail:
    actor = actor or admin(world)
    job = service.get_job(actor, job_id)
    with UnitOfWork(actor) as uow:
        service.request_commit(uow, job_id, CommitRequest(expected_version=job.version, acknowledge_excluded=acknowledge))
    drain()
    return service.get_job(actor, job_id)


def run(world: World, import_type: str, data: bytes, name: str = "import.csv") -> JobDetail:
    job = start(world, import_type, data, name)
    validate(world, job.id)
    return commit(world, job.id)


def issues(world: World, job_id: uuid.UUID, **filters: Any) -> list[Any]:
    return service.list_issues(admin(world), job_id, limit=500, **filters).items


def rows(world: World, job_id: uuid.UUID, **filters: Any) -> list[Any]:
    return service.list_rows(admin(world), job_id, limit=500, **filters).items


__all__ = ["write_csv"]
