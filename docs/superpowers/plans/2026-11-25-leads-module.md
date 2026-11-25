# Leads module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Execution chosen by the owner on 2026-11-25: native (one session, "complete everything"), one whole-branch review
> at the end.

**Goal:** Give leads a pipeline (stage, priority, temperature, source, interests), an activity log whose next
follow-up becomes an owner task, a summary, the `apps/one` screens, and a re-runnable import of the 705-lead sheet.

**Architecture:** Everything lives in the `parties` module (a lead is a party with status `prospect`). New columns on
`parties_party`, two new tenant tables (`parties_lead_source`, `parties_activity`), new commands in
`parties/leads.py` and `parties/lead_sources.py`, a follow-up rule family in `parties/rules.py` registered with the
`tasks.rules` consumer, and a CLI command `lk import leads`. The web side is new screens in `apps/one`.

**Tech Stack:** FastAPI 0.143, SQLAlchemy 2.1 sync, Alembic, Postgres 17 + RLS, pytest; Next.js 16.4, React 19,
TanStack Query, openapi-fetch, react-aria-components.

**Spec:** `docs/superpowers/specs/2026-11-25-leads-module-design.md`

## Global Constraints

- One Alembic head; new revision `0029_leads_crm` using `migrations/helpers.py` (`enable_tenant_rls`, `append_only`,
  `enum_check`). Never edit 0001–0028.
- Permissions and events are declared in `docs/architecture/permissions.md` / `events.md` and regenerated with
  `cd backend && uv run python tools/gen_catalogues.py`; never hand-edit `catalogue_data.py`. New rows carry slice 7.
- Never hand-edit `backend/openapi.json` or `apps/web/src/lib/api/schema.d.ts`: `npm run api:generate`.
- Never edit `apps/web/**`; the new UI imports only non-visual modules from `@/…` (`apps/one/BUILDING.md`).
- Money/quantities are not involved; dates are ISO `date`. Use `127.0.0.1`. Tests use `app.seed.world.keys`
  constants, never literals.
- Party currency limited to INR/EUR/USD/GBP (`default_currency_enabled`).
- UI copy: sentence case, "Lead", "Customer", never "Party"; no em dashes, no exclamation marks.

## Review Focus

1. A lead without an owner task after a follow-up date is set, or two open follow-up tasks for one lead → dedup key
   `lead:{party_id}:follow_up` and the integration test in Task 4.
2. A sales user (`parties.party.read` OWN) seeing another owner's leads in the list, summary or activities → scope
   tests in Tasks 3 and 5.
3. Re-running the import overwriting stage/priority/owner edited in the app, or duplicating contacts → second-run
   test in Task 6.
4. Marking a lead Lost without a reason, or a reason surviving a reopen → stage tests in Task 3 (API 422 and DB check).
5. Sheet rows with odd data: blank company, unknown country, owner not mapped, invalid email, contact block with only
   a phone, date in another format → parser unit tests in Task 6.

---

### Task 0: Merge the rebuilt frontend and branch

- [ ] `git switch -c lane/crm-leads` in `D:\Lamikraft ERP` (from `main` @ the spec commit).
- [ ] `git merge --no-ff lane/web-rebuild -m "merge: bring the apps/one rebuild onto the CRM lane"`; expect no
      conflicts (the rebuild branched from `45c6dc6`, main only added docs).
- [ ] `npm install` at the root if `apps/one` is a workspace without deps here; `npm run -w apps/one typecheck`
      (or `npx tsc -p apps/one`) passes.

### Task 1: Schema — columns, lead sources, activities

**Files:** Create `backend/migrations/versions/0029_leads_crm.py`; modify `backend/app/modules/parties/models.py`.

**Produces:** `Party.website|lead_source_code|interests|requirement|first_contact_on|lead_stage|lost_reason|priority|
temperature|next_follow_up_on`; `LeadSourceRecord` (`parties_lead_source`); `PartyActivity` (`parties_activity`);
constants `LEAD_STAGES`, `OPEN_LEAD_STAGES`, `INTERESTS`, `PRIORITIES`, `TEMPERATURES`, `ACTIVITY_KINDS`,
`SYSTEM_LEAD_SOURCES`.

- [ ] Migration: add the ten columns; checks `lead_stage IN (...)`, `priority IN ('A','B','C')`,
      `temperature IN ('hot','warm','cold')`, `interests <@ ARRAY[...]`, `(lead_stage = 'lost') = (lost_reason IS NOT
      NULL)`, `char_length(requirement) <= 2000`; composite FK `(company_id, lead_source_code)` →
      `parties_lead_source(company_id, code)`; indexes from the spec. Backfill: `UPDATE parties_party SET lead_stage =
      CASE WHEN status = 'prospect' THEN 'new' ELSE 'won' END, first_contact_on = (created_at AT TIME ZONE
      'Asia/Kolkata')::date WHERE 'customer' = ANY(roles)`; `priority='B'`, `temperature='cold'` for the same rows.
