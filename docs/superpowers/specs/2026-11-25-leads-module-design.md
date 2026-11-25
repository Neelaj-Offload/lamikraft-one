# Leads module — design

Date: 2026-11-25 · Status: approved in conversation, awaiting written-spec review · Module 1 of the Sales CRM programme

## Why

The team has to start working its real leads in Lamikraft One. Today a lead is only a party with status `prospect`: no
pipeline, no source, no follow-ups. The full list (705 leads, `LamiKraft Leads.xlsx`) lives in a spreadsheet. The owner
asked for the Infinique ops lead flow (`D:\Infinique_ERP\infinique-ops\backend\routes\leads.py`) as the reference:
pipeline stage, activity log with follow-ups, priority and temperature, and summary numbers.

Meeting references: `docs/meetings/2026-11-12-sales-crm-scope-and-phases.md` (customers vs leads, one-by-one entry
for the team), `docs/meetings/2026-11-12-stock-categories-crm-vs-erp-po-pi.md` (leads live in the ERP too).

## Programme context (agreed 2026-11-25)

Build every module locally, host last. Order: 0 merge `lane/web-rebuild` (the `apps/one` frontend) into `main`;
**1 Leads (this spec)**; 2 Customers + samples; 3 Quotations + proforma invoice; 4 Products (design × decor × size) +
stock categories; 5 E-commerce stock sync (Amazon first, Demo until approved); 6 Hosting (Vercel web, Railway
Singapore API + worker + Postgres, `*.vercel.app` first). Each module has its own spec, plan and checkpoint.

## Scope

In: lead fields, lead sources list, pipeline stage, priority and temperature, activity log, follow-up tasks, lead
summary, the one-time import of the spreadsheet, and the `apps/one` screens for all of it.

Out (later modules or never): lead → customer promotion by sample or order (module 2); duplicate-merge screen; a
spreadsheet import screen (the meeting decided the team enters data one by one; the CLI import is for the owner);
sending email or WhatsApp from an activity; lead scoring.

## Data model (module `parties`)

A lead stays a party (role `customer`, status `prospect`). New columns on `parties_party`, all nullable so vendors and
existing customers are untouched:

| Column | Type | Notes |
|---|---|---|
| `website` | varchar(200) | stored as typed, shown as a link |
| `lead_source_code` | varchar(20) | references `parties_lead_source(company_id, code)` |
| `interests` | varchar(30)[] | subset of `lamikraft`, `table_top`, `standard_decorative`, `standard_compact` (fixed list, labels "Lamikraft", "Table top", "Standard decorative", "Standard compact") |
| `requirement` | text ≤ 2,000 | what they asked for ("Chopping boards, platters, risers") |
| `first_contact_on` | date | when the relationship started; defaults to the creation date |
| `lead_stage` | varchar(20) | `new`, `contacted`, `qualified`, `negotiating`, `won`, `lost`; set for every party with the customer role |
| `lost_reason` | varchar(500) | required when `lead_stage = lost`, cleared otherwise (check constraint) |
| `priority` | char(1) | `A`, `B`, `C`; default `B` |
| `temperature` | varchar(10) | `hot`, `warm`, `cold`; default `cold` |
| `next_follow_up_on` | date | denormalised from the latest activity, for list sorting and the overdue count |

Backfill: existing prospects → `new`; existing active customers → `won`. Indexes on `(company_id, lead_stage)`,
`(company_id, lead_source_code)` and `(company_id, owner_user_id, next_follow_up_on)`.

New table `parties_lead_source`, a copy of the customer-type pattern (`customer_types.py`): `code`, `label`,
`display_order`, `is_active`, `is_system`; never deleted, only deactivated; an inactive source cannot be newly
assigned but old leads keep it. System sources: Website, Visiting card, Trade show, Referral, Other. The import adds
the sheet's own sources (NRA Chicago 2026, Intergastra 2026, …) as company sources.

