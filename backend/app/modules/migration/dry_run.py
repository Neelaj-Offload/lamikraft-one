"""``lk migration dry-run``: read an export, analyse every legacy entity, persist the run, its quarantine, the
rerunnable ID map and the candidate party links, and build the reconciliation report. No domain data is written.

Rerunning over the same export changes nothing but ``last_run_id`` (``id_maps.unchanged`` = all, ``new`` = 0); a
corrected export shows the changed rows. A key already applied whose source row changed is quarantined
``SOURCE_CHANGED_SINCE_APPLY`` (the applied record is never overwritten silently).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.migration.analysis import QUARANTINE, Analysis, Finding, Options
from app.modules.migration.catalogue import analyse_catalogue
from app.modules.migration.documents import analyse_documents
from app.modules.migration.models import (
    CandidateStatus,
    MapStatus,
    MigrationIdMap,
    MigrationIssue,
    MigrationRun,
    PartyCandidate,
    RunKind,
    RunStatus,
)
from app.modules.migration.parties import analyse_parties
from app.modules.migration.sources import ENTITY_FILES, ExportSource, SourceError, read_export
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.uow import UnitOfWork

DRY_RUN = "migration.dry_run.run"
ORPHAN_CODES = {"ORPHAN_PRODUCT", "ORPHAN_LINE", "ORPHAN_REVISION"}


@dataclass
class RunResult:
    run_id: uuid.UUID
    status: str
    counts: dict[str, Any]
    report: dict[str, Any]
    issue_count: int
    quarantined: int
    errors: int
    analysis: Analysis | None = None


def _start(
    actor: ActorContext, kind: str, label: str, digest: str, options: Options, source: ExportSource | None
) -> uuid.UUID:
    with UnitOfWork(actor) as uow:
        uow.actor.require(DRY_RUN, Scope.COMPANY)
        run = uow.add(
            MigrationRun(
                kind=kind,
                status=RunStatus.RUNNING.value,
                source_label=label[:200],
                source_digest=digest,
                export_manifest=dict(source.manifest) if source else {},
                files=[f.describe() for f in source.files.values()] if source else [],
                options={
                    "fetch_media": options.fetch_media,
                    "default_price_type": options.default_price_type,
                    "default_currency": options.default_currency,
                    "date_order": options.date_order,
                },
                started_at=uow.now(),
                started_by_name=actor.display_name[:200],
            )
        )
        uow.flush()
        return run.id


def fail(actor: ActorContext, run_id: uuid.UUID, kind: str, code: str, detail: str) -> None:
    with UnitOfWork(actor) as uow:
        run = uow.session.get(MigrationRun, run_id)
        if run is None:
            return
        run.status = RunStatus.FAILED.value
        run.finished_at = uow.now()
        run.error_code = code[:60]
        run.error_detail = detail[:1000]
        uow.emit(
            "migration.run.failed",
            aggregate_id=run.id,
            payload={"run_id": str(run.id), "kind": kind, "error_code": code[:60]},
        )
        uow.audit(
            "migration.run.failed",
            resource_type="migration.run",
            resource_id=run.id,
            resource_label=run.source_label,
            outcome="failed",
            details={"error_code": code},
        )


def _issue_rows(uow: UnitOfWork, run_id: uuid.UUID, findings: list[Finding]) -> list[dict[str, Any]]:
    now = uow.now()
    return [
        {
            "id": uuid.uuid7(),
            "company_id": uow.actor.company_id,
            "run_id": run_id,
            "entity": f.entity,
            "source_file": f.file,
            "row_number": f.row_number,
            "source_key": f.source_key,
            "code": f.code,
            "severity": f.severity,
            "message": f.message,
            "field": f.field,
            "raw_value": f.raw_value,
            "raw": f.raw,
            "created_at": now,
            "updated_at": now,
        }
        for f in findings
    ]


def _persist_id_maps(uow: UnitOfWork, an: Analysis, run_id: uuid.UUID) -> dict[str, Any]:
    entities = sorted({p.entity for p in an.planned.values()} | set(an.source.files))
    existing = {
        (e, k): (h, s)
        for e, k, h, s in uow.session.execute(
            select(
                MigrationIdMap.source_entity,
                MigrationIdMap.source_key,
                MigrationIdMap.source_hash,
                MigrationIdMap.status,
            ).where(MigrationIdMap.source_entity.in_(entities))
        )
    }
    stats: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    now = uow.now()
    for (entity, key), p in sorted(an.planned.items()):
        prev = existing.get((entity, key))
        status = p.status
        if prev is None:
            stats["new"] += 1
        elif prev[0] != p.source_hash:
            stats["changed"] += 1
            if prev[1] == MapStatus.APPLIED.value:
                status = MapStatus.APPLIED.value
                an.findings.append(
                    Finding(
                        entity,
                        "SOURCE_CHANGED_SINCE_APPLY",
                        QUARANTINE,
                        "This record was applied from a different source row; the applied record "
                        "is kept and the change needs a person",
                        an.source.file_name(entity),
                        None,
                        key[:400],
                    )
                )
                an.counts[entity]["changed_since_apply"] += 1
        else:
            stats["unchanged"] += 1
        if prev is not None and prev[1] == MapStatus.APPLIED.value:
            status = MapStatus.APPLIED.value
        rows.append(
            {
                "id": uuid.uuid7(),
                "company_id": uow.actor.company_id,
                "source_entity": entity,
                "source_key": key,
                "business_key": (p.business_key or None) and p.business_key[:400],
                "status": status,
                "source_hash": p.source_hash,
                "first_run_id": run_id,
                "last_run_id": run_id,
                "created_at": now,
                "updated_at": now,
            }
        )
    planned_keys = set(an.planned)
    stats["missing_from_export"] = sum(
        1 for k in existing if k not in planned_keys and k[0] in an.source.files
    )
    for chunk in range(0, len(rows), 1000):
        batch = rows[chunk : chunk + 1000]
        stmt = pg_insert(MigrationIdMap).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_migration_id_map_source",
            set_={
                "business_key": stmt.excluded.business_key,
                "source_hash": stmt.excluded.source_hash,
                "status": stmt.excluded.status,
                "last_run_id": stmt.excluded.last_run_id,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        uow.session.execute(stmt)
    stats["total"] = len(rows)
    return dict(stats)


def _persist_candidates(uow: UnitOfWork, an: Analysis, run_id: uuid.UUID, found: dict[Any, Any]) -> None:
    current = {(c.name_key, c.country_key): c for c in uow.session.scalars(select(PartyCandidate))}
    for (nk, ck), (agg, suggestion) in sorted(found.items()):
        row = current.get((nk, ck))
        if row is None:
            row = uow.add(
                PartyCandidate(
                    name_key=nk,
                    country_key=ck,
                    legacy_name=agg.legacy_name[:200],
                    legacy_country=(agg.legacy_country or None) and agg.legacy_country[:80],
                    last_run_id=run_id,
                    status=CandidateStatus.PROPOSED.value,
                )
            )
        row.legacy_name = agg.legacy_name[:200]
        row.variants = [{"name": n, "count": c} for n, c in agg.variants.most_common()]
        row.occurrences = agg.occurrences
        row.sources = agg.sources
        row.last_run_id = run_id
        if row.status == CandidateStatus.PROPOSED.value:
            row.suggested_party_id = suggestion.party_id if suggestion else None
            row.match_kind = suggestion.match_kind if suggestion else "none"
            row.score = suggestion.score if suggestion else 0
    uow.flush()


def _count(an: Analysis, entity: str, code: str) -> int:
    return sum(1 for f in an.findings if f.entity == entity and f.code == code)


def build_report(an: Analysis, id_maps: dict[str, Any]) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    reconciled = True
    for entity in ENTITY_FILES:
        if entity not in an.source.files:
            continue
        c = an.counts[entity]
        row = {
            k: int(c.get(k, 0))
            for k in (
                "source_rows",
                "accepted",
                "quarantined",
                "rejected",
                "duplicate_identical",
                "with_warnings",
            )
        }
        row["file_rows"] = len(an.source.rows(entity))
        row["balanced"] = (
            row["file_rows"]
            == row["source_rows"]
            == (row["accepted"] + row["quarantined"] + row["rejected"] + row["duplicate_identical"])
        )
        reconciled = reconciled and row["balanced"]
        entities[entity] = row

    def link(entity: str, orphan_code: str | None = None, unresolved: str | None = None) -> dict[str, int]:
        out = {"linked": int(an.counts[entity].get("accepted", 0))}
        if orphan_code:
            out["orphans"] = _count(an, entity, orphan_code)
        if unresolved:
            out["unresolved"] = _count(an, entity, unresolved)
        return out

    links = {
        "products->taxonomy": {
            "linked": int(an.counts["products_master"].get("accepted", 0))
            - _count(an, "products_master", "TAXONOMY_UNKNOWN"),
            "unknown": _count(an, "products_master", "TAXONOMY_UNKNOWN"),
        },
        "pricing->products": link("pricing", "ORPHAN_PRODUCT"),
        "packaging->products": link("packaging", "ORPHAN_PRODUCT"),
        "specifications->products": link("specifications", "ORPHAN_PRODUCT"),
        "media->products": link("media", "ORPHAN_PRODUCT"),
        "quote_lines->quotes": link("quote_lines", "ORPHAN_LINE"),
        "quote_lines->products": {"unresolved": _count(an, "quote_lines", "LINE_PRODUCT_UNRESOLVED")},
        "quote_lines->custom_products": {"unresolved": _count(an, "quote_lines", "LINE_CUSTOM_UNRESOLVED")},
        "quote_revisions->quotes": link("quote_revisions", "ORPHAN_REVISION"),
        "custom_products->products": {"unresolved": _count(an, "custom_products", "BASE_PRODUCT_UNRESOLVED")},
        "challan_lines->challans": link("delivery_challan_lines", "ORPHAN_LINE"),
        "opening_balances->products": link("opening_balances", "ORPHAN_PRODUCT"),
    }
    links = {
        k: v
        for k, v in links.items()
        if any(v.values())
        or k.split("->")[0].replace("challan_lines", "delivery_challan_lines") in an.source.files
    }
    by_code: Counter[str] = Counter(f"{f.severity}:{f.code}" for f in an.findings)
    report: dict[str, Any] = {
        "source": {
            "label": an.source.label,
            "digest": an.source.digest,
            "authorised": an.source.authorised,
            "export_manifest": {
                k: an.source.manifest.get(k)
                for k in ("authorised_by", "exported_at", "source_system", "export_reference")
                if an.source.manifest.get(k) is not None
            },
            "files": [f.describe() for f in an.source.files.values()],
            "ignored_files": an.source.ignored,
        },
        "entities": entities,
        "reconciled": reconciled,
        "links": links,
        "id_maps": id_maps,
        "issues_by_code": dict(sorted(by_code.items())),
    }
    for key, value in an.report.items():
        if not key.startswith("_"):
            report[key] = value
    return report


def _digest_of_error(label: str) -> str:
    return hashlib.sha256(f"unreadable:{label}".encode()).hexdigest()


def run_dry_run(
    actor: ActorContext,
    root: Path,
    options: Options | None = None,
    *,
    kind: str = RunKind.DRY_RUN.value,
    keep_analysis: bool = False,
) -> RunResult:
    options = options or Options()
    root = Path(root)
    try:
        source = read_export(root)
    except SourceError as exc:
        run_id = _start(actor, kind, root.name or "export", _digest_of_error(root.name), options, None)
        fail(actor, run_id, kind, exc.code, exc.message)
        raise
    run_id = _start(actor, kind, source.label, source.digest, options, source)
    try:
        with UnitOfWork(actor) as uow:
            an = Analysis(source=source, uow=uow, options=options)
            for name, file in source.files.items():
                for row_no, column, code, message in file.notes:
                    an.findings.append(
                        Finding(name, code, "warning", message, file.name, row_no, None, column)
                    )
            if not source.authorised:
                an.findings.append(
                    Finding(
                        "export",
                        "EXPORT_NOT_AUTHORISED",
                        "warning",
                        "export_manifest.json does not name who authorised the export and when; "
                        "a dry run is allowed, an apply is refused",
                        None,
                    )
                )
            analyse_catalogue(an)
            analyse_documents(an)
            parties = analyse_parties(an)
            id_maps = _persist_id_maps(uow, an, run_id)
            _persist_candidates(uow, an, run_id, parties)
            report = build_report(an, id_maps)
            rows = _issue_rows(uow, run_id, an.findings)
            for chunk in range(0, len(rows), 1000):
                uow.session.execute(insert(MigrationIssue), rows[chunk : chunk + 1000])
            run = uow.session.get(MigrationRun, run_id)
            assert run is not None
            counts = {e: {k: int(v) for k, v in c.items()} for e, c in an.counts.items()}
            quarantined = sum(1 for f in an.findings if f.severity == QUARANTINE)
            errors = sum(1 for f in an.findings if f.severity == "error")
            run.status = RunStatus.COMPLETED.value
            run.finished_at = uow.now()
            run.counts = counts
            run.report = report
            run.issue_count = len(rows)
            run.quarantined_count = quarantined
            run.error_count = errors
            uow.emit(
                "migration.run.completed",
                aggregate_id=run.id,
                payload={
                    "run_id": str(run.id),
                    "kind": kind,
                    "source_digest": source.digest,
                    "quarantined": quarantined,
                    "errors": errors,
                },
            )
            uow.audit(
                "migration.run.completed",
                resource_type="migration.run",
                resource_id=run.id,
                resource_label=source.label,
                details={"kind": kind, "issues": len(rows), "quarantined": quarantined, "errors": errors},
            )
            result = RunResult(
                run.id,
                run.status,
                counts,
                report,
                len(rows),
                quarantined,
                errors,
                an if keep_analysis else None,
            )
        return result
    except Exception as exc:
        fail(actor, run_id, kind, type(exc).__name__, str(exc) or type(exc).__name__)
        raise


__all__ = ["DRY_RUN", "RunResult", "build_report", "fail", "run_dry_run"]
