"""``lk backup``: database + file-store backups through the compose PostgreSQL container, and restore rehearsals.

    lk backup create                 pg_dump (custom format) + storage zip + manifest with checksums
    lk backup restore-rehearsal [--backup-id ID]
                                     restore into a temporary database, verify, drop it (never over a real database)
    lk backup list

Backups are CLI-only (permissions.md §7.8); Settings › Backups shows the facts. See docs/runbooks/backup-restore.md.
"""

from __future__ import annotations

import argparse

from app.cli import EXIT_FAILURE, CliError, arg, command, group, out

group("backup", "Database and file-store backups, restore rehearsals")


@command("backup", "create", help="Back up the database (pg_dump in the compose container) and the file store")
def create(args: argparse.Namespace) -> int | None:
    from app.modules.migration.backup import BackupError, create_backup

    try:
        result = create_backup()
    except BackupError as exc:
        raise CliError(f"{exc.code}: {exc.message}", hint="see docs/runbooks/backup-restore.md") from None
    m = result.manifest
    out(f"backup {result.backup_id}: {result.status}")
    out(f"database {m['database']} at revision {m['alembic_revision']}; {len(m['tables'])} tables, "
        f"{sum(m['tables'].values())} rows")
    out(f"dump {m['dump']['bytes']} bytes sha256 {m['dump']['sha256']}")
    out(f"storage {m['storage']['files']} files, {m['storage']['bytes']} bytes")
    out(f"directory {result.directory}")
    return None


@command(
    "backup",
    "restore-rehearsal",
    help="Restore a backup into a temporary database, run the verification queries, drop it",
    arguments=[arg("--backup-id", default=None, help="the backup to rehearse (default: the newest)")],
)
def restore_rehearsal(args: argparse.Namespace) -> int | None:
    from app.modules.migration.backup import BackupError
    from app.modules.migration.backup import restore_rehearsal as rehearse

    try:
        result = rehearse(args.backup_id)
    except BackupError as exc:
        raise CliError(f"{exc.code}: {exc.message}", hint="see docs/runbooks/backup-restore.md") from None
    out(f"rehearsal of {result.backup_id} in {result.database}: {result.outcome} ({result.seconds} s)")
    for c in result.checks:
        out(f"  [{'pass' if c['passed'] else 'FAIL'}] {c['check']}: {c['detail'] or ''}")
    return None if result.outcome == "passed" else EXIT_FAILURE


@command("backup", "list", help="List backups recorded in this database (newest first)",
         arguments=[arg("--limit", type=int, default=10)])
def list_backups(args: argparse.Namespace) -> int | None:
    from app.cli.commands.migration import cli_actor, company_id_for
    from app.modules.migration import service

    company_id, _key = company_id_for(None)
    facts = service.backup_facts(cli_actor(company_id, None, "system.backup.read"), limit=args.limit)
    for b in facts.history:
        out(f"{b.started_at.isoformat()}  {b.backup_id}  {b.status:<9} dump {b.dump_bytes or 0} B  "
            f"rehearsal {b.rehearsal_outcome or '-'}")
    if not facts.history:
        out("no backups recorded")
    return None
