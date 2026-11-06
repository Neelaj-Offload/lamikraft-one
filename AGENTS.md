# AGENTS.md — Lamikraft One ERP

Instructions for coding agents (Codex, Claude Code, others) working in this repository.
**Start every session by reading [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md)**: it holds the current state, where the
unfinished work lives and the ordered list of what to do next. This file holds the rules that never change.

## What this is

Lamikraft One: an ERP for Crown / Lamikraft (laminate/decor manufacturer, export quoting). It replaces a legacy
FastAPI + MongoDB portal (`CURRENT_STATE_SPEC.md`). The authoritative requirements are `OPUS_5_5_BUILD_PROMPT.md`;
the plan of record is `docs/PLAN.md` (Slices 0–6); progress is recorded in `docs/BUILD_STATE.md` checkpoints.

- `apps/web` — Next.js 16.4 (React 19, Tailwind 4, react-aria-components, TanStack Query, openapi-fetch). Same-origin:
  Next rewrites `/api/*` to FastAPI.
- `backend/app/{core,platform/*,modules/*}` — FastAPI 0.143, SQLAlchemy 2.1 **sync**, Alembic, psycopg 3, Python 3.14
  via `uv`. One polling worker for outbox/jobs.
- `backend/migrations/versions/` — one linear Alembic chain (`alembic heads` must be 1).
- PostgreSQL 17 in Docker Compose (container `lk-postgres`, `127.0.0.1:54329`), RLS on every tenant table.
- `scripts/dev.mjs` — the single entry for setup/dev/test commands. `backend/app/cli` — the `lk` CLI.

## Commands (run from the repo or worktree root)

| Command | What it does | Time |
|---|---|---|
| `npm run setup -- --slot N` | env file, databases, deps for a worktree slot | minutes |
| `npm run dev` | API + worker + web for this slot | — |
| `npm run check -- --keep-going` | 7 gates: ruff, pytest unit+contract, alembic heads, api:check, eslint, tsc, vitest | ~5–10 min |
| `npm run test:api` | full pytest incl. integration on real Postgres (~1,750 tests) | **70–80 min** — run in the background, log to a file |
| `npm run test:e2e -- --workers=1` | Playwright, own e2e DB, seeds the demo world, builds Next | 30–60 min |
| `npm run api:generate` | regenerate `openapi.json` + `apps/web/src/lib/api/schema.d.ts` | 1 min |
| `cd backend && uv run --locked python -m app.cli <cmd>` | the `lk` CLI (`db`, `seed`, `demo sign-in-link MEERA`, `migration`, `backup`, `env`) | — |

For `test:e2e` and any `next build` on this machine set `LK_NEXT_BUILD_CPUS=2` and
`NODE_OPTIONS=--max-old-space-size=2048` (15.7 GB RAM; builds die otherwise).

## Hard rules

1. **Never push** (there is no remote), never rewrite history, never force-reset a branch that has commits you did not make.
2. **Never run two test suites at once** on this machine (same DB server, limited RAM). Only one `test:e2e` at a time
   (guarded by `~/.lamikraft-dev/e2e.lock`). Never leave dev servers or test runs running when you finish.
3. **Use `127.0.0.1`, never `localhost`.** CSRF/Origin checks compare against `LK_PUBLIC_ORIGIN`. The main checkout
   (slot 0) uses web **3200** / API **8200** because port 8000 belongs to another project.
4. **Never hand-edit generated files**: `backend/openapi.json`, `apps/web/src/lib/api/schema.d.ts`. Regenerate with
   `npm run api:generate`; on a merge conflict in them, take either side and regenerate.
5. **Migrations**: only through the helpers in `backend/migrations`; keep one head; never edit a revision already on `main`.
6. **No secrets in the repo or docs.** `.env*` is git-ignored; live credentials are the owner's to place. Demo
   adapters (Claude, Gemini, STT/TTS, WhatsApp, accounting) stay the default and stay labelled "Demo".
7. **No placeholder UI**: every visible control works or is not rendered. No floats for money/quantities
   (`DecimalStr`). Raw SQL only in `platform/**`, `core/db/**` and allow-listed `sql.py` files.
8. **Honest status**: only claim "Implemented (verified)" with test evidence recorded in `docs/BUILD_STATE.md`.
   If a gate fails, record it; after three failed attempts at the same thing, record the cause and move on.
9. Commit locally after each verified unit of work, conventional-commit style (`feat(module):`, `fix(web):`,
   `test(...)`, `docs:`), matching `git log`.

## Conventions worth knowing before you edit

- `docs/architecture/*.md` are the frozen contracts: `conventions.md`, `api-conventions.md` (problem+json errors,
  409 for conflicts, `capabilities` in responses, `Idempotency-Key`), `permissions.md` (`<module>.<resource>.<action>`,
  scopes own<team<branch<company), `events.md` (`<module>.<entity>.<past_verb>`, outbox), `fixtures.md` (the demo
  world: Crown Decor (Demo), people Sahil/Meera/Neha/Ravi/Kabir/Arjun/Ananya/Priya, clock frozen 2026-10-12 08:55 IST).
- Tests reference fixture constants (`backend/app/seed/world/keys.py`), never literals. Each module declares permissions in `policies.py`
  and events in `events.py`; startup validation rejects unknown keys/events.
- Web: keep shell/design-system components; respect `routes.test.ts` and `design-lint.test.ts` invariants; a server
  page never calls a `"use client"` function.
- Parallel work uses git worktrees under `D:\lk-wt\<name>` with their own slot (ports `8000+10N` / `3000+10N`,
  DB `lk_wtN`). See `docs/runbooks/local-dev.md` §"Worktree slots".

## Common pitfalls

- Test DB stamped with an old placeholder revision → `uv run --locked python -m app.cli db drop --test --yes` then
  `db create --test` (in `backend/`, inside that worktree).
- A stale `next dev` holds Next's dev lock and causes false hydration errors — check
  `netstat -ano | findstr ":3200"` and ask the owner to end the process.
- `.gitignore` has an unanchored `backups/` that also matches `apps/web/src/app/(app)/settings/backups/` — anchor it
  to `/backups/` (listed as a task in `CODEX_HANDOFF.md`).
- The repo path contains a space (`D:\Lamikraft ERP`); quote paths.
