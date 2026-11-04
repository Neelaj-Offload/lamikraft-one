# Lane report: Slice 5 — migration dry-run tooling and backup / restore rehearsal (`lane/s5-migration`)

Worktree `D:\lk-wt\sales`, env slot 6 (`lk_wt6`, API 8060, web 3060), branched from 74c8cd5 (CP4a). Brief:
`docs/superpowers/briefs/s5-migration-backup.md`, with the orchestrator's scope change of 2026-11-04: this lane starts
before Slice 4 and builds the migration dry-run tooling, the backup / restore rehearsal, their screens, tests and
runbooks. The brief's "New capabilities" (offcut reuse, sample lineage, what-if views) are **not** in this pass: they
need the Slice-4 inventory and production modules and become a follow-up on this branch. Opening balances: the
staging / approval / reconciliation side is built; posting is a documented seam (integrator request 1).

## 1. What was built

| Area | Where | Notes |
|---|---|---|
| Tables | `backend/migrations/versions/0050_migration_slice5.py` (placeholder, `down_revision = 0018`) | `migration_run`, `migration_issue`, `migration_id_map` (`UNIQUE(company_id, source_entity, source_key)`), `migration_party_candidate`, `migration_legacy_record` (payload + sha256 immutable by trigger), `migration_opening_batch` / `_line`, `migration_backup`; forced RLS on all; enum CHECKs mirror the StrEnums. Up / down / up and `alembic check` clean on `lk_wt6`. |
| Events | `docs/architecture/events.md` §3.12 → regenerated `catalogue_data.py` | `migration.run.completed/failed`, `system.backup.completed/failed`, `system.restore_rehearsal.completed` (payload ids, digests, counts). |
| Export readers | `app/modules/migration/sources.py` | CSV / XLSX through the import workbench readers (no type inference), JSON arrays / objects, JSON Lines (`mongoexport`), MongoDB Extended JSON unwrapped; `export_manifest.json` authorisation; export digest; media paths contained in the export; two files for one collection, bad JSON or unreadable sheets stop the run (recorded as a failed run). |
| Dry run | `analysis.py`, `catalogue.py`, `documents.py`, `parties.py`, `dry_run.py`; `lk migration dry-run` | Every legacy entity of `CURRENT_STATE_SPEC.md` §4. Catalogue collections reuse the import workbench's `ImportDefinition.normalise` (header aliases, packaging alias reconciliation, `PRICE_AMBIGUOUS`, identifier rules) instead of duplicating them. Quarantine with row references and original values (credentials scrubbed), rerunnable ID map, candidate party links, reconciliation report (counts per collection with a `balanced` check, quote totals by currency with legacy-vs-lines discrepancies, links, file and media hashes, users, challans with `stock_movements: 0`, opening lines). Writes no domain data (asserted). |
| Apply | `apply.py`; `lk migration apply --as EMAIL --i-have-a-backup [--backup-id]` | Refused without the flag, a named operator with `migration.apply.execute`, a backup of this database ≤ 24 h old whose rehearsal passed, and an authorised export. Catalogue written **through the import workbench** (one job per collection, its own quarantine and rollback; job ids in the report); media files stored with sha256 and attached; legacy quotes (+ lines + revisions), custom products, challans (+ lines, `inventory_effect: none`), users (planned role + expanded overrides, no credential), quote settings and grain locks archived exactly in `migration_legacy_record`. Applying twice writes nothing twice. |
| Opening balances | `opening.py`; `lk migration opening-balances stage/approve/post/list` | Staged batch (valid + quarantined lines, totals by unit), approved by a second person (`approver_is_stager` refused), posting through `register_opening_poster` — refused `inventory_module_unavailable` until Slice 4 registers a poster. |
| Backup | `backup.py`; `lk backup create / restore-rehearsal / list` | Snapshot-consistent `pg_dump -Fc --snapshot` inside `lk-postgres` (container must carry the compose label `lamikraft`), storage zip with per-file sha256, manifest with every table's row count and RLS facts; rehearsal into a temporary `lk_rehearsal_<hex>` database (never an existing one) with 9 verification checks, always dropped. |
| API | `router.py`, `service.py`, `schemas.py` | `/api/v1/migration/{runs, runs/{id}, runs/{id}/issues, issue-facets, issues.csv, party-candidates, party-candidates/{id}/decision, opening-balance-batches}`, `/api/v1/system/backups`. Reads are `migration.run.read` / `system.backup.read` with the MFA step-up (like the audit log). |
| Web | `apps/web/src/features/migration/**`, `src/app/(app)/settings/{migration,backups}/**`, `src/messages/migration.ts` | Settings › Migration (latest run facts, run history, candidate customers with link / new / reject / reopen, opening batches), run page (source facts, reconciliation by collection, quote totals by currency and discrepancies, documents and people, links, media, files with checksums, quarantine browser with severity / collection / code facets in the URL, original values, CSV), Settings › Backups (last backup, last rehearsal with its checks, history). One authenticator confirmation unlocks the page. Checked in the browser at 1440 / 375 px, light and dark, after enrolling TOTP for the demo admin on slot 6. |
| Runbooks | `docs/runbooks/migration.md`, `docs/runbooks/backup-restore.md` | export layout, rules table, dry run, candidates, apply / cutover sequence, opening balances, rollback; backup contents, rehearsal, real restore, the recorded rehearsal. |
| Fixture | `backend/tests/fixtures/legacy_export/` (generator kept out of the repo; files committed) | Synthetic export derived from `CURRENT_STATE_SPEC.md` §4 in all formats (CSV, XLSX, JSON, JSONL with Extended JSON), with deliberate alias conflicts, ambiguous and blank-currency prices, duplicate identities (products, quotes, custom products, challans, users), a case-only key collision, orphans, missing / remote / outside-the-export media, unknown statuses and roles, legacy-total discrepancies, attribution to people who left, cleared collections and a non-collection file. |