- [ ] Create `parties_lead_source` (copy of `parties_customer_type`: id, company_id, code, label, description,
      display_order, is_active, is_system, version, timestamps; unique `(company_id, code)`; code format check) and
      backfill system sources for every company (`website`, `visiting_card`, `trade_show`, `referral`, `other`).
- [ ] Create `parties_activity` (id, company_id, party_id FK, kind check, occurred_at timestamptz, outcome ≤ 200,
      notes ≤ 4000, next_follow_up_on date, created_by FK app_user, created_at); `append_only`; index
      `(company_id, party_id, occurred_at DESC)`. `enable_tenant_rls` on both new tables; grants as earlier revisions.
- [ ] Models mirror the migration exactly. Run `uv run --locked alembic upgrade head` on the slot-0 dev DB and the
      test DB; `uv run --locked python -m app.cli db` check that `alembic heads` is one.
- [ ] Commit `feat(parties): lead pipeline columns, lead sources and activity tables`.

### Task 2: Lead sources (managed list)

**Files:** Create `backend/app/modules/parties/lead_sources.py`; modify `schemas.py`, `router.py`,
`docs/architecture/permissions.md` (`parties.lead_source.manage` | C | | | 7 | mgt), `events.md`
(`parties.lead_source.created` / `.updated`); test `backend/tests/integration/parties/test_lead_sources.py`.

**Produces:** `list_lead_sources(actor) -> list[LeadSourceRead]`, `create_lead_source(uow, LeadSourceCreate)`,
`update_lead_source(uow, id, LeadSourceUpdate)`, `ensure_lead_source(uow, code, *, current=None) -> str | None`
(raises `ValidationFailed` for unknown/inactive codes), `slug_code(label) -> str`. Routes `GET/POST /lead-sources`,
`PATCH /lead-sources/{id}`.

- [ ] Tests first: system sources listed with lead counts; create → assignable; duplicate code 409; inactive cannot be
      newly assigned but an existing lead keeps it; manage capability only for the manage key.
- [ ] Implement by following `customer_types.py` line for line (provisioning, capabilities, counts).
- [ ] Regenerate catalogues; contract tests `tests/contract` pass. Commit `feat(parties): managed lead sources`.

### Task 3: Lead fields, stage command, filters

**Files:** Create `backend/app/modules/parties/leads.py`; modify `schemas.py` (fields on `PartyCreate`,
`PartyUpdate`, `PartySummary`, `PartyDetail`, `PartyFilters`; `LeadStage`, `Interest`, `Priority`, `Temperature`,
`LeadStageChange`), `service.py` (`create_party`/`update_party` accept and validate the new fields; `_summary`;
`_filter_conditions`; `list_parties` sort), `router.py`, `events.py` (`parties.lead.stage_changed`), docs;
tests `test_leads.py`, `tests/unit/parties/test_lead_schemas.py`.

**Produces:** `change_lead_stage(uow, party_id, LeadStageChange) -> PartyDetail` and `POST
/parties/{id}/lead-stage`; capabilities `change_stage`, `log_activity`; filters `lead_stage[]`, `lead_source`,
`interest`, `priority`, `temperature`, `follow_up` (`overdue|today|week`), `sort` (`name|follow_up`).

- [ ] Tests first: create a lead with source/interests/website → read back; `lead_stage` defaults `new` for a customer
      role, `None` for a vendor; lost without reason 422; lost → reason stored, event emitted with from/to; reopen
      clears reason; won sets status active and is final (409 on leaving won); stage change by another owner's sales
      user is 404; filters each narrow correctly; `follow_up=overdue` uses the company time zone date.
- [ ] Implement. Stage changes are rejected in `update_party` (`lead_stage` and `lost_reason` are not in
      `PartyUpdate`). Commit `feat(parties): lead stage, priority, temperature and list filters`.

### Task 4: Activities and follow-up tasks

**Files:** Create `backend/app/modules/parties/activities.py`, `backend/app/modules/parties/rules.py`; modify
`router.py`, `schemas.py` (`ActivityCreate`, `ActivityRead`, `ActivityKind`), `events.py`
(`parties.activity.logged`), `tasks/rules/consumer.py` (register `CRM_TRIGGERS`), `tasks/completion.py`
(`lead_followed_up` check + `CHECK_SOURCES`), `parties/service.py` (`read_party_facts` adds `lead_stage`,
`next_follow_up_on`, `last_activity_at`), docs (`events.md` §3.5 and §4 family `sales.lead_follow_up`,
`permissions.md` `parties.activity.create` | R | D | | 7 | sal O, mgt C); tests `test_activities.py`.

**Produces:** `log_activity(uow, party_id, ActivityCreate) -> ActivityRead`, `list_activities(actor, party_id,
cursor, limit) -> CursorPage[ActivityRead]`; `rules.on_lead_event(uow, event, cache)` and
`rules.derive_follow_up(uow, party_id, cache)`; routes `POST/GET /parties/{id}/activities`.

