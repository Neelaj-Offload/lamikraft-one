"""``lk migration apply``: the guarded write of a dry run's accepted rows (docs/runbooks/migration.md, cutover).

Refused unless all of these hold: ``--i-have-a-backup``; a named operator with ``migration.apply.execute``; a backup
of this database from the last ``max_backup_age_hours`` whose restore rehearsal passed (``lk backup create`` +
``lk backup restore-rehearsal``); an export whose ``export_manifest.json`` names who authorised it and when.

The apply re-analyses the export (its own run, ``kind = apply``, with the full quarantine) and writes:
- **catalogue** (taxonomy, products, pricing, packaging, specifications, lookups, reference media) through the import
  workbench: one import job per collection, validated and committed by the workbench itself, so its rules, its
  quarantine and its rollback apply unchanged (the job ids are in the run report);
- **media files** inside the export: stored through ``platform/files`` (sha256, deduplicated) and attached to the
  product; links that could not be read become reference media and stay in the inaccessible-link report;
- **legacy documents** (quotes with lines and revisions, custom products, challans with lines, users, quote settings,
  grain locks) into ``migration_legacy_record`` exactly as exported (immutable payload + sha256). Challans are
  documents only: nothing is posted to inventory. Users are invitation candidates (no account, no credential).
Opening balances are never part of an apply: they are a separate approved batch (``lk migration opening-balances``).

Every written key is marked ``applied`` in ``migration_id_map`` with its target; a rerun skips keys already applied
from the same source row, so applying twice writes nothing twice.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import uuid
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.imports.definitions import definition
from app.modules.migration.analysis import Accepted, Analysis, Options, text
from app.modules.migration.catalogue import IMPORT_TYPES, _mapping, _values
from app.modules.migration.documents import cents, money
from app.modules.migration.dry_run import RunResult, complete, fail, run_dry_run
from app.modules.migration.models import (
    BackupRecord,
    BackupStatus,
    LegacyRecord,
    MapStatus,
    MigrationIdMap,
    MigrationRun,
    PartyCandidate,
    RehearsalOutcome,
    RunKind,
)
from app.modules.migration.parties import country_code, normalise_name
from app.modules.migration.service import APPLY_BACKUP_MAX_AGE_HOURS
from app.modules.migration.sources import read_export, scrub
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.uow import UnitOfWork

APPLY = "migration.apply.execute"
CATALOGUE_ORDER = ("category_taxonomy", "products_master", "pricing", "packaging", "specifications",
                   "lookup_reference", "media")
LEGACY_ENTITIES = ("users", "quote_settings", "custom_products", "quotes", "grain_locked_decors", "delivery_challans")


class ApplyRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_verified_backup(actor: ActorContext, backup_id: str | None, max_age_hours: int) -> BackupRecord:
    with UnitOfWork(actor) as uow:
        stmt = select(BackupRecord).where(
            BackupRecord.status == BackupStatus.COMPLETED.value,
            BackupRecord.rehearsal_outcome == RehearsalOutcome.PASSED.value,
            BackupRecord.database == get_settings().db_name,
            BackupRecord.started_at >= uow.now() - timedelta(hours=max_age_hours),
        )
        if backup_id:
            stmt = stmt.where(BackupRecord.backup_id == backup_id)
        row = uow.session.scalar(stmt.order_by(BackupRecord.started_at.desc()).limit(1))
        if row is None:
            raise ApplyRefused("no_verified_backup", (
                f"no backup {backup_id + ' ' if backup_id else ''}of {get_settings().db_name} from the last "
                f"{max_age_hours} h with a passed restore rehearsal; run lk backup create and "
                "lk backup restore-rehearsal first"))
        uow.session.expunge(row)
        return row


def _applied(actor: ActorContext) -> dict[tuple[str, str], tuple[str, uuid.UUID | None]]:
    with UnitOfWork(actor) as uow:
        return {(e, k): (h, t) for e, k, h, t in uow.session.execute(
            select(MigrationIdMap.source_entity, MigrationIdMap.source_key, MigrationIdMap.source_hash,
                   MigrationIdMap.target_id).where(MigrationIdMap.status == MapStatus.APPLIED.value,
                                                   MigrationIdMap.applied_run_id.is_not(None)))}


def _pending(an: Analysis, entity: str, applied: dict[tuple[str, str], tuple[str, Any]]) -> tuple[list[Accepted], int]:
    planned = {k: p.source_hash for (e, k), p in an.planned.items() if e == entity}
    todo, skipped = [], 0
    for key, acc in an.accepted[entity].items():
        prev = applied.get((entity, key))
        if prev is not None and prev[0] == planned.get(key):
            skipped += 1
        else:
            todo.append(acc)
    return todo, skipped


def _mark(actor: ActorContext, run_id: uuid.UUID, entity: str, targets: dict[str, uuid.UUID], table: str) -> None:
    if not targets:
        return
    with UnitOfWork(actor) as uow:
        for key, target in targets.items():
            uow.session.execute(update(MigrationIdMap).where(
                MigrationIdMap.source_entity == entity, MigrationIdMap.source_key == key,
            ).values(status=MapStatus.APPLIED.value, target_table=table, target_id=target, applied_run_id=run_id,
                     updated_at=uow.now()))


# ---- catalogue through the import workbench --------------------------------------------------------------------------
def _upload(actor: ActorContext, data: bytes, name: str, purpose: str) -> uuid.UUID:
    from app.platform.files import service as files
    from app.platform.files.upload import ReceivedUpload

    tmp = Path(tempfile.mkstemp(suffix=".part")[1])
    tmp.write_bytes(data)
    received = ReceivedUpload(path=tmp, size=len(data), sha256=hashlib.sha256(data).hexdigest(), filename=name,
                              declared_content_type=None, head=data[:4096])
    try:
        return files.create_from_upload(actor, received, purpose=purpose).id
    finally:
        received.discard()


def _csv(an: Analysis, entity: str, rows: list[Accepted]) -> bytes:
    import_type = IMPORT_TYPES[entity]
    mapping = _mapping(an, entity, an.source.rows(entity), import_type)
    fields = [f.name for f in definition(import_type).fields]
    records: list[dict[str, str]] = []
    extras: list[str] = []
    for acc in rows:
        values = _values(acc.row, mapping)
        record = {k: (v or "") for k, v in values.items() if k in fields}
        for k, v in (values.get("__extra__") or {}).items():
            if k not in extras:
                extras.append(k)
            record[k] = v
        records.append(record)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields + extras, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return buffer.getvalue().encode("utf-8")


def _import_job(actor: ActorContext, an: Analysis, entity: str, rows: list[Accepted], options: Options) -> dict[str, Any]:
    from app.modules.imports import service as imports
    from app.modules.imports.models import ImportChange, StagedRow
    from app.modules.imports.schemas import CommitRequest, ImportOptions, JobCreate, MappingUpdate
    from app.platform.jobs.worker import drain

    import_type = IMPORT_TYPES[entity]
    file_id = _upload(actor, _csv(an, entity, rows), f"migration-{entity}.csv", "import")
    with UnitOfWork(actor) as uow:
        job = imports.create_job(uow, JobCreate(import_type=import_type, file_id=file_id))  # type: ignore[arg-type]
    if options.default_currency or options.default_price_type or options.date_order != "DMY":
        with UnitOfWork(actor) as uow:
            job = imports.set_mapping(uow, job.id, MappingUpdate(
                expected_version=job.version, mapping=dict(job.mapping),
                options=ImportOptions(default_currency=options.default_currency,  # type: ignore[arg-type]
                                      default_price_type=options.default_price_type,  # type: ignore[arg-type]
                                      date_order=options.date_order)))  # type: ignore[arg-type]
    with UnitOfWork(actor) as uow:
        imports.request_validation(uow, job.id, job.version)
    drain()
    job = imports.get_job(actor, job.id)
    if job.status == "validated":
        with UnitOfWork(actor) as uow:
            imports.request_commit(uow, job.id, CommitRequest(expected_version=job.version, acknowledge_excluded=True))
        drain()
        job = imports.get_job(actor, job.id)
    with UnitOfWork(actor) as uow:
        # unchanged rows carry their target from the plan; inserted ones are found through the change log
        targets: dict[str, uuid.UUID] = {}
        for key, target, change_target in uow.session.execute(
            select(StagedRow.natural_key, StagedRow.target_id, ImportChange.entity_id)
            .outerjoin(ImportChange, ImportChange.staged_row_id == StagedRow.id)
            .where(StagedRow.job_id == job.id, StagedRow.status.in_(("committed", "unchanged")))
            .order_by(StagedRow.row_number, ImportChange.seq)
        ):
            if key and key not in targets and (target or change_target):
                targets[key] = target or change_target
    return {"job_id": str(job.id), "job_status": job.status, "rows": len(rows), "counts": dict(job.counts),
            "path": job.path, "_targets": targets}


def _attach_media_file(actor: ActorContext, an: Analysis, acc: Accepted) -> uuid.UUID | None:
    from app.core.errors import Conflict
    from app.modules.catalogue.media import MediaAttach, attach_media
    from app.modules.catalogue.models import Product, ProductMedia

    v = acc.values
    info = v.get("file") or {}
    path = an.source.root.resolve() / info["path"]
    purpose = "image" if v.get("media_type") in ("image", "packaging_photo") else "document"
    file_id = _upload(actor, path.read_bytes(), str(v.get("file_name") or path.name)[:200], purpose)
    with UnitOfWork(actor) as uow:
        product_id = uow.session.scalar(select(Product.id).where(Product.product_key == v.get("product_key")))
        if product_id is None:
            return None
        try:
            media = attach_media(uow, product_id, MediaAttach(file_id=file_id, media_type=v["media_type"],
                                                              alt_text=v.get("alt_text"),
                                                              source_catalog_page=v.get("source_catalog_page")))
            return media.id
        except Conflict:  # the same bytes are already on the product (an earlier apply or an upload)
            return uow.session.scalar(select(ProductMedia.id).where(ProductMedia.product_id == product_id,
                                                                    ProductMedia.file_id == file_id))


def _apply_catalogue(actor: ActorContext, an: Analysis, run_id: uuid.UUID, options: Options,
                     applied: dict[tuple[str, str], tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entity in CATALOGUE_ORDER:
        if entity not in an.source.files:
            continue
        rows, skipped = _pending(an, entity, applied)
        entry: dict[str, Any] = {"skipped_already_applied": skipped}
        if entity == "media":
            stored = [a for a in rows if (a.values.get("file") or {}).get("path")]
            rows = [a for a in rows if not (a.values.get("file") or {}).get("path")]
            targets: dict[str, uuid.UUID] = {}
            missing_product = 0
            for acc in stored:
                media_id = _attach_media_file(actor, an, acc)
                if media_id is None:
                    missing_product += 1
                else:
                    targets[acc.key] = media_id
            _mark(actor, run_id, entity, targets, "catalogue_product_media")
            entry.update({"files_stored": len(targets), "files_without_product": missing_product})
        if rows:
            job = _import_job(actor, an, entity, rows, options)
            targets = job.pop("_targets")
            _mark(actor, run_id, entity, {k: t for k, t in targets.items() if k}, definition(IMPORT_TYPES[entity]).writes[0])
            entry.update(job)
        out[entity] = entry
    return out


# ---- legacy documents ------------------------------------------------------------------------------------------------
def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _sort(rows: list[Accepted], field: str) -> list[Accepted]:
    def key(a: Accepted) -> tuple[int, str]:
        raw = text(a.row.values, field) or ""
        return (int(raw) if raw.isdigit() else 0, a.key)

    return sorted(rows, key=key)


def _legacy_records(an: Analysis) -> list[dict[str, Any]]:
    """(entity, key, document number, payload, money facts, member keys) for every accepted legacy document."""
    users = {c["source_key"]: c for c in (an.report.get("users") or {}).get("candidates", [])}
    lines_by_quote: dict[str, list[Accepted]] = defaultdict(list)
    for acc in an.accepted["quote_lines"].values():
        lines_by_quote[text(acc.row.values, "quote_id") or ""].append(acc)
    revisions_by_quote: dict[str, list[Accepted]] = defaultdict(list)
    for acc in an.accepted["quote_revisions"].values():
        revisions_by_quote[text(acc.row.values, "quote_id") or ""].append(acc)
    lines_by_challan: dict[str, list[Accepted]] = defaultdict(list)
    for acc in an.accepted["delivery_challan_lines"].values():
        lines_by_challan[text(acc.row.values, "challan_id") or ""].append(acc)
    out: list[dict[str, Any]] = []
    for entity in LEGACY_ENTITIES:
        for key, acc in sorted(an.accepted[entity].items()):
            v = scrub(acc.row.values)
            record: dict[str, Any] = {"entity": entity, "key": key, "number": None, "members": {},
                                      "currency": None, "legacy_total": None, "recomputed": None, "customer": None}
            if entity == "quotes":
                lines = _sort(lines_by_quote.get(key, []), "line_number")
                revs = _sort(revisions_by_quote.get(key, []), "version")
                record["payload"] = {"quote": v, "lines": [scrub(a.row.values) for a in lines],
                                     "revisions": [scrub(a.row.values) for a in revs]}
                record["number"] = text(v, "quote_number")
                record["currency"] = (text(v, "currency") or "").upper() or None
                record["legacy_total"] = money(v, "total_amount", [])
                recomputed = acc.values.get("_recomputed_total")
                record["recomputed"] = money({"x": recomputed}, "x", []) if recomputed is not None else None
                record["members"] = {"quote_lines": [a.key for a in lines], "quote_revisions": [a.key for a in revs]}
                record["customer"] = (text(v, "customer_name"), text(v, "customer_country"))
            elif entity == "delivery_challans":
                lines = _sort(lines_by_challan.get(key, []), "sort_order")
                record["payload"] = {"challan": v, "lines": [scrub(a.row.values) for a in lines],
                                     "inventory_effect": "none"}
                record["number"] = text(v, "challan_number")
                record["members"] = {"delivery_challan_lines": [a.key for a in lines]}
            elif entity == "users":
                plan = users.get(key, {})
                record["payload"] = {"user": v, "planned_access": {k: plan.get(k) for k in (
                    "kind", "role_template", "grant", "revoke")}}
                record["number"] = plan.get("email")
            elif entity == "custom_products":
                record["payload"] = {"custom_product": v}
                record["number"] = text(v, "custom_code")
                record["customer"] = (text(v, "customer_name"), None)
            else:
                record["payload"] = {entity: v}
                record["number"] = text(v, "decor", "decor_no") if entity == "grain_locked_decors" else None
            out.append(record)
    return out


def _apply_legacy(actor: ActorContext, an: Analysis, run_id: uuid.UUID,
                  applied: dict[tuple[str, str], tuple[str, Any]]) -> dict[str, Any]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"new": 0, "unchanged": 0, "kept_original": 0})
    targets: dict[str, dict[str, uuid.UUID]] = defaultdict(dict)
    with UnitOfWork(actor) as uow:
        uow.actor.require(APPLY, Scope.COMPANY)
        candidates = {(c.name_key, c.country_key): c.id for c in uow.session.scalars(select(PartyCandidate))}
        existing = {(r.source_entity, r.source_key): r for r in uow.session.scalars(select(LegacyRecord))}
        for rec in _legacy_records(an):
            entity, key = rec["entity"], rec["key"]
            payload = rec["payload"]
            digest = _payload_hash(payload)
            row = existing.get((entity, key))
            if row is not None:
                stats[entity]["unchanged" if row.payload_sha256 == digest else "kept_original"] += 1
            else:
                candidate_id = None
                if rec["customer"] and rec["customer"][0]:
                    name, country = rec["customer"]
                    ck = country_code(country) or (" ".join(country.split()).casefold() if country else "")
                    candidate_id = candidates.get((normalise_name(name), ck))
                legacy, recomputed = rec["legacy_total"], rec["recomputed"]
                row = uow.add(LegacyRecord(
                    source_entity=entity, source_key=key[:400], document_number=(rec["number"] or None) and rec["number"][:80],
                    payload=payload, payload_sha256=digest, currency=rec["currency"], legacy_total=legacy,
                    recomputed_total=recomputed,
                    has_discrepancy=legacy is not None and recomputed is not None and cents(legacy) != cents(recomputed),
                    party_candidate_id=candidate_id, applied_run_id=run_id,
                ))
                uow.flush()
                stats[entity]["new"] += 1
            targets[entity][key] = row.id
            for member_entity, keys in rec["members"].items():
                for k in keys:
                    targets[member_entity][k] = row.id
    for entity, mapping in targets.items():
        _mark(actor, run_id, entity, mapping, "migration_legacy_record")
    return {e: dict(s) for e, s in stats.items()}


# ---- orchestration ---------------------------------------------------------------------------------------------------
def run_apply(actor: ActorContext, root: Path, options: Options | None = None, *, i_have_a_backup: bool,
              backup_id: str | None = None, max_backup_age_hours: int = APPLY_BACKUP_MAX_AGE_HOURS) -> RunResult:
    options = options or Options()
    if not i_have_a_backup:
        raise ApplyRefused("backup_flag_required", "an apply needs --i-have-a-backup (and a verified backup)")
    if actor.user_id is None:
        raise ApplyRefused("operator_required", "an apply is run by a named member (--as EMAIL)")
    if not actor.can(APPLY, Scope.COMPANY):
        raise ApplyRefused("permission_denied", f"{actor.display_name} lacks {APPLY}")
    backup = require_verified_backup(actor, backup_id, max_backup_age_hours)
    if not read_export(Path(root)).authorised:
        raise ApplyRefused("export_not_authorised", "export_manifest.json must name authorised_by and exported_at")
    result = run_dry_run(actor, root, options, kind=RunKind.APPLY.value, keep_analysis=True)
    an = result.analysis
    assert an is not None
    try:
        with UnitOfWork(actor) as uow:
            run = uow.session.get(MigrationRun, result.run_id)
            assert run is not None
            run.backup_id = backup.backup_id
        applied = _applied(actor)
        summary = {
            "backup_id": backup.backup_id,
            "catalogue": _apply_catalogue(actor, an, result.run_id, options, applied),
            "legacy_records": _apply_legacy(actor, an, result.run_id, applied),
            "opening_balances": "not applied: a separate approved batch (lk migration opening-balances stage)",
            "stock_movements": 0,
        }
        with UnitOfWork(actor) as uow:
            run = uow.session.get(MigrationRun, result.run_id)
            assert run is not None
            run.report = {**(run.report or {}), "apply": summary}
            complete(uow, run)
            result.report = dict(run.report)
            result.status = run.status
        return result
    except AppError as exc:
        fail(actor, result.run_id, RunKind.APPLY.value, exc.code, exc.detail)
        raise
    except Exception as exc:
        fail(actor, result.run_id, RunKind.APPLY.value, type(exc).__name__, str(exc) or type(exc).__name__)
        raise


__all__ = ["APPLY", "ApplyRefused", "require_verified_backup", "run_apply"]
