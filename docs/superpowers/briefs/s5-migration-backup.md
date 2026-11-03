# Lane brief: Slice 5 — migration dry-run tooling, backup and restore rehearsal, new capabilities

Branch `lane/s5-migration` from `main` (after the Slice-4 checkpoint). Module owner:
`backend/app/modules/migration/**`, `backend/app/cli/commands/{migration,backup}.py`, `apps/web/src/features/migration/**`
and `src/app/(app)/settings/migration/**`, `docs/runbooks/{migration,backup-restore}.md`, plus the "new
capabilities" items (offcut reuse in `modules/inventory` + `modules/cutting` append-only additions, sample lineage
in `modules/sales`, what-if views in `features/production`). Never push; small named commits; never two test
suites at once; never leave dev servers running.

## Contracts (read first)
1. `OPUS_5_5_BUILD_PROMPT.md` `<migration>` section (every rule: dry-run, ID maps, business keys, packaging
   aliases with conflict reporting, quarantine, exact issued quote snapshots with discrepancy reports, media
   download with checksums, candidate party links, users via invitations, historical attribution, legacy challans
   document-only with no stock, reconciliation of counts/totals/links/hashes, rerunnable mappings, cutover and
   rollback plan, backup before cutover).
2. `CURRENT_STATE_SPEC.md` (the legacy data model: every entity, field group and alias), `docs/PARITY_MATRIX.md`
   rows about migration (`grep -n -i "migrat"`), `docs/PLAN.md` Slice 5 "Migration" and "Backup" and scenario M;
   `docs/BUILD_STATE.md` §5 decisions 12, 13; `docs/DECISIONS.md` ADR-048 (backup round trip proven in Slice 5);
   `events.md` §3.11 (`migration.run.*`, `system.backup.*`, `system.restore_rehearsal.completed`);
   `permissions.md` §7.8 (`migration.*`, backup is CLI-only).
3. Existing: `modules/imports` (the Slice-2 import workbench: staging, batches, quarantine, hashes — reuse its
   staging and quarantine machinery rather than duplicating it), `modules/catalogue/normalise.py` (identifier and
   alias normalisation), `modules/sales` (quote snapshots), `modules/challans`, `platform/files` (media with
   checksums), `platform/identity` (invitations), `app/cli` (command groups), `app/core/db`.

## Deliverables
- **Migration dry-run tooling** `lk migration dry-run --source <dir>` for every legacy entity (products, prices,
  packaging, specs, media, taxonomy, lookup references, custom products, quotes, lines, revisions, users and
  attribution, grain locks, challans): readers for the authorised export formats (CSV/XLSX/JSON as the legacy
  system exports; the spec is not a dump), ID and business-key maps preserved, display SKUs non-unique preserved,
  packaging alias conversion with conflict quarantine and original values kept, pricing ambiguity and duplicate
  identities quarantined, issued quotes stored exactly as snapshots with a legacy-total discrepancy report (never
  rewritten), media proxied into storage with checksums and an inaccessible-link report, candidate party links for
  review (never auto-merged), users as invitation candidates, legacy challans document-only, opening balances as a
  separate approved batch (inventory module), reconciliation report (counts, totals by currency, links, file
  hashes), quarantine, rerunnable mappings (`UNIQUE(source_entity, source_key)`), `lk migration apply` guarded by
  an explicit `--i-have-a-backup` flag and a fresh backup check; cutover and rollback runbook.
- **Backup**: `lk backup create` (pg_dump through the compose container + storage directory snapshot + manifest
  with checksums) and `lk backup restore-rehearsal` into a temporary database with verification queries;
  `system.backup.completed/failed`, `system.restore_rehearsal.completed`; runbook `docs/runbooks/backup-restore.md`.
- **New capabilities**: offcut reuse (cutting plans may consume measured offcut lots; inventory lot kind
  `offcut`), sample lineage (samples link to the custom product, the quote and the dispatch challan; a lineage
  view on the sample), what-if views (read-only production simulation screens).
- **Web**: Settings › Migration (`settings-migration`): run history, reconciliation report, quarantine browser with
  row references, candidate party links review; Settings › Backups: last backup and rehearsal facts (read-only).
- **Tests**: scenario M (migration part): dry run reconciles counts and totals, reruns without duplication,
  creates no stock from legacy challans; restore rehearsal proven in the test environment; IDOR matrix.

## Migration
`backend/migrations/versions/0041_migration_slice5.py`, `down_revision` = current head on `main`.

## Verification and report
`npm run check -- --keep-going` 7/7, `npm run test:api`, `npm run api:generate` committed, web gates, a recorded
backup + restore rehearsal run (log in the report); `docs/lanes/migration-s5.md`. Final message: branch tip,
counts, unfinished items with reasons.