- [ ] Tests first: log a call with a follow-up → activity listed, party `next_follow_up_on` set, stage new →
      contacted, one open task `lead:{id}:follow_up` assigned to the owner, due that date 18:00 company time, title
      "Follow up with {name}"; a second activity with a new date closes and reopens (still exactly one open); an
      activity without a date closes it; won/lost/archive closes it; the table rejects UPDATE (append-only); a sales
      user cannot log on another owner's lead.
- [ ] Implement the rule as an `IssueOutcome` per lead (family `sales.lead_follow_up`, root ref `parties.party`),
      modelled on `inventory.rules.derive_pick_list`; `responsibility.resolve(uow, "sales.lead_follow_up", [owner])`.
- [ ] Commit `feat(parties): activity log with follow-up tasks`.

### Task 5: Lead summary

**Files:** Modify `leads.py`, `router.py`, `schemas.py` (`LeadSummary`); test in `test_leads.py`.

**Produces:** `lead_summary(actor) -> LeadSummary` (`by_stage`, `by_source`, `by_owner`, `open`, `won_this_month`,
`conversion_rate` as decimal string, `follow_ups_overdue`, `follow_ups_today`); `GET /parties/lead-summary`.

- [ ] Tests first: counts match a constructed set; a sales user sees only own leads; conversion 0 with no leads.
- [ ] Implement with the party repo's scoped conditions. Commit `feat(parties): lead summary`.

### Task 6: `lk import leads`

**Files:** Create `backend/app/modules/parties/lead_import.py` (pure parsing + apply), `backend/app/cli/commands/
leads.py`; tests `tests/unit/parties/test_lead_import_parse.py`, `tests/integration/parties/test_lead_import.py`,
fixture `tests/fixtures/leads/leads_sample.xlsx` (built in the test from rows with invented names).

**Produces:** `parse_sheet(path) -> list[SheetRow]`, `plan_import(rows, owner_map) -> ImportPlan`,
`apply_import(uow, plan) -> ImportReport`; CLI `lk import leads FILE [--company KEY] --as EMAIL (--dry-run|--apply)
[--owner "Name=email"]...`.

- [ ] Unit tests first: header aliases (both "Source" columns), 5 contact blocks, email-only block named by the
      email, empty block skipped, invalid email dropped with an issue, `15-Jan-2026` and Excel date cells, country map
      incl. "United States" → US, currency map, interests split, unknown country / blank company / unmapped owner
      rejected with row numbers.
- [ ] Integration tests: dry run writes nothing; apply creates leads, sources, contacts, address, note lines; second
      apply on the same file → all `unchanged`; after editing stage/priority/owner in the app a re-run keeps them and
      only fills empty fields; a new contact email in the sheet is added.
- [ ] Commit `feat(parties): lk import leads`.

### Task 7: API contract

- [ ] `npm run api:generate`; review the diff of `openapi.json` / `schema.d.ts` (only parties additions). Commit
      `chore(api): regenerate for the leads module`.

### Task 8: `apps/one` screens

**Files:** Create `apps/one/src/data/leads.ts` (hooks: `useLeadSummary`, `useLeadSources`, `useActivities`,
`useLogActivity`, `useChangeLeadStage`, lead-source mutations; query keys under `["parties", …]` so the old caches
invalidate), `apps/one/src/screens/sales/leads/{list-state.ts,list.tsx,record.tsx,activity.tsx,stage-dialogs.tsx,
labels.ts}`, `apps/one/src/screens/settings/lead-sources.tsx` + route `app/(app)/settings/lead-sources/page.tsx`;
modify `app/(app)/sales/parties/page.tsx` (prospect → `LeadList`), the party record route (prospect → lead record
views), customer create/edit forms (new fields), `screens/sales/hub/*` (stat tiles), `shell/nav.ts` (Settings item),
vitest `list-state.test.ts`.

- [ ] Vitest first for `list-state` (parse/serialise every filter, defaults, unknown values dropped).
- [ ] Build the list, record (facts strip, "Log activity" primary, Move stage / Mark won / Mark lost menu, Overview,
      Activity, Contacts, Details views), forms, settings and hub tiles per `BUILDING.md`.
- [ ] `npx tsc`, eslint, vitest for `apps/one`; open `/sales/parties?status=prospect` in the preview against the slot-0
      API, log an activity, check the task in Today, mark lost; screenshots at 1440 and 390, light and dark.
- [ ] Commit `feat(one): leads pipeline screens`.

### Task 9: Gates and checkpoint

- [ ] `npm run check -- --keep-going` (7/7).
- [ ] `npm run test:api > D:\lk-wt\crm-leads-testapi.log 2>&1` in the background; read the tail.
- [ ] Record the checkpoint in `docs/BUILD_STATE.md` (new section "CRM programme — Module 1 Leads") with gate
      evidence; update `CODEX_HANDOFF.md` TL;DR; fast-forward `main`.
