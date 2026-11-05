"""``lk migration``: legacy migration dry runs, the guarded apply and the opening-balance batch.

    lk migration dry-run --source <export dir> [--company KEY] [--as EMAIL] [--fetch-media]
    lk migration apply --source <export dir> --as EMAIL --i-have-a-backup [--backup-id ID]
    lk migration runs [--company KEY]
    lk migration opening-balances approve --batch ID --as EMAIL

A dry run writes no domain data: it records the run, its quarantine, the rerunnable ID map, candidate party links and
the reconciliation report (also written as JSON next to the issues CSV under ``backend/var/migration/<run id>/``).
The apply refuses without ``--i-have-a-backup`` and a backup from the last 24 hours whose restore rehearsal passed
(docs/runbooks/migration.md, docs/runbooks/backup-restore.md).
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from app.cli import CliError, arg, command, group, out

group("migration", "Legacy migration: dry run, guarded apply, opening balances")


def company_id_for(key: str | None) -> tuple[uuid.UUID, str]:
    from sqlalchemy import select

    from app.platform.authz.context import ActorContext
    from app.platform.org.models import Company
    from app.platform.uow import UnitOfWork

    with UnitOfWork(ActorContext.system(None, reason="cli")) as uow:
        rows = list(uow.session.execute(select(Company.id, Company.company_key).order_by(Company.company_key)))
    if key:
        for cid, ckey in rows:
            if ckey == key:
                return cid, ckey
        raise CliError(f"no company with key {key!r}", hint="known: " + ", ".join(k for _, k in rows))
    if len(rows) == 1:
        return rows[0][0], rows[0][1]
    raise CliError("more than one company exists; name one with --company KEY",
                   hint="known: " + ", ".join(k for _, k in rows) if rows else "none exists yet")


def cli_actor(company_id: uuid.UUID, as_email: str | None, permission: str) -> Any:
    """The operator: a member (``--as``, their permissions apply) or the CLI itself (system rights)."""
    from sqlalchemy import select

    from app.platform.authz.actors import actor_for_member
    from app.platform.authz.context import ActorContext
    from app.platform.authz.permissions import Scope
    from app.platform.identity.models import AppUser
    from app.platform.uow import UnitOfWork

    if not as_email:
        return ActorContext(actor_type="cli", company_id=company_id, display_name="CLI (lk migration)",
                            is_system=True, auth_strength="system", channel="cli")
    with UnitOfWork(ActorContext.system(None, reason="cli")) as uow:
        user_id = uow.session.scalar(select(AppUser.id).where(AppUser.email_normalized == as_email.strip().lower()))
    if user_id is None:
        raise CliError(f"no user {as_email}")
    from app.core.errors import AppError

    try:
        actor = actor_for_member(company_id, user_id, channel="cli")
    except AppError as exc:
        raise CliError(f"{as_email} is not an active member of the company ({exc.code})") from None
    if not actor.can(permission, Scope.COMPANY):
        raise CliError(f"{as_email} lacks {permission} at company scope")
    return actor.with_(actor_type="cli", channel="cli")


def run_dir(run_id: uuid.UUID) -> Path:
    from app.core.config import BACKEND_DIR

    path = BACKEND_DIR / "var" / "migration" / str(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_outputs(actor: Any, run_id: uuid.UUID, report: dict[str, Any]) -> Path:
    from app.modules.migration import service

    folder = run_dir(run_id)
    (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (folder / "issues.csv").write_bytes(service.issues_csv(actor, run_id))
    return folder


def _options(args: argparse.Namespace) -> Any:
    from app.modules.migration.analysis import Options

    return Options(fetch_media=bool(getattr(args, "fetch_media", False)),
                   default_price_type=getattr(args, "default_price_type", None),
                   default_currency=getattr(args, "default_currency", None),
                   date_order=getattr(args, "date_order", "DMY"))


def print_summary(result: Any) -> None:
    report = result.report
    out(f"run {result.run_id}: {result.status}; {result.issue_count} issues "
        f"({result.quarantined} quarantined, {result.errors} rejected rows)")
    out(f"source digest {report['source']['digest']} (authorised: {report['source']['authorised']})")
    out(f"{'entity':<24} {'rows':>6} {'accepted':>9} {'quarantined':>12} {'rejected':>9} {'repeats':>8}")
    for entity, c in report["entities"].items():
        out(f"{entity:<24} {c['source_rows']:>6} {c['accepted']:>9} {c['quarantined']:>12} {c['rejected']:>9} "
            f"{c['duplicate_identical']:>8}")
    out(f"reconciled (every row has one outcome): {report['reconciled']}")
    ids = report.get("id_maps", {})
    out(f"id maps: {ids.get('total', 0)} ({ids.get('new', 0)} new, {ids.get('changed', 0)} changed, "
        f"{ids.get('unchanged', 0)} unchanged)")
    for cur, t in (report.get("quotes", {}).get("totals_by_currency") or {}).items():
        out(f"quotes {cur}: legacy {t.get('accepted_total', '0')} vs lines {t.get('recomputed_total', '0')} "
            f"({t.get('discrepant_quotes', 0)} with a discrepancy)")
    if "challans" in report:
        out(f"challans: {report['challans']['documents']} documents, stock movements "
            f"{report['challans']['stock_movements']}")


@command(
    "migration",
    "dry-run",
    help="Analyse a legacy export: quarantine, ID maps, candidate party links, reconciliation (writes no domain data)",
    arguments=[
        arg("--source", required=True, type=Path, help="the export directory (one file per legacy collection)"),
        arg("--company", default=None, help="company key (default: the only company)"),
        arg("--as", dest="as_email", default=None, help="run as this member (needs migration.dry_run.run)"),
        arg("--fetch-media", action="store_true", help="download remote media links to hash them (authorised hosts)"),
        arg("--default-price-type", default=None, help="confirm a price type for blank pricing rows"),
        arg("--default-currency", default=None, help="confirm a currency for blank pricing rows"),
        arg("--date-order", default="DMY", choices=["DMY", "MDY"], help="slash-date order in the export"),
        arg("--json", action="store_true", help="print the report as JSON"),
    ],
)
def dry_run(args: argparse.Namespace) -> int | None:
    from app.modules.migration.dry_run import DRY_RUN, run_dry_run
    from app.modules.migration.sources import SourceError

    company_id, key = company_id_for(args.company)
    actor = cli_actor(company_id, args.as_email, DRY_RUN)
    try:
        result = run_dry_run(actor, args.source, _options(args))
    except SourceError as exc:
        raise CliError(f"{exc.code}: {exc.message}", hint="see docs/runbooks/migration.md (export layout)") from None
    folder = write_outputs(actor, result.run_id, result.report)
    if args.json:
        out(json.dumps(result.report, indent=2, ensure_ascii=False, default=str))
    else:
        out(f"company {key}")
        print_summary(result)
        out(f"report: {folder / 'report.json'}")
        out(f"issues: {folder / 'issues.csv'}")
    return None


@command("migration", "runs", help="List migration runs (newest first)",
         arguments=[arg("--company", default=None, help="company key"), arg("--limit", type=int, default=20)])
def runs(args: argparse.Namespace) -> int | None:
    from app.modules.migration import service

    company_id, _key = company_id_for(args.company)
    actor = cli_actor(company_id, None, "migration.run.read")
    page = service.list_runs(actor, limit=args.limit, offset=0)
    for r in page.items:
        out(f"{r.started_at.isoformat()}  {r.id}  {r.kind:<8} {r.status:<10} {r.source_label}  "
            f"issues {r.issue_count} (quarantined {r.quarantined_count})")
    if not page.items:
        out("no runs yet")
    return None


@command(
    "migration",
    "apply",
    help="Write the accepted rows of an authorised export (needs --i-have-a-backup and a rehearsed backup)",
    arguments=[
        arg("--source", required=True, type=Path, help="the export directory"),
        arg("--as", dest="as_email", required=True, help="the operator (needs migration.apply.execute)"),
        arg("--i-have-a-backup", dest="i_have_a_backup", action="store_true",
            help="confirm a fresh backup exists; the apply also checks for one with a passed restore rehearsal"),
        arg("--backup-id", default=None, help="the verified backup to rely on (default: the newest verified)"),
        arg("--max-backup-age-hours", type=int, default=24, help="how old the verified backup may be (default 24)"),
        arg("--company", default=None, help="company key (default: the only company)"),
        arg("--default-price-type", default=None, help="confirm a price type for blank pricing rows"),
        arg("--default-currency", default=None, help="confirm a currency for blank pricing rows"),
        arg("--date-order", default="DMY", choices=["DMY", "MDY"], help="slash-date order in the export"),
    ],
)
def apply(args: argparse.Namespace) -> int | None:
    from app.core.errors import AppError
    from app.modules.migration.apply import APPLY, ApplyRefused, run_apply
    from app.modules.migration.sources import SourceError

    if not args.i_have_a_backup:
        raise CliError("refusing to apply without --i-have-a-backup",
                       hint="run lk backup create and lk backup restore-rehearsal, then pass --i-have-a-backup")
    company_id, key = company_id_for(args.company)
    actor = cli_actor(company_id, args.as_email, APPLY)
    try:
        result = run_apply(actor, args.source, _options(args), i_have_a_backup=True, backup_id=args.backup_id,
                           max_backup_age_hours=args.max_backup_age_hours)
    except ApplyRefused as exc:
        raise CliError(f"{exc.code}: {exc.message}", hint="see docs/runbooks/migration.md (cutover)") from None
    except SourceError as exc:
        raise CliError(f"{exc.code}: {exc.message}") from None
    except AppError as exc:
        raise CliError(f"apply failed: {exc.code}: {exc.detail}", hint="the run is recorded as failed; restore the "
                       "backup if anything was written (docs/runbooks/migration.md, rollback)") from None
    folder = write_outputs(actor, result.run_id, result.report)
    out(f"company {key}")
    print_summary(result)
    applied = result.report.get("apply", {})
    out(f"backup relied on: {applied.get('backup_id')}")
    for entity, entry in (applied.get("catalogue") or {}).items():
        out(f"  {entity:<20} job {entry.get('job_id', '-')} {entry.get('job_status', '')} "
            f"rows {entry.get('rows', 0)} skipped {entry.get('skipped_already_applied', 0)}"
            + (f" files {entry['files_stored']}" if "files_stored" in entry else ""))
    for entity, s in (applied.get("legacy_records") or {}).items():
        out(f"  {entity:<20} legacy records: {s.get('new', 0)} new, {s.get('unchanged', 0)} unchanged, "
            f"{s.get('kept_original', 0)} kept (source changed)")
    out(f"report: {folder / 'report.json'}")
    return None


@command(
    "migration",
    "opening-balances",
    help="Opening stock batch: stage from an export, approve (second person), post (inventory module)",
    arguments=[
        arg("action", choices=["stage", "approve", "post", "list"]),
        arg("--source", type=Path, default=None, help="stage: the export directory holding opening_balances.*"),
        arg("--batch", default=None, help="approve / post: the batch id"),
        arg("--as", dest="as_email", default=None, help="the operator (needs migration.apply.execute)"),
        arg("--company", default=None, help="company key (default: the only company)"),
    ],
)
def opening_balances(args: argparse.Namespace) -> int | None:
    from app.core.errors import AppError
    from app.modules.migration import opening, service
    from app.modules.migration.dry_run import run_dry_run

    company_id, _key = company_id_for(args.company)
    if args.action == "list":
        page = service.list_opening_batches(cli_actor(company_id, None, "migration.run.read"), limit=20)
        for b in page.items:
            out(f"{b.created_at.isoformat()}  {b.id}  {b.status:<9} lines {b.line_count} (quarantined "
                f"{b.quarantined_count}) totals {b.totals}")
        if not page.items:
            out("no opening-balance batches")
        return None
    if not args.as_email:
        raise CliError("opening balances are staged, approved and posted by named members (--as EMAIL)")
    actor = cli_actor(company_id, args.as_email, opening.APPLY)
    try:
        if args.action == "stage":
            if args.source is None:
                raise CliError("stage needs --source")
            result = run_dry_run(actor, args.source, keep_analysis=True)
            assert result.analysis is not None
            batch_id = opening.stage_batch(actor, result.analysis, result.run_id)
            if batch_id is None:
                raise CliError("the export has no opening_balances file")
            out(f"batch {batch_id} staged from run {result.run_id}: {result.report.get('opening_balances')}")
            return None
        if not args.batch:
            raise CliError(f"{args.action} needs --batch")
        batch_id = uuid.UUID(args.batch)
        current = next((b for b in service.list_opening_batches(cli_actor(company_id, None, "migration.run.read"),
                                                                 limit=200).items if b.id == batch_id), None)
        if current is None:
            raise CliError(f"no batch {batch_id}")
        from app.modules.migration.models import OpeningBatch
        from app.platform.uow import UnitOfWork

        with UnitOfWork(actor) as uow:
            version = uow.session.get(OpeningBatch, batch_id).version  # type: ignore[union-attr]
        fn = opening.approve_batch if args.action == "approve" else opening.post_batch
        out(json.dumps(fn(actor, batch_id, version)))
    except AppError as exc:
        raise CliError(f"{exc.code}: {exc.detail}") from None
    return None