## 2. Recorded backup + restore rehearsal (slot 6)

```
lk backup create
backup bk-20261104T011425Z-00b502: completed
database lk_wt6 at revision 0050; 159 tables, 2136 rows
dump 1037584 bytes sha256 922b233bf29dbb3f8334a68ef5e0bbcacfb28c0f290f579cc37dcb3489930960
storage 1 files, 51 bytes

lk backup restore-rehearsal
rehearsal of bk-20261104T011425Z-00b502 in lk_rehearsal_a221eb6b: passed (9.76 s)
  [pass] dump_checksum  [pass] pg_restore: exit 0  [pass] alembic_revision: 0050 (backup 0050)
  [pass] tables_present: 159 tables  [pass] row_counts: 2136 rows in 159 tables
  [pass] rls_forced: 139 tables, 139 policies
  [pass] rls_fails_closed: lk_app sees 0 of 79 rows in audit_log without a tenant
  [pass] storage_checksums: 1 files verified  [pass] temporary_database_dropped: lk_rehearsal_a221eb6b
```

`test_backup_restore.py` repeats the round trip on a committed clone in every API run (plus a tampered dump that
fails at the checksum without restoring). No `lk_rehearsal_*` database is left behind.

## 3. Tests

- `tests/integration/migration/test_dry_run.py` — scenario M: every collection reconciles (`balanced`), totals by
  currency (EUR export 5750.00, accepted 4250.00 vs 3850.00 from the lines), every deliberate conflict quarantined
  with its original values, no credentials anywhere, no domain writes (no stock, quotes, challans, products), reruns
  reuse the ID map and candidates without duplication, a corrected export changes one key's status, candidates are
  suggested and never merged, unreadable exports recorded as failed runs.
- `test_apply.py` — the apply's guards (flag, no / stale / failed-rehearsal backup, unauthorised export, missing
  permission), catalogue through the workbench, media stored, exact archive incl. revisions verbatim, no quotes /
  challans / stock created, second apply writes nothing; opening batch staged, second-person approval, posting refused.
