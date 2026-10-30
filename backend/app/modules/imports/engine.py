"""Import engine: parse -> map -> validate -> review -> commit (500-row batches) -> recheck -> rollback.

- Parse stores every source row verbatim (``imports_staged_row.raw``) with its physical row number.
- Validate normalises every row, resolves in-file duplicate keys (identical -> ``duplicate_identical``, differing ->
  every occurrence quarantined ``DUPLICATE_KEY_CONFLICT``), resolves dependencies against committed data and diffs
  each row against the current entity. Every issue is kept (no cap) and feeds the downloadable report.
- Commit runs in batches of at most 500 rows, each batch one transaction that re-plans every row under the batch's
  locks: a changed dependency (``DEPENDENCY_CHANGED``), a target edited since review (``TARGET_CHANGED_SINCE_REVIEW``)
  or a key created meanwhile (``KEY_CREATED_CONCURRENTLY``) quarantines the row instead of overwriting work. Staged
  rows are marked inside the batch, so a failed commit resumes without duplicates. Unchanged rows write nothing.
- Rollback walks the change log backwards: an entity edited later (version moved) or referenced elsewhere blocks;
  ``all`` needs zero blocked items, ``reversible_only`` applies the safe subset; one transaction, guarded by a plan hash.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, insert, select, update

from app.core.errors import AppError, Conflict, ValidationFailed
from app.modules.imports.definitions import definition
from app.modules.imports.definitions.base import (
    ERROR,
    INFO,
    QUARANTINE,
    WARNING,
    Change,
    ImportDefinition,
    Issue,
    Prepared,
)
from app.modules.imports.models import ImportChange, ImportJob, RowIssue, RowStatus, StagedRow
from app.platform.uow import UnitOfWork

BATCH_SIZE = 500
PREVIEW_ROWS = 20


# ---- helpers ---------------------------------------------------------------------------------------------------------
def raw_hash(raw: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def mapped_values(job: ImportJob, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Field -> cell text through the job's mapping; unmapped non-blank cells -> ``__extra__`` (source_extra)."""
    values: dict[str, Any] = {}
    extra: dict[str, str] = {}
    cleared: list[str] = []
    for header, text in raw.items():
        field = (job.mapping or {}).get(header)
        if field:
            values[field] = text
            if job.options.get("blank_cells") == "clear" and not str(text or "").strip():
                cleared.append(field)
        elif str(text or "").strip():
            extra[header] = text
    values["__extra__"] = extra
    values["__cleared__"] = cleared
    return values


def _issue_rows(
    job: ImportJob, row: StagedRow | None, issues: Iterable[Issue], phase: str, reverse: Mapping[str, str]
) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid7(),
            "company_id": job.company_id,
            "job_id": job.id,
            "staged_row_id": row.id if row else None,
            "row_number": row.row_number if row else None,
            "column_original": reverse.get(i.field or "") if i.field else None,
            "field": i.field,
            "code": i.code,
            "severity": i.severity,
            "message": i.message[:1000],
            "raw_value": (str(i.raw_value)[:500] if i.raw_value is not None else None),
            "phase": phase,
        }
        for i in issues
    ]


def _insert_issues(uow: UnitOfWork, rows: list[dict[str, Any]]) -> None:
    if rows:
        now = uow.now()
        for r in rows:
            r.setdefault("created_at", now)
            r.setdefault("updated_at", now)
        uow.session.execute(insert(RowIssue), rows)


def _status_for(issues: Sequence[Issue]) -> str:
    severities = {i.severity for i in issues}
    if ERROR in severities:
        return RowStatus.REJECTED.value
    if QUARANTINE in severities:
        return RowStatus.QUARANTINED.value
    if WARNING in severities:
        return RowStatus.WARNING.value
    return RowStatus.VALID.value


def reverse_mapping(job: ImportJob) -> dict[str, str]:
    return {field: header for header, field in (job.mapping or {}).items() if field}


def recount(uow: UnitOfWork, job: ImportJob) -> dict[str, int]:
    rows = uow.session.execute(
        select(StagedRow.status, StagedRow.action, func.count()).where(StagedRow.job_id == job.id)
        .group_by(StagedRow.status, StagedRow.action)
    ).all()
    counts: dict[str, int] = {}
    for status, action, n in rows:
        counts[status] = counts.get(status, 0) + int(n)
        if action and status in ("valid", "warning"):
            counts[f"to_{action}"] = counts.get(f"to_{action}", 0) + int(n)
    severities = uow.session.execute(
        select(RowIssue.severity, func.count()).where(RowIssue.job_id == job.id).group_by(RowIssue.severity)
    ).all()
    for severity, n in severities:
        counts[f"issues_{severity}"] = int(n)
    job.counts = counts
    return counts


