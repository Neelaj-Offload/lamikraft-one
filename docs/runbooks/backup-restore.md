# Backup and restore

Backups are a CLI-only operation (`docs/architecture/permissions.md` §7.8). Settings › Backups shows the facts of
the last backup and restore rehearsal; it cannot start one. Code: `backend/app/modules/migration/backup.py`,
commands in `backend/app/cli/commands/backup.py`. Decision: ADR-048 (the round trip is proven in Slice 5).

All commands run from `backend/` (`uv run python -m app.cli ...`, shown as `lk ...`).

## What a backup holds

`lk backup create` writes one directory `backend/var/backups/bk-<UTC timestamp>-<6 hex>/` (override the root with
`LK_BACKUP_DIR`):

| File | Content |
|---|---|
| `db.dump` | `pg_dump -Fc` of the configured database (`LK_DB_NAME`), run **inside the compose PostgreSQL container** (`docker exec lk-postgres`; override with `LK_PG_CONTAINER`) |
| `storage.zip` | the LocalFs file store (`LK_STORAGE_DIR`), every file with its sha256 |
| `manifest.json` | backup id, database, server and `pg_dump` versions, Alembic revision, dump size and sha256, storage file list with sha256, the row count of every table, the tables with forced row-level security and the policy count |

Consistency: the command opens a `REPEATABLE READ` transaction, exports its snapshot, reads the row counts and RLS
facts in it and runs `pg_dump --snapshot=<that snapshot>`, so the manifest describes exactly what the dump holds even
while the API and worker keep writing.

Safety: the container must carry the compose label `com.docker.compose.project=lamikraft` and be running; any other
container (for example another project's PostgreSQL on the same machine) is refused (`foreign_container`). The
database name must match `lk_[a-z0-9_]+`.

Each backup is recorded in `migration_backup` (one row per company, since the dump covers the whole database) and
emits `system.backup.completed` (or `system.backup.failed`) per company.

S3 storage (`LK_STORAGE_BACKEND=s3`) is not snapshotted by this command; enable bucket versioning and record the
bucket state alongside the database backup.

## Restore rehearsal

```
lk backup create
lk backup restore-rehearsal                # the newest backup
lk backup restore-rehearsal --backup-id bk-20261104T011425Z-00b502
lk backup list
```

The rehearsal never touches a real database:

1. verifies the dump's sha256 against the manifest (a tampered or truncated dump fails here, nothing is restored);
2. creates a **new temporary database** `lk_rehearsal_<8 hex>` (refused if the name exists or equals the configured
   database) from `template0`, owned by `lk_owner`;
3. `pg_restore --exit-on-error` the dump into it through the same container;
4. verification queries: Alembic revision equals the manifest; the same table set; **every table's row count**
   equals the manifest; the same tables have forced RLS and the same number of policies; connecting as `lk_app`
   without `app.company_id`, a tenant table with rows reads as empty (RLS fails closed); the storage archive's
   checksum and every file's sha256;
5. always drops the temporary database (also after a failure) and checks it is gone.

The outcome (`passed` only if every check passed), the checks and the duration are written to
`rehearsal-<timestamp>.json` in the backup directory, recorded on the backup's `migration_backup` rows and emitted as
`system.restore_rehearsal.completed`. The command exits non-zero when the rehearsal fails.

A migration apply relies on this: it is refused unless a backup of the database from the last 24 hours has a passed
rehearsal (`docs/runbooks/migration.md`).

## Restoring for real (rollback)

Only after a decision to roll back (for example a failed cutover):

1. stop the API, the worker and the web app (`npm run dev` processes, or the production services);
2. keep the current database for investigation: rename it (`ALTER DATABASE lk_x RENAME TO lk_x_failed_<date>` as the
   superuser) instead of dropping it;
3. create the database again empty (`lk db create`), then restore:
   `docker exec -i lk-postgres pg_restore -U postgres -d <database> --exit-on-error < <backup dir>/db.dump`;
4. restore the file store: extract `storage.zip` into an empty `LK_STORAGE_DIR` and compare a few sha256 values with
   the manifest;
5. `lk db status` (Alembic revision equals the manifest's), start the services, sign in and check the dashboards;
6. run `lk backup restore-rehearsal --backup-id <id>` again later on a copy if the restore needs to be re-proven.

## Recorded rehearsal (Slice 5 lane, 2026-11-04)

Slot 6 (`lk_wt6`, demo world `--slice 2` + one dry run), migration head `0050`:

```
backup bk-20261104T011425Z-00b502: completed
database lk_wt6 at revision 0050; 159 tables, 2136 rows
dump 1037584 bytes sha256 922b233bf29dbb3f8334a68ef5e0bbcacfb28c0f290f579cc37dcb3489930960
storage 1 files, 51 bytes
rehearsal of bk-20261104T011425Z-00b502 in lk_rehearsal_a221eb6b: passed (9.76 s)
  [pass] dump_checksum   [pass] pg_restore   [pass] alembic_revision: 0050   [pass] tables_present: 159 tables
  [pass] row_counts: 2136 rows in 159 tables   [pass] rls_forced: 139 tables, 139 policies
  [pass] rls_fails_closed: lk_app sees 0 of 79 rows in audit_log without a tenant
  [pass] storage_checksums: 1 files verified   [pass] temporary_database_dropped: lk_rehearsal_a221eb6b
```

The test environment proves the same path on every API run:
`backend/tests/integration/migration/test_backup_restore.py` (committed-mode clone, skipped when Docker or the
container is absent).