- `test_migration_http.py` — route declarations, runs / issues / facets / CSV / candidates / decisions / backups
  over HTTP, optimistic 409, decisions survive reruns; **IDOR matrix**: another company's admin sees and decides
  nothing (404), linking to another company's party is 422 `party_not_found`, a member without the permission gets
  403 everywhere, an admin without an MFA-verified session gets 401 `mfa_required`.
- `test_backup_restore.py` — round trip, tampered dump, unknown ids (committed mode; needs Docker).
- `tests/unit/migration/test_sources.py` — readers, Extended JSON, digest, containment, skipped collections, names.
- Web: `src/features/migration/migration.test.tsx` (9), `src/lib/api/client.test.ts` (+1).

## 4. Decisions and cross-lane changes (for the integrator)

1. **`mfa_required` no longer redirects to sign-in** (`apps/web/src/lib/api/client.ts`, `unauthorizedMiddleware`):
   it was treated like an expired session, so an MFA-flagged read (audit log, migration, backups) on a session
   without MFA bounced through `/login` in a loop of requests. It is now handled in place like `reauth_required`
   (test added). Shared file; small change.
2. Schema names are prefixed (`MigrationRunSummary`, `MigrationRunDetail`, `MigrationIssueRead`, `CandidatePartyRef`)
   to avoid clashes in `openapi.json`.
3. `migration_backup` is a tenant table with one row per company per backup (the dump covers the whole database);
   events are emitted per company.
4. Dry-run product rules follow the workbench exactly (`CATEGORY_NOT_FOUND` quarantined, `PRODUCT_NOT_MIGRATED` for
   rows of quarantined products) so the dry run predicts what an apply will write.
5. Legacy quotes are archived exactly (`migration_legacy_record`), not turned into `sales_quote` rows; "new revisions
   use the corrected engine" therefore starts when a person creates a quote from the archive (follow-up 3).

## 5. Integrator requests

1. **Opening-balance poster (Slice 4 inventory):** register `app.modules.migration.opening.register_opening_poster(fn)`
   in the inventory manifest's `on_load`; `fn(uow, batch, valid_lines) -> posting_ref` posts an opening receipt per
   line (`location_code` → warehouse, `uom_code`, `quantity`, optional `unit_cost`) and returns its reference. Until
   then `post` answers 503 `inventory_module_unavailable`.
2. **Renumber** `0050_migration_slice5` after the Slice-3 stage-2 and Slice-4 migrations (`down_revision` = the head at
   merge).
3. Matrix rows FG-USR-03, FG-QUO-17, FG-QRV-04, FG-MSC-01/02, OQ-04, SCN-M1/M2/M3 are repointed to this lane's tests
   and marked **in progress**; move them to implemented after the merge gate.

## 6. Not done (with reasons)

- **New capabilities** (offcut reuse, sample lineage, what-if views): out of this pass by the orchestrator's scope
  change; they need the Slice-4 inventory and production modules. Follow-up on this branch.
- **Opening-balance posting**: seam only (request 1).
- **Legacy quotes / challans / custom products as live records** (`sales_quote` with `origin=migration`, owner =
  `assigned_to` else `created_by`, FG-QUO-11/12/16): needs a sales / challans import entry point; the archive keeps
  every value so this is a later, re-runnable step. Rows stay planned.
- **User invitations from candidates**: the apply records invitation candidates with their mapped role and overrides;
  sending invitations is left to Settings › Users so the owner controls timing (runbook §5 step 7).
- **Grain locks into `cutting_grain_lock`**: archived; writing them through the cutting service is a small follow-up.
- **Linking a candidate to a non-suggested customer**: needs a party picker in the web; the API accepts any party id
  of the company.
- **Remote media download** (`--fetch-media`) is implemented but untested against a live host (no authorised host).
- **No real legacy export exists**; everything is proven on the synthetic fixture.

## 7. Gates

See the final section appended after the gate runs.
