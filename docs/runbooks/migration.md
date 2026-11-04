# Legacy migration: dry run, apply, cutover and rollback

Moves the legacy SKU Intelligence Portal (MongoDB; `CURRENT_STATE_SPEC.md` §4) into Lamikraft One. The spec is not
a database dump: a real migration needs an **authorised export** of the legacy collections. Until one exists, every
command here is exercised on the synthetic export `backend/tests/fixtures/legacy_export/`, which carries deliberate
conflicts so every quarantine and report path runs.

Code: `backend/app/modules/migration/` (readers `sources.py`, analysers `catalogue.py` / `documents.py` /
`parties.py`, `dry_run.py`, `apply.py`, `opening.py`), commands `backend/app/cli/commands/migration.py`, screens
Settings › Migration and Settings › Backups. Commands run from `backend/` (`uv run python -m app.cli ...`, shown as
`lk ...`). Permissions (`permissions.md` §7.8): `migration.run.read`, `migration.dry_run.run` (MFA),
`migration.apply.execute` (MFA, recent sign-in, sensitive), `migration.party_candidate.update`.

## 1. The export

One file per legacy collection in one directory, named after the collection; any of these formats:

| Format | Notes |
|---|---|
| `.jsonl` / `.ndjson` | one document per line (`mongoexport` default) |
| `.json` | an array, or an object holding it under `items`, `rows` or the collection name |
| `.csv` | UTF-8 (BOM fine; cp1252 read with a warning); delimiter sniffed; every cell stays text |
| `.xlsx` | first sheet; numbers kept exactly (`120.0` stays visible as a float artefact, zero-padded formats kept) |

MongoDB Extended JSON (`$oid`, `$date`, `$numberDecimal`, `$numberLong`, ...) is unwrapped to text. Collections:
`category_taxonomy`, `products_master`, `pricing`, `packaging`, `specifications`, `media`, `lookup_reference`, `users`,
`quote_settings`, `custom_products`, `quotes`, `quote_lines`, `quote_revisions`, `grain_locked_decors` (or
`grain_locks`), `delivery_challans`, `delivery_challan_lines`, plus `opening_balances` (an authorised stock count, not
a legacy collection). Other files (`revision_history`, the cleared legacy `products`, `search_history`, notes) are
listed as ignored. Media binaries go under `media/`; a media row's `file_path` / `storage_path` is resolved inside the
export only (absolute paths and `..` are quarantined).

`export_manifest.json` records the authorisation: `authorised_by`, `exported_at`, optionally `source_system` and
`export_reference`. A dry run without it warns (`EXPORT_NOT_AUTHORISED`); an apply refuses.

Two files for the same collection, invalid JSON or an unreadable sheet stop the run before analysis; the failed run
is still recorded.

## 2. Dry run

```
lk migration dry-run --source D:\exports\legacy-2026-11 [--as admin@company] [--company KEY]
                     [--default-currency INR --default-price-type domestic] [--date-order DMY] [--fetch-media]
```

Writes **no domain data**. It records a run with:

- **the quarantine** (`migration_issue`): every rejected, quarantined or noteworthy row with its row reference (file,
  physical row or document index, legacy key) and the original values (credentials removed);
- **the rerunnable ID map** (`migration_id_map`, `UNIQUE(company, source_entity, source_key)`): one row per legacy
  key with its business key and the hash of the source row. A rerun updates it in place (`id_maps`: new / changed /
  unchanged / status changed / missing from export) and never duplicates it;
- **candidate party links** (`migration_party_candidate`), see §4;
- **the reconciliation report** (Settings › Migration › run; also `backend/var/migration/<run id>/report.json` with
  `issues.csv` beside it): per collection the source rows and their outcome (accepted, quarantined, rejected, exact
  repeat) with `balanced` = every row has exactly one outcome; quote totals by currency (export total, accepted
  total, total recomputed from the lines, difference); links between collections (linked, orphans, unresolved);
  every source file and every reachable media file with its sha256; challans (documents, `stock_movements: 0`);
  users (invitation candidates, historical people, password hashes dropped); opening-balance lines.

Rules applied (OPUS build prompt `<migration>`):

| Situation | Outcome |
|---|---|
| packaging aliases disagree (`carton_qty`/`master_carton_qty`, `inner_qty`/`inner_pack_qty`, `unit_weight_g`/`unit_weight_kg`, `packing_type`/`unit_packing_type`) | quarantined `ALIAS_CONFLICT`, both values kept |
| `price` and `final_price` disagree; two rows for one (product, price type, currency) with different prices | quarantined `PRICE_AMBIGUOUS` |
| blank pricing currency or price type | quarantined unless `--default-currency` / `--default-price-type` confirms one |
| same legacy key or document number with different content (products, quotes, custom products, challans, users by email) | every row quarantined `DUPLICATE_IDENTITY`; exact repeats reported once |
| product keys differing only by case or spacing | quarantined `KEY_CASE_COLLISION` |
| shared display SKUs | preserved, reported `DISPLAY_SKU_SHARED` (display SKUs are not identities) |
| rows for a product not in the export or the catalogue / for a quarantined product | quarantined `ORPHAN_PRODUCT` / `PRODUCT_NOT_MIGRATED` |
| a category not in the taxonomy | quarantined `CATEGORY_NOT_FOUND` (as the products import does) |
| quote statuses outside the quote state set; blank or unknown currency | quarantined |
| legacy total differs from the lines | warning `LEGACY_TOTAL_DISCREPANCY`, listed in the report; the snapshot is kept exactly |
| media file missing / remote link not fetched / path leaving the export | warning `MEDIA_INACCESSIBLE` / `MEDIA_NOT_FETCHED`; quarantine `MEDIA_PATH_OUTSIDE_EXPORT` |
| `created_by` not a legacy user | the name is kept as historical attribution (`ATTRIBUTION_NAME_ONLY`) |
| legacy password hashes | never read into the new system (`CREDENTIAL_DROPPED`) |