# ---- validation ------------------------------------------------------------------------------------------------------
def validate_job(uow: UnitOfWork, job: ImportJob) -> None:
    """Normalise, de-duplicate, resolve and diff every live staged row of the job (all issues kept)."""
    defn = definition(job.import_type)
    options = {**(job.options or {}), "job_id": str(job.id)}
    reverse = reverse_mapping(job)
    uow.session.execute(delete(RowIssue).where(RowIssue.job_id == job.id, RowIssue.phase == "validate"))
    rows = list(
        uow.session.scalars(
            select(StagedRow)
            .where(StagedRow.job_id == job.id, StagedRow.status != RowStatus.RELEASED.value)
            .order_by(StagedRow.row_number)
        )
    )
    missing = [f.name for f in defn.fields if f.required and f.name not in reverse]
    issue_rows: list[dict[str, Any]] = []
    if missing:
        issue_rows += _issue_rows(
            job, None, [Issue("REQUIRED_COLUMN_UNMAPPED", ERROR, f"No column is mapped to {', '.join(missing)}")],
            "validate", reverse,
        )
    prepared: dict[uuid.UUID, Prepared] = {}
    for row in rows:
        p = defn.normalise(mapped_values(job, row.raw), options)
        prepared[row.id] = p
    # in-file duplicate keys (rows with errors take no part)
    by_key: dict[str, list[StagedRow]] = {}
    for row in rows:
        p = prepared[row.id]
        if p.key and not any(i.severity == ERROR for i in p.issues):
            by_key.setdefault(p.key, []).append(row)
    duplicate_of: dict[uuid.UUID, str] = {}
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        payloads = {json.dumps(prepared[r.id].values, sort_keys=True, default=str) for r in group}
        numbers = ", ".join(str(r.row_number) for r in group)
        if len(payloads) == 1:
            for r in group[1:]:
                duplicate_of[r.id] = "identical"
                prepared[r.id].issues.append(
                    Issue("DUPLICATE_IDENTICAL", INFO, f"Same key and values as row {group[0].row_number}; skipped")
                )
        else:
            for r in group:
                duplicate_of[r.id] = "conflict"
                prepared[r.id].issues.append(
                    Issue("DUPLICATE_KEY_CONFLICT", QUARANTINE, f"Key '{key}' appears with different values in rows "
                          f"{numbers}", None, key)
                )
    ordered = sorted(rows, key=lambda r: (defn.order_key(prepared[r.id]), r.row_number))
    for row in ordered:
        p = prepared[row.id]
        row.normalized = p.values
        row.natural_key = (p.key or "")[:600] or None
        row.action, row.diff, row.target_id, row.target_version_seen = None, None, None, None
        issues = list(p.issues)
        if missing:
            row.status = RowStatus.REJECTED.value
        elif duplicate_of.get(row.id) == "identical":
            row.status = RowStatus.DUPLICATE_IDENTICAL.value
        elif any(i.severity == ERROR for i in issues) or duplicate_of.get(row.id) == "conflict":
            row.status = _status_for(issues)
        else:
            plan = defn.plan(uow, p, options)
            issues += plan.issues
            row.status = _status_for(issues)
            if row.status in (RowStatus.VALID.value, RowStatus.WARNING.value):
                row.action = plan.action
                row.diff = plan.diff or None
                row.target_id = plan.target_id
                row.target_version_seen = plan.target_version
        issue_rows += _issue_rows(job, row, issues, "validate", reverse)
    uow.flush()
    _insert_issues(uow, issue_rows)
    digest = hashlib.sha256(
        json.dumps(
            [(r.row_number, r.status, r.action, r.target_version_seen, r.raw_hash) for r in rows], default=str
        ).encode()
    ).hexdigest()
    job.validation_digest = digest
    job.validated_at = uow.now()
    job.status = "validated"
    job.error_code = job.error_detail = None
    job.progress = {"state": "idle"}
    recount(uow, job)