New table `parties_activity` (works for any party, not only leads): `party_id`, `kind` (`call`, `email`, `whatsapp`,
`meeting`, `visit`, `note`), `occurred_at`, `outcome` (≤ 200), `notes` (≤ 4,000), `next_follow_up_on` (date, nullable),
`created_by`. Append-only; a wrong entry is corrected by a new one (audit-friendly, matches Infinique's push-only log).

## Behaviour

- **Stage changes** go through one command, `POST /parties/{id}/lead-stage` (`stage`, `lost_reason`,
  `expected_version`). Lost needs a reason. Won sets the party status `prospect` → `active` (it becomes a customer).
  Won is final in this module (no way back to an open stage; module 2 revisits it with orders and samples). A Lost
  lead can be reopened to any open stage, which clears the reason. Any other move between open stages is free.
- **Logging an activity** (`POST /parties/{id}/activities`) records it, copies `next_follow_up_on` onto the party, and
  moves a `new` lead to `contacted`. Listing: `GET /parties/{id}/activities`, newest first, cursor-paginated.
- **Follow-up tasks**: a rule family `sales.lead_follow_up` in `tasks/rules` consumes `parties.activity.logged`
  and `parties.lead.stage_changed`. When a lead has a next follow-up date it keeps exactly one open task
  (dedup key `lead:{party_id}:follow_up`), "Follow up with {company}", assigned to the lead owner, due that day. A
  later activity closes it (and opens the next one if a new date was set); Won, Lost or archiving closes it.
- **Summary** `GET /parties/lead-summary`: counts by stage, by source and by owner; conversion rate = won ÷ (won +
  lost + open); follow-ups overdue and due today. Respects the caller's read scope (own < team < branch < company).
- **List filters** on `GET /parties`: `lead_stage`, `lead_source`, `interest`, `priority`, `temperature`, `owner`,
  `follow_up` (`overdue`, `today`, `week`); sort by `next_follow_up_on`.
- Events (`events.md` naming): `parties.lead.stage_changed`, `parties.activity.logged`,
  `parties.lead_source.created`, `parties.lead_source.updated`. Permissions (`permissions.md`):
  `parties.activity.create` (sales roles), `parties.lead_source.manage` (admin, sales manager); stage changes use
  `parties.party.update`.
- Every response carries `capabilities` for the new actions, so the UI renders only what the person may do.

## Import: `lk import leads`

`uv run --locked python -m app.cli import leads <file.xlsx> --company lamikraft (--dry-run | --apply)
[--owner "Priyanka Khanna=<email>" ...]`. One transaction per run; dry run prints the same report without writing.

| Sheet column | Becomes |
|---|---|
| Company / Brand name | legal and display name (trimmed) |
| Country | ISO country code via a fixed map of the 65 names in the sheet; unknown → row rejected |
| Interested In | `interests` (comma-split) |
| Asign To | owner, via `--owner` mapping to an existing user; unmapped name → row rejected |
| Lead Source | lead source (created as a company source if new) |
| Requirement | `requirement` |
| Website | `website` |
| Create Date (`15-Jan-2026`) | `first_contact_on` |
| Contact blocks 1–5 (name, designation, email, phone) | contacts; block 1 is primary; a block with only an email or phone uses the email (or "Contact") as the name; an empty block is skipped |
| Per-contact Source | appended to the lead's note ("Bruno Rossi — from Intergastra 2026") when it differs from the lead source |
| State, City, Pincode, Address Line, Address Line (2) | one billing address; skipped when there is no address line |
| Lead Action ≠ "NA" | note line, and stage `negotiating` for "Order Form Issued" |

Default currency by country (EUR for euro countries, GBP, AUD, CAD, INR, otherwise USD). New leads start `new`, `B`,
`cold`. Re-running matches on `name_key` + country: it fills empty fields and adds missing contacts (matched by email,
then name) but never overwrites stage, priority, temperature, owner or activities changed in the app. Invalid emails
are dropped from the contact and listed in the report. Report: created, updated, unchanged, rejected (with row number
and reason).

## Screens (`apps/one`, follow `apps/one/BUILDING.md`)

- **Leads list** (`/sales/parties?status=prospect`): columns Company, Country, Stage, Owner, Next follow-up, Source;
  stage chips; filters for source, interest, priority, temperature, owner ("Mine"), follow-up (overdue / today / this
  week). Overdue follow-ups shown in amber with the word "Overdue".
- **Lead record**: facts strip Stage, Owner, Source, Next follow-up, Priority · temperature. Primary action "Log
  activity" (dialog: kind, when, outcome, notes, next follow-up). Menu: "Move stage", "Mark won", "Mark lost" (a
  `ReasonDialog`). Views: Overview (stage, requirement, interests, next step), Activity (the log), Contacts,
  Details (website, addresses, first contact).
- **Lead form** (create and edit) gains source, interests, website, requirement, first contact, priority, temperature.
- **Settings → Lead sources**: list, add, rename, reorder, deactivate.
- **Sales hub**: the lead summary as stat tiles (open leads, follow-ups overdue, won this month, conversion rate)
  with links into the filtered list.

## Testing

Unit: sheet parsing (contact blocks, dates, country map, currency, owner map), stage rules, lost-reason check.
Integration on real Postgres: migration and backfill, stage command incl. 409 cases, activity → follow-up task open,
replace and close, summary under each read scope, list filters, RLS isolation of the new tables, import dry run vs
apply and an idempotent second run against a trimmed copy of the real sheet stored as a test fixture with invented
names. Contract: `npm run api:generate` diff reviewed. Web: vitest for the new screens' parsers; one Playwright
scenario (log a call with a follow-up, see the task in Today, mark the lead lost with a reason) at 1440 / 834 / 390 px.
Gates: `npm run check`, `npm run test:api`, the new e2e scenario.

## Open owner inputs

Work emails for Priyanka Khanna, Akshay Khanna, Priyanka Chatterjee and Priyanka Roy Rudra (needed before the real
import, not before building it). "Interested in" is a fixed list of four; if Crown adds product lines often, it
becomes a managed list.
