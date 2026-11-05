"""Migration read services (runs, quarantine, opening batches, backup facts) and the candidate-party decision.

Runs and backups are company data behind ``migration.run.read`` / ``system.backup.read`` (company scope, MFA
step-up like the audit log). Candidate decisions need ``migration.party_candidate.update``; a link must name a party
of the same company (RLS makes another company's party invisible, so it is refused as not found).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from app.core.csv_safe import write_csv
from app.core.errors import NotFound, ValidationFailed, VersionConflict
from app.core.http.capabilities import Capability
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.migration.models import (
    BackupRecord,
    BackupStatus,
    CandidateStatus,
    MigrationIssue,
    MigrationRun,
    OpeningBatch,
    PartyCandidate,
)
from app.modules.migration.schemas import (
    BackupFacts,
    BackupRead,
    CandidateDecide,
    CandidateDecision,
    CandidatePartyRef,
    CandidateRead,
    IssueFacet,
    IssueFacets,
    MigrationIssueRead,
    MigrationRunDetail,
    MigrationRunSummary,
    OpeningBatchRead,
    RehearsalCheck,
)
from app.platform.authz.permissions import Scope
from app.platform.authz.stepup import require_step_up
from app.platform.service import command, query
from app.platform.uow import UnitOfWork

RUN_READ = "migration.run.read"
CANDIDATE_UPDATE = "migration.party_candidate.update"
BACKUP_READ = "system.backup.read"
APPLY_BACKUP_MAX_AGE_HOURS = 24


def run_path(run_id: uuid.UUID) -> str:
    return f"/settings/migration/runs/{run_id}"


def _summary(run: MigrationRun) -> dict[str, Any]:
    return {
        "id": run.id, "kind": run.kind, "status": run.status, "source_label": run.source_label,
        "source_digest": run.source_digest, "issue_count": run.issue_count, "quarantined_count": run.quarantined_count,
        "error_count": run.error_count, "started_at": run.started_at, "finished_at": run.finished_at,
        "started_by_name": run.started_by_name, "backup_id": run.backup_id, "error_code": run.error_code,
        "path": run_path(run.id),
    }


def _run(uow: UnitOfWork, run_id: uuid.UUID) -> MigrationRun:
    run = uow.session.get(MigrationRun, run_id)
    if run is None:
        raise NotFound(code="migration_run_not_found", resource_type="migration.run")
    return run


@query(RUN_READ, at_least=Scope.COMPANY)
def list_runs(uow: UnitOfWork, *, kind: str | None = None, limit: int = 25, offset: int = 0) -> Page[MigrationRunSummary]:
    require_step_up(uow, RUN_READ)
    stmt = select(MigrationRun)
    if kind:
        stmt = stmt.where(MigrationRun.kind == kind)
    total = uow.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = uow.session.scalars(stmt.order_by(MigrationRun.started_at.desc(), MigrationRun.id.desc())
                               .limit(min(limit, MAX_LIMIT)).offset(offset))
    return Page(items=[MigrationRunSummary(**_summary(r)) for r in rows], total=int(total), limit=limit, offset=offset)


@query(RUN_READ, at_least=Scope.COMPANY)
def get_run(uow: UnitOfWork, run_id: uuid.UUID) -> MigrationRunDetail:
    require_step_up(uow, RUN_READ)
    run = _run(uow, run_id)
    return MigrationRunDetail(
        **_summary(run), export_manifest=dict(run.export_manifest or {}), files=list(run.files or []),
        options=dict(run.options or {}), counts=dict(run.counts or {}), report=dict(run.report or {}),
        error_detail=run.error_detail, issues_csv_path=f"/api/v1/migration/runs/{run.id}/issues.csv",
    )


def _issue_filters(run_id: uuid.UUID, severity: str | None, entity: str | None, code: str | None) -> list[Any]:
    conds: list[Any] = [MigrationIssue.run_id == run_id]
    if severity:
        conds.append(MigrationIssue.severity == severity)
    if entity:
        conds.append(MigrationIssue.entity == entity)
    if code:
        conds.append(MigrationIssue.code == code)
    return conds


@query(RUN_READ, at_least=Scope.COMPANY)
def list_issues(uow: UnitOfWork, run_id: uuid.UUID, *, severity: str | None = None, entity: str | None = None,
                code: str | None = None, limit: int = 50, offset: int = 0) -> Page[MigrationIssueRead]:
    require_step_up(uow, RUN_READ)
    _run(uow, run_id)
    conds = _issue_filters(run_id, severity, entity, code)
    total = uow.session.scalar(select(func.count()).select_from(MigrationIssue).where(*conds)) or 0
    rows = uow.session.scalars(
        select(MigrationIssue).where(*conds)
        .order_by(MigrationIssue.entity, MigrationIssue.row_number.nulls_first(), MigrationIssue.code, MigrationIssue.id)
        .limit(min(limit, MAX_LIMIT)).offset(offset)
    )
    items = [MigrationIssueRead(id=i.id, entity=i.entity, source_file=i.source_file, row_number=i.row_number,
                       source_key=i.source_key, code=i.code, severity=i.severity, message=i.message, field=i.field,
                       raw_value=i.raw_value, raw=i.raw) for i in rows]
    return Page(items=items, total=int(total), limit=limit, offset=offset)


@query(RUN_READ, at_least=Scope.COMPANY)
def issue_facets(uow: UnitOfWork, run_id: uuid.UUID) -> IssueFacets:
    require_step_up(uow, RUN_READ)
    _run(uow, run_id)

    def facet(column: Any) -> list[IssueFacet]:
        rows = uow.session.execute(select(column, func.count()).where(MigrationIssue.run_id == run_id)
                                   .group_by(column).order_by(column))
        return [IssueFacet(value=str(v), count=int(n)) for v, n in rows]

    return IssueFacets(severity=facet(MigrationIssue.severity), entity=facet(MigrationIssue.entity),
                       code=facet(MigrationIssue.code))


@query(RUN_READ, at_least=Scope.COMPANY)
def issues_csv(uow: UnitOfWork, run_id: uuid.UUID) -> bytes:
    require_step_up(uow, RUN_READ)
    _run(uow, run_id)
    rows = uow.session.scalars(select(MigrationIssue).where(MigrationIssue.run_id == run_id)
                               .order_by(MigrationIssue.entity, MigrationIssue.row_number.nulls_first(),
                                         MigrationIssue.code))
    return write_csv(
        ["entity", "source_file", "row_number", "source_key", "severity", "code", "field", "raw_value", "message"],
        ([i.entity, i.source_file or "", i.row_number or "", i.source_key or "", i.severity, i.code, i.field or "",
          i.raw_value or "", i.message] for i in rows),
    )


# ---- candidates ----------------------------------------------------------------------------------------------------
def _party_refs(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, CandidatePartyRef]:
    from app.modules.parties.models import Party

    clean = {i for i in ids if i}
    if not clean:
        return {}
    rows = uow.session.execute(select(Party.id, Party.party_number, Party.display_name, Party.country_code)
                               .where(Party.id.in_(clean)))
    return {pid: CandidatePartyRef(id=pid, party_number=num, display_name=name, country_code=cc,
                          path=f"/sales/parties/{pid}") for pid, num, name, cc in rows}


def _names(uow: UnitOfWork, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    from app.platform.identity.models import AppUser

    clean = {i for i in ids if i}
    if not clean:
        return {}
    return dict(uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(clean))).all())


def _candidate(uow: UnitOfWork, c: PartyCandidate, parties: dict[uuid.UUID, CandidatePartyRef],
               names: dict[uuid.UUID, str]) -> CandidateRead:
    can = uow.actor.can(CANDIDATE_UPDATE, Scope.COMPANY)
    open_ = c.status == CandidateStatus.PROPOSED.value

    def cap(ok: bool, reason: str) -> Capability:
        if not can:
            return Capability(allowed=False, reason_code="permission_denied")
        return Capability(allowed=ok, reason_code=None if ok else reason)

    return CandidateRead(
        id=c.id, legacy_name=c.legacy_name, legacy_country=c.legacy_country, name_key=c.name_key,
        country_key=c.country_key, variants=list(c.variants or []), occurrences=c.occurrences,
        sources=list(c.sources or []), match_kind=c.match_kind, score=c.score, status=c.status,
        suggested_party=parties.get(c.suggested_party_id) if c.suggested_party_id else None,
        linked_party=parties.get(c.linked_party_id) if c.linked_party_id else None,
        decided_by_name=names.get(c.decided_by) if c.decided_by else None, decided_at=c.decided_at,
        decision_note=c.decision_note, version=c.version,
        capabilities={"decide": cap(open_, "already_decided"), "reopen": cap(not open_, "not_decided")},
    )


@query(RUN_READ, at_least=Scope.COMPANY)
def list_candidates(uow: UnitOfWork, *, status: str | None = None, q: str | None = None, limit: int = 50,
                    offset: int = 0) -> Page[CandidateRead]:
    require_step_up(uow, RUN_READ)
    stmt = select(PartyCandidate)
    if status:
        stmt = stmt.where(PartyCandidate.status == status)
    if q and q.strip():
        from app.core.text import LIKE_ESCAPE, contains_pattern

        stmt = stmt.where(PartyCandidate.legacy_name.ilike(contains_pattern(q.strip()), escape=LIKE_ESCAPE))
    total = uow.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(uow.session.scalars(stmt.order_by(PartyCandidate.occurrences.desc(), PartyCandidate.name_key)
                                    .limit(min(limit, MAX_LIMIT)).offset(offset)))
    parties = _party_refs(uow, [r.suggested_party_id for r in rows] + [r.linked_party_id for r in rows])
    names = _names(uow, [r.decided_by for r in rows])
    return Page(items=[_candidate(uow, r, parties, names) for r in rows], total=int(total), limit=limit,
                offset=offset)


@command(CANDIDATE_UPDATE, at_least=Scope.COMPANY)
def decide_candidate(uow: UnitOfWork, candidate_id: uuid.UUID, data: CandidateDecide) -> CandidateRead:
    from app.modules.parties.models import Party

    row = uow.session.get(PartyCandidate, candidate_id, with_for_update=True)
    if row is None:
        raise NotFound(code="party_candidate_not_found", resource_type="migration.party_candidate")
    if row.version != data.expected_version:
        raise VersionConflict(current_version=row.version)
    decision = data.decision
    if decision == CandidateDecision.REOPEN:
        if row.status == CandidateStatus.PROPOSED.value:
            raise ValidationFailed("The candidate is not decided", errors=[
                {"loc": ["body", "decision"], "msg": "nothing to reopen", "code": "not_decided"}])
        row.status, row.linked_party_id = CandidateStatus.PROPOSED.value, None
    else:
        if row.status != CandidateStatus.PROPOSED.value:
            raise ValidationFailed("The candidate is already decided; reopen it first", errors=[
                {"loc": ["body", "decision"], "msg": "already decided", "code": "already_decided"}])
        if decision == CandidateDecision.LINK:
            party = uow.session.get(Party, data.party_id) if data.party_id else None
            if party is None or party.archived_at is not None:
                raise ValidationFailed("Choose an active customer of this company", errors=[
                    {"loc": ["body", "party_id"], "msg": "party not found", "code": "party_not_found"}])
            row.status, row.linked_party_id = CandidateStatus.LINKED.value, party.id
        elif decision == CandidateDecision.NEW_PARTY:
            row.status, row.linked_party_id = CandidateStatus.NEW_PARTY.value, None
        else:
            row.status, row.linked_party_id = CandidateStatus.REJECTED.value, None
    row.decided_by = uow.actor.user_id
    row.decided_at = uow.now() if decision != CandidateDecision.REOPEN else None
    row.decision_note = data.note
    uow.flush()
    uow.audit(f"migration.party_candidate.{decision.value}", resource_type="migration.party_candidate",
              resource_id=row.id, resource_label=row.legacy_name,
              details={"status": row.status, "party_id": str(row.linked_party_id) if row.linked_party_id else None})
    parties = _party_refs(uow, [row.suggested_party_id, row.linked_party_id])
    return _candidate(uow, row, parties, _names(uow, [row.decided_by]))


# ---- opening balances --------------------------------------------------------------------------------------------------
@query(RUN_READ, at_least=Scope.COMPANY)
def list_opening_batches(uow: UnitOfWork, *, limit: int = 25, offset: int = 0) -> Page[OpeningBatchRead]:
    from app.modules.migration.opening import poster_available

    require_step_up(uow, RUN_READ)
    total = uow.session.scalar(select(func.count()).select_from(OpeningBatch)) or 0
    rows = list(uow.session.scalars(select(OpeningBatch).order_by(OpeningBatch.created_at.desc())
                                    .limit(min(limit, MAX_LIMIT)).offset(offset)))
    names = _names(uow, [r.approved_by for r in rows])
    available = poster_available()
    return Page(items=[OpeningBatchRead(
        id=b.id, run_id=b.run_id, status=b.status, source_digest=b.source_digest, line_count=b.line_count,
        quarantined_count=b.quarantined_count, totals=dict(b.totals or {}), created_at=b.created_at,
        approved_at=b.approved_at, approved_by_name=names.get(b.approved_by) if b.approved_by else None,
        posted_at=b.posted_at, posting_ref=b.posting_ref, poster_available=available,
    ) for b in rows], total=int(total), limit=limit, offset=offset)


# ---- backups -----------------------------------------------------------------------------------------------------------
def backup_read(b: BackupRecord) -> BackupRead:
    return BackupRead(
        backup_id=b.backup_id, status=b.status, database=b.database, alembic_revision=b.alembic_revision,
        started_at=b.started_at, finished_at=b.finished_at, dump_bytes=b.dump_bytes, dump_sha256=b.dump_sha256,
        storage_files=b.storage_files, storage_bytes=b.storage_bytes, storage_sha256=b.storage_sha256,
        manifest_sha256=b.manifest_sha256, table_count=b.table_count, row_total=b.row_total,
        error_code=b.error_code, rehearsal_outcome=b.rehearsal_outcome, rehearsed_at=b.rehearsed_at,
        rehearsal_seconds=b.rehearsal_seconds,
        rehearsal_checks=[RehearsalCheck.model_validate(c) for c in (b.rehearsal_checks or [])],
    )


@query(BACKUP_READ, at_least=Scope.COMPANY)
def backup_facts(uow: UnitOfWork, *, limit: int = 10) -> BackupFacts:
    require_step_up(uow, BACKUP_READ)
    history = list(uow.session.scalars(select(BackupRecord).order_by(BackupRecord.started_at.desc())
                                       .limit(min(limit, 50))))
    last_backup = uow.session.scalar(select(BackupRecord).where(BackupRecord.status == BackupStatus.COMPLETED.value)
                                     .order_by(BackupRecord.started_at.desc()).limit(1))
    last_rehearsal = uow.session.scalar(select(BackupRecord).where(BackupRecord.rehearsed_at.is_not(None))
                                        .order_by(BackupRecord.rehearsed_at.desc()).limit(1))
    return BackupFacts(
        last_backup=backup_read(last_backup) if last_backup else None,
        last_rehearsal=backup_read(last_rehearsal) if last_rehearsal else None,
        history=[backup_read(b) for b in history], max_age_hours_for_apply=APPLY_BACKUP_MAX_AGE_HOURS,
    )


__all__ = [
    "APPLY_BACKUP_MAX_AGE_HOURS",
    "backup_facts",
    "backup_read",
    "decide_candidate",
    "get_run",
    "issue_facets",
    "issues_csv",
    "list_candidates",
    "list_issues",
    "list_opening_batches",
    "list_runs",
    "run_path",
]