# ---- commit ----------------------------------------------------------------------------------------------------------
def committable_row_ids(uow: UnitOfWork, job: ImportJob, defn: ImportDefinition) -> list[uuid.UUID]:
    rows = uow.session.execute(
        select(StagedRow.id, StagedRow.row_number, StagedRow.normalized, StagedRow.natural_key).where(
            StagedRow.job_id == job.id,
            StagedRow.status.in_([RowStatus.VALID.value, RowStatus.WARNING.value]),
        )
    ).all()
    ordered = sorted(
        rows, key=lambda r: (defn.order_key(Prepared(values=r.normalized or {}, key=r.natural_key)), r.row_number)
    )
    return [r.id for r in ordered]


def commit_batch(uow: UnitOfWork, job_id: uuid.UUID, row_ids: Sequence[uuid.UUID]) -> None:
    """One transaction: re-plan every row under lock, write through the definition, log the changes."""
    job = uow.session.scalars(select(ImportJob).where(ImportJob.id == job_id).with_for_update()).one()
    defn = definition(job.import_type)
    options = {**(job.options or {}), "job_id": str(job.id)}
    reverse = reverse_mapping(job)
    seq = uow.session.scalar(select(func.coalesce(func.max(ImportChange.seq), 0)).where(ImportChange.job_id == job.id))
    rows = {
        r.id: r
        for r in uow.session.scalars(select(StagedRow).where(StagedRow.id.in_(list(row_ids))).with_for_update())
    }
    issue_rows: list[dict[str, Any]] = []
    for row_id in row_ids:
        row = rows[row_id]
        if row.status not in (RowStatus.VALID.value, RowStatus.WARNING.value):
            continue  # committed by an earlier attempt
        prepared = Prepared(values=row.normalized or {}, key=row.natural_key)
        plan = defn.plan(uow, prepared, options)
        blocker: Issue | None = None
        if any(i.severity in (ERROR, QUARANTINE) for i in plan.issues):
            first = next(i for i in plan.issues if i.severity in (ERROR, QUARANTINE))
            blocker = Issue("DEPENDENCY_CHANGED", QUARANTINE, f"Changed since review: {first.message}", first.field)
        elif row.action == "insert" and plan.action != "insert":
            blocker = Issue("KEY_CREATED_CONCURRENTLY", QUARANTINE, "The record was created since the review")
        elif row.action == "update" and plan.target_version != row.target_version_seen:
            blocker = Issue("TARGET_CHANGED_SINCE_REVIEW", QUARANTINE, "The record was edited since the review; "
                            "re-check the row to import it over the newer version")
        if blocker is not None:
            row.status = RowStatus.QUARANTINED.value
            issue_rows += _issue_rows(job, row, [blocker], "commit", reverse)
            continue
        if plan.action == "unchanged":
            row.status = RowStatus.UNCHANGED.value
            continue
        try:
            with uow.session.begin_nested():
                changes: list[Change] = defn.apply(uow, prepared, plan, options)
                uow.flush()
        except (ValidationFailed, Conflict) as exc:
            row.status = RowStatus.REJECTED.value
            detail = "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.extra.get("errors", [])
            ) or exc.detail
            issue_rows += _issue_rows(job, row, [Issue("APPLY_FAILED", ERROR, f"{exc.code}: {detail}"[:1000])], "commit",
                                      reverse)
            continue
        now = uow.now()
        for change in changes:
            seq += 1
            uow.session.execute(
                insert(ImportChange).values(
                    id=uuid.uuid7(), company_id=job.company_id, job_id=job.id, seq=seq, staged_row_id=row.id,
                    entity_table=change.entity_table, entity_id=change.entity_id, op=change.op,
                    before=_json(change.before), after=_json(change.after), changed_fields=change.changed_fields,
                    version_after=change.version_after, created_at=now, updated_at=now,
                )
            )
        row.status = RowStatus.COMMITTED.value
    uow.flush()
    _insert_issues(uow, issue_rows)
    done = int(job.progress.get("done", 0)) + len(row_ids)
    job.progress = {**job.progress, "state": "committing", "done": done}


def _json(value: Any) -> Any:
    from app.modules.imports.definitions.base import jsonable

    return jsonable(value) if value is not None else None