Catalogue collections use the import workbench's own value rules (`app/modules/imports/definitions`), so a dry run
and a later workbench import judge a row the same way.

Work the quarantine in the source system or in the export (never in the database), then run the dry run again until
the remaining quarantine is accepted by the owner.

## 3. Backup before any apply

```
lk backup create
lk backup restore-rehearsal
```

See `docs/runbooks/backup-restore.md`. The apply checks for a backup of this database from the last 24 hours whose
rehearsal passed.

## 4. Candidate customers

Legacy quotes and custom products name customers as free text. The dry run groups spellings (case, punctuation and
legal forms such as GmbH, Ltd, Pvt ignored) per country and suggests at most one existing customer (`exact_name`,
`name_tokens`; none when several match equally). Nothing is merged automatically. In Settings › Migration a person
with `migration.party_candidate.update` links the name to the suggested customer, marks it as a new customer or as
not a customer, or reopens a decision. Decisions survive reruns. Linking to a customer other than the suggestion
needs the party picker (follow-up); create or rename the customer first so it becomes the suggestion.

## 5. Apply (cutover)

```
lk migration apply --source D:\exports\legacy-2026-11 --as admin@company --i-have-a-backup [--backup-id bk-...]
```

Refused without `--i-have-a-backup`, a named operator holding `migration.apply.execute`, a verified backup (§3) and an
authorised export. The apply analyses the export again (its own run, `kind = apply`, full quarantine) and writes:

- **catalogue** through the import workbench, one import job per collection (taxonomy, products, pricing, packaging,
  specifications, lookups, reference media): the workbench validates, quarantines what it cannot write and commits;
  each job is in the run report and in Settings › Imports with its own rollback;
- **media files** inside the export: stored through the file store with their sha256 and attached to the product;
  unreachable links become reference media and stay in the inaccessible-link report;
- **legacy documents** into `migration_legacy_record`, exactly as exported (payload + sha256 immutable): quotes with
  their lines and revisions (legacy and recomputed totals, the discrepancy flag, the candidate customer), custom
  products, challans with their lines (`inventory_effect: none`), users (with their planned role template and the
  expanded permission overrides), quote settings, grain locks.

Not part of an apply: stock (see §6) and user accounts (users are invitation candidates; invite them from Settings ›
Users once the cutover is accepted, so nobody reuses a legacy credential). Every written key is marked `applied` in
the ID map; applying the same export again writes nothing twice (rows already applied from the same source row are
skipped; a changed source row is quarantined `SOURCE_CHANGED_SINCE_APPLY`).

Cutover sequence:

1. announce the freeze; stop writes in the legacy system; take the authorised export;
2. `lk migration dry-run` on the export; review the report and the quarantine with the owner; repeat until accepted;
3. `lk backup create` and `lk backup restore-rehearsal` (must pass);
4. `lk migration apply ... --i-have-a-backup`;
5. check the apply run's report (jobs committed, legacy records new, discrepancies as expected), spot-check products,
   prices, media and a few archived quotes against the legacy screens;
6. stage opening balances (§6) and have them approved;
7. invite the users; switch the team over.

## 6. Opening balances

Stock never comes from legacy challans. It starts from an authorised count, staged and approved separately:

```
lk migration opening-balances stage --source <export> --as stager@company
lk migration opening-balances approve --batch <id> --as approver@company     # a second person
lk migration opening-balances post --batch <id> --as approver@company        # needs the inventory module
lk migration opening-balances list
```

The batch keeps valid and quarantined lines with totals by unit. Posting hands the approved lines to the poster the
inventory module registers (`app.modules.migration.opening.register_opening_poster`); until the Slice-4 inventory
module is merged, posting is refused with `inventory_module_unavailable`.

## 7. Rollback

- **Before users start working:** restore the backup taken in §5 step 3 (`docs/runbooks/backup-restore.md`, "Restoring
  for real"). This is the rollback of record: it reverses the catalogue jobs, the legacy archive and the ID map at
  once.
- **A single catalogue collection was wrong:** roll back its import job from Settings › Imports (field-level, only
  while the records are unchanged), correct the export, dry-run and apply again.
- Legacy records are inert (nothing reads them to compute anything); a wrong archive is corrected by restoring the
  backup, never by editing the payload (the database refuses payload changes).
