"""Migration API (``/api/v1/migration``) and backup facts (``/api/v1/system/backups``), read-only apart from the
candidate-party decision. Dry runs, the apply and backups run from the CLI (docs/runbooks/migration.md)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.migration import service
from app.modules.migration.models import CandidateStatus, IssueSeverity, RunKind
from app.modules.migration.schemas import (
    BackupFacts,
    CandidateDecide,
    CandidateRead,
    IssueFacets,
    IssueRead,
    OpeningBatchRead,
    RunDetail,
    RunSummary,
)
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/migration", tags=["migration"])
backups_router = APIRouter(prefix="/system/backups", tags=["system"])
READ = requires("migration.run.read")
DECIDE = requires("migration.party_candidate.update")
BACKUP_READ = requires("system.backup.read")
CSV = "text/csv; charset=utf-8"


@router.get("/runs", openapi_extra=READ)
def list_migration_runs(
    actor: Actor,
    kind: RunKind | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RunSummary]:
    """Dry runs and applies, newest first."""
    return service.list_runs(actor, kind=kind.value if kind else None, limit=limit, offset=offset)


@router.get("/runs/{run_id}", openapi_extra=READ)
def get_migration_run(actor: Actor, run_id: uuid.UUID) -> RunDetail:
    """One run with its reconciliation report (counts, totals by currency, links, file hashes, ID maps)."""
    return service.get_run(actor, run_id)


@router.get("/runs/{run_id}/issues", openapi_extra=READ)
def list_migration_issues(
    actor: Actor,
    run_id: uuid.UUID,
    severity: IssueSeverity | None = None,
    entity: Annotated[str | None, Query(max_length=40)] = None,
    code: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IssueRead]:
    """The quarantine browser: every issue with its row reference (file, row, source key) and original values."""
    return service.list_issues(actor, run_id, severity=severity.value if severity else None, entity=entity,
                               code=code, limit=limit, offset=offset)


@router.get("/runs/{run_id}/issue-facets", openapi_extra=READ)
def get_migration_issue_facets(actor: Actor, run_id: uuid.UUID) -> IssueFacets:
    return service.issue_facets(actor, run_id)


@router.get("/runs/{run_id}/issues.csv", openapi_extra=READ, response_class=Response,
            responses={200: {"content": {CSV: {"schema": {"type": "string"}}}}})
def get_migration_issues_csv(actor: Actor, run_id: uuid.UUID) -> Response:
    return Response(content=service.issues_csv(actor, run_id), media_type=CSV, headers={
        "Content-Disposition": f'attachment; filename="migration-{run_id}-issues.csv"',
        "Cache-Control": "private, no-store",
    })


@router.get("/party-candidates", openapi_extra=READ)
def list_party_candidates(
    actor: Actor,
    status: CandidateStatus | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CandidateRead]:
    """Legacy customer names with a suggested party, for review (never merged automatically)."""
    return service.list_candidates(actor, status=status.value if status else None, q=q, limit=limit, offset=offset)


@router.post("/party-candidates/{candidate_id}/decision", openapi_extra=DECIDE)
def decide_party_candidate(actor: Actor, candidate_id: uuid.UUID, body: CandidateDecide) -> CandidateRead:
    """Link the legacy name to a party of this company, mark it as a new party, reject it, or reopen it."""
    with UnitOfWork(actor) as uow:
        return service.decide_candidate(uow, candidate_id, body)


@router.get("/opening-balance-batches", openapi_extra=READ)
def list_opening_balance_batches(
    actor: Actor,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OpeningBatchRead]:
    return service.list_opening_batches(actor, limit=limit, offset=offset)


@backups_router.get("", openapi_extra=BACKUP_READ)
def get_backup_facts(actor: Actor) -> BackupFacts:
    """The last backup, the last restore rehearsal and recent history (backups themselves are CLI-only)."""
    return service.backup_facts(actor)