# ---- rollback --------------------------------------------------------------------------------------------------------
class _Blocked(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code, self.detail = code, detail


def _references(uow: UnitOfWork, table: str, entity_id: uuid.UUID) -> dict[str, int]:
    from app.modules.catalogue.taxonomy import reference_counts

    return {r.table: r.count for r in reference_counts(uow, table, entity_id)}


def _check(uow: UnitOfWork, change: ImportChange) -> Any:
    """The live entity for a reversible change; raises _Blocked, returns None when it is already gone."""
    from app.modules.catalogue.models import Category, LookupReference, Product, ProductMedia, Subcategory

    models = {
        "catalogue_product": Product,
        "catalogue_category": Category,
        "catalogue_subcategory": Subcategory,
        "catalogue_product_media": ProductMedia,
        "catalogue_lookup_reference": LookupReference,
    }
    model = models.get(change.entity_table)
    if model is None:
        raise _Blocked("NOT_REVERSIBLE", "Price-list changes are kept as pricing history; edit the price list instead")
    entity = uow.session.get(model, change.entity_id)
    if entity is None:
        return None
    version = getattr(entity, "version", None)
    if change.version_after is not None and version is not None and version != change.version_after:
        who = getattr(entity, "updated_by", None)
        raise _Blocked("LATER_EDIT", f"Edited after the import (version {version}, by {who or 'someone'})")
    if change.entity_table == "catalogue_lookup_reference" and change.after:
        current = {k: getattr(entity, k) for k in change.after}
        if current != change.after:
            raise _Blocked("LATER_EDIT", "Edited after the import")
    if change.op == "insert":
        refs = _references(uow, change.entity_table, change.entity_id)
        if refs:
            raise _Blocked("REFERENCED", ", ".join(f"{t}: {n}" for t, n in sorted(refs.items())))
    return entity


def rollback_items(uow: UnitOfWork, job: ImportJob) -> list[dict[str, Any]]:
    changes = list(
        uow.session.scalars(
            select(ImportChange)
            .where(ImportChange.job_id == job.id, ImportChange.reverted_at.is_(None))
            .order_by(ImportChange.seq.desc())
        )
    )
    items: list[dict[str, Any]] = []
    for change in changes:
        item = {"seq": change.seq, "entity_table": change.entity_table, "entity_id": str(change.entity_id),
                "op": change.op, "status": "reversible", "reason_code": None, "detail": None}
        try:
            if _check(uow, change) is None:
                item["status"] = "already_removed"
        except _Blocked as blocked:
            item.update(status="blocked", reason_code=blocked.code, detail=blocked.detail)
        items.append(item)
    return items


def plan_hash(items: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(list(items), sort_keys=True, default=str).encode()).hexdigest()


def revert_change(uow: UnitOfWork, change: ImportChange) -> None:
    from app.modules.catalogue import service as catalogue
    from app.modules.catalogue.models import ProductPackaging, ProductSpecification
    from app.modules.catalogue.schemas import PackagingIn, ProductUpdate, SpecificationIn

    entity = _check(uow, change)
    if entity is None:
        return
    if change.op == "insert":
        uow.session.delete(entity)
        uow.flush()
        return
    before = change.before or {}
    if change.entity_table == "catalogue_product":
        if "packaging" in before or "specification" in before:
            section = "packaging" if "packaging" in before else "specification"
            previous = before[section]
            if previous is None:
                model = ProductPackaging if section == "packaging" else ProductSpecification
                row = uow.session.get(model, entity.id)
                if row is not None:
                    uow.session.delete(row)
                entity.updated_at = uow.now()
                uow.flush()
                return
            body = {k: v for k, v in previous.items() if v is not None}
            section_in = PackagingIn.model_validate(body) if section == "packaging" else SpecificationIn.model_validate(body)
            catalogue.update_product(uow, entity.id, ProductUpdate(expected_version=entity.version, **{section: section_in}))
            return
        catalogue.update_product(
            uow, entity.id, ProductUpdate.model_validate({**before, "expected_version": entity.version})
        )
        return
    for name, value in before.items():
        setattr(entity, name, value)
    entity.updated_at = uow.now()
    uow.flush()


def mark_reverted(uow: UnitOfWork, change: ImportChange) -> None:
    uow.session.execute(update(ImportChange).where(ImportChange.id == change.id).values(reverted_at=uow.now()))


__all__ = [
    "BATCH_SIZE",
    "PREVIEW_ROWS",
    "AppError",
    "commit_batch",
    "committable_row_ids",
    "mapped_values",
    "plan_hash",
    "raw_hash",
    "recount",
    "revert_change",
    "rollback_items",
    "validate_job",
]
