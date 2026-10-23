# Local development runbook

How to set up, run and troubleshoot Lamikraft One on a developer machine (Windows 11 is the
reference platform; macOS and Linux work the same way). Everything below runs from the repository
root unless a step says otherwise.

## What runs where

| Piece | How it runs | Address |
|---|---|---|
| PostgreSQL 17 | Docker Compose service `postgres`, container `lk-postgres`, volume `lamikraft_pgdata` | `127.0.0.1:54329` |
| API (FastAPI) | `uv run python -m uvicorn app.main:app --reload` (the `uvicorn.exe` shim can be blocked by Windows Application Control) from `backend/` | `127.0.0.1:8000 + 10N` |
| Worker | `uv run python -m app.worker` from `backend/` | no port |
| Web (Next.js) | `npm run dev -w apps/web`; rewrites `/api/*` to the API | `127.0.0.1:3000 + 10N` |
| e2e API / web | started by `npm run test:e2e` only | `8100 + 10N` / `3100 + 10N` |
| MinIO (optional) | compose profile `s3`, container `lk-minio` | `127.0.0.1:9000`, console `9001` |

`N` is the worktree slot (0-9; see [Worktree slots](#worktree-slots)). The single compose project
`lamikraft` and its one PostgreSQL container are shared by every worktree on the machine; each
slot gets its own databases `lk_wt<N>` and `lk_wt<N>_test`.

## Prerequisites

Install these yourself; the scripts check them and print the exact fix, but never install
system tools.

| Tool | Version | Check | Install |
|---|---|---|---|
| Node.js + npm | Node 24 (npm 11 or 12) | `node --version` | https://nodejs.org/ or `winget install OpenJS.NodeJS.LTS` |
| uv | 0.13 | `uv --version` | `pip install --user uv==0.13.0` or `winget install --id astral-sh.uv` |
| Docker Desktop | Engine 25+ with Compose v2 | `docker compose version` | https://www.docker.com/products/docker-desktop/ |
| git | 2.4x+ | `git --version` | set `git config core.longpaths true` in the repository |

Python itself is managed by uv (`backend/.python-version`). You do not need `psql`: use
`docker exec -it lk-postgres psql -U postgres` when you want a SQL prompt.

`node scripts/dev.mjs doctor` prints the detected versions and where configuration lives.

## First-time setup

```
npm run setup
```

Steps, each idempotent (re-running is safe and stops at the first failure with a summary table):

1. **Prerequisites**: Node 24, npm, uv, Docker CLI, Compose plugin, and a reachable Docker daemon.
2. **Backend dependencies**: `uv sync --locked` in `backend/` (never rewrites `uv.lock`).
3. **`.env`**: if the repository-root `.env` is missing, runs `lk env init --slot 0`
   (`npm run setup -- --slot 2` picks another slot). An existing `.env` is left untouched.
4. **PostgreSQL**: `docker compose up -d postgres`, then waits until the container is healthy.
5. **Roles**: `lk db ensure-roles` creates `lk_owner` (owns the schema, runs migrations) and
   `lk_app` (runtime: `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`, `statement_timeout=30s`,
   `idle_in_transaction_session_timeout=60s`).
6. **Databases**: `lk db create` and `lk db create --test` create `lk_wt<N>` and `lk_wt<N>_test`
   owned by `lk_owner`, with `pg_trgm` and `btree_gist`, `CREATE` on `public` revoked from
   `PUBLIC`, and default privileges so `lk_app` gets DML on tables, sequences and functions that
   `lk_owner` creates.
7. **Node dependencies**: `npm install` at the root (npm workspaces: `apps/web`).
8. **Migrations**: `lk db migrate` (Alembic `upgrade head` as `lk_owner`).
9. Optional, with `npm run setup -- --with-browsers`: `npx playwright install chromium`.

## Daily start

```
npm run dev
```

`dev` makes sure PostgreSQL is up, syncs backend dependencies, applies pending migrations, then
runs the API, the worker and the web app side by side. Every log line is prefixed with `[api]`,
`[worker]` or `[web]`. It reports when the API answers `/api/v1/health/live` and the web app
answers `/`, then prints the URL to open (`http://127.0.0.1:3000` for slot 0).

- **Ctrl+C** stops everything. Children get a few seconds to exit cleanly, then their whole
  process trees are killed (`taskkill /T /F` on Windows). A second Ctrl+C kills immediately.
- If one process exits (for example the worker crashes on an import error), the others are
  stopped too, so nothing keeps running half-broken.
- Options: `npm run dev -- --no-migrate`, `--no-worker`, `--no-web`.

## Command reference

| Command | What it does |
|---|---|
| `npm run setup` | First-time or repair setup (above) |
| `npm run dev` | Daily start (above) |
| `npm run check` | `ruff check`, `pytest tests/unit tests/contract`, `lk db heads` is exactly 1, `api:check`, web `lint`, `typecheck` and vitest; stops at the first failure and prints a table. `npm run check -- --keep-going` runs every step. |
| `npm run test:api` | The whole pytest suite with `LK_ENV=test` against `lk_wt<N>_test`; extra arguments go to pytest (`npm run test:api -- -k quotes`). |
| `npm run test:e2e` | Takes the machine-wide e2e lock, migrates the test database, builds the web app, starts API, worker and web on the e2e ports with `LK_ENV=test`, runs Playwright, then stops them. `-- --no-build` reuses the last build; other arguments go to Playwright. |
| `npm run api:generate` | Writes `backend/openapi.json` (sorted, indented, trailing newline) and regenerates the web client types (`npm run gen:api -w apps/web`). |
| `npm run api:check` | Fails if `backend/openapi.json` differs from what the app exports. |
| `npm run db:up` | Starts PostgreSQL and waits until it is healthy; `-- --s3` also starts MinIO. |
| `npm run db:migrate` | `lk db migrate`; `npm run db:migrate -- --test` migrates the test database. |
| `npm run seed:demo` | `lk seed demo` (provided by the seed module). |
| `node scripts/dev.mjs lk <args>` | Runs the backend CLI from the root, e.g. `node scripts/dev.mjs lk db status`. |

### The `lk` CLI

From `backend/`: `uv run python -m app.cli <group> <command>` (`--help` at any level).

| Command | Purpose |
|---|---|
| `env init --slot N [--force] [--fresh]` | Write `.env` for slot N (see [Secrets](#how-secrets-are-stored)). |
| `env show` | Effective configuration; secrets appear only as set/missing. |
| `db ensure-roles` | Create or update `lk_owner` / `lk_app`. Passwords are sent as SCRAM verifiers, so plaintext never reaches the server log. |
| `db create [--test]` | Create and configure the dev or test database. |
| `db drop [--test] [--yes]` | Drop it. Refused when `LK_ENV=production` or the name does not start with `lk_wt`. |
| `db migrate [--test] [--revision R]` | Alembic upgrade as `lk_owner`. |
| `db heads [--verbose]` | Prints the number of Alembic heads; exits 1 unless it is exactly 1. |
| `db reparent <file>` | Points a revision's `down_revision` (and its `Revises:` line) at the current single head, excluding the file itself and anything built on it. |
| `db status [--json]` | Connectivity, role attributes (superuser, BYPASSRLS, ...), role settings, databases, extensions, `lk_app` privileges and login checks; exits 1 when anything is wrong. |
| `api export-openapi --out FILE` | The deterministic OpenAPI export used by `api:generate` / `api:check`. |

Exit codes: `0` success, `1` failure, `2` usage error, `3` the command (or what it needs, such as
`app.main` or `alembic.ini`) is not installed yet.

Adding a command: create `backend/app/cli/commands/<name>.py` and decorate a handler with
`@command("<group>", "<name>", help=..., arguments=[arg(...)])` from `app.cli`. Modules are
discovered automatically; no shared file changes. Keep heavy imports inside the handler.

## Worktree slots

Parallel work happens in git worktrees, one slot each, so ports and databases never collide:

| Slot | API | Web | e2e API | e2e web | Databases |
|---|---|---|---|---|---|
| 0 | 8000 | 3000 | 8100 | 3100 | `lk_wt0`, `lk_wt0_test` |
| 1 | 8010 | 3010 | 8110 | 3110 | `lk_wt1`, `lk_wt1_test` |
| 2 | 8020 | 3020 | 8120 | 3120 | `lk_wt2`, `lk_wt2_test` |
| N | 8000+10N | 3000+10N | 8100+10N | 3100+10N | `lk_wtN`, `lk_wtN_test` |

Create a worktree on a short path without spaces, then set it up on its own slot:

```
git worktree add D:\lk-wt\sales -b lane/sales
cd D:\lk-wt\sales
npm run setup -- --slot 2
```

All worktrees share the one PostgreSQL container and the dev secrets in `~/.lamikraft-dev`.
File storage is per slot (`backend/var/storage-slot<N>`). Only one `npm run test:e2e` runs at a
time on the machine, guarded by `~/.lamikraft-dev/e2e.lock`.

**Parallel migrations.** Alembic history is one linear chain. After rebasing a lane onto the
integrator's branch, if `lk db heads` prints 2, run
`uv run python -m app.cli db reparent migrations/versions/<your-file>.py` and commit the change.

To move an existing worktree to another slot: `uv run python -m app.cli env init --slot N --force`
(keeps the worktree's secret key, encryption keys, provider keys and any variables you added),
then `npm run setup`.

## How secrets are stored

- **`~/.lamikraft-dev/dev-secrets.env`** (`%USERPROFILE%\.lamikraft-dev` on Windows) is created
  once per machine by the first `lk env init`. It holds random 32-character passwords for the
  PostgreSQL superuser, `lk_owner` and `lk_app`, plus the MinIO root credentials. Every worktree
  copies them, because they all share one database server. Set `LK_DEV_HOME` to keep this
  directory elsewhere.
- **`.env`** (repository root, git-ignored) is per worktree: slot, ports, origins, storage path,
  the copied database passwords, a generated `LK_SECRET_KEY` (64 random bytes, URL-safe) and
  `LK_DATA_ENCRYPTION_KEYS` (`k1:` + base64 of 32 random bytes), and blank provider keys.
- Both files are written with owner-only permissions (POSIX mode 0600; on Windows your profile's
  ACL applies). The tools print where they wrote, never the values.
- **`.env.example`** documents every variable with placeholders only. Never put a real value in it.
- **Live mode** (real AI, WhatsApp, SMTP or S3): add the keys to your `.env` yourself
  (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `LK_WHATSAPP_*`, `LK_SMTP_*`, `AWS_*`) and switch the
  matching `LK_*_MODE`. Never paste keys into chat, commits or issue trackers.
- `lk env init --force` keeps the existing `LK_SECRET_KEY`, `LK_DATA_ENCRYPTION_KEYS`, modes and
  provider keys; `--force --fresh` regenerates everything. Regenerating the encryption keys makes
  existing encrypted data (such as MFA enrolments) unreadable.
- Rotating a database password: change it in the shared file, run `lk env init --force` in every
  worktree, then `lk db ensure-roles` once. The superuser password is a special case (below).

## Troubleshooting

**"the Docker daemon is not reachable".** Start Docker Desktop and wait for "Engine running", then
re-run the command. `docker info` must succeed in the same terminal.

**Docker Desktop shows "An unexpected error occurred … remove …dockerInference / engine.sock: The file cannot be
accessed by the system".** Stale AF_UNIX socket files from a previous session cannot be deleted. Quit Docker Desktop,
rename `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` (for example to `run.stale-<date>`),
create empty folders with the original names, and start Docker Desktop again.

**`Failed to spawn: uvicorn … An Application Control policy has blocked this file`.** The venv's `uvicorn.exe` shim
is blocked; the scripts already run `python -m uvicorn`, so use that form for manual runs too.

**Port already in use.** `dev` and `test:e2e` check their ports first. Find the owner with
`Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess` (PowerShell) or
`netstat -ano | findstr :8000`. Usually it is another worktree on the same slot (give one of them
a new slot) or a leftover process from a crashed run (stop it). If `docker compose up` fails on
54329, another PostgreSQL is bound to that port.

**"password authentication failed for user postgres".** The superuser password is fixed when the
`lamikraft_pgdata` volume is first created, so it no longer matches a shared secrets file that
was deleted and recreated. Either keep the data and reset the password from inside the container
(socket connections there need no password):

```
docker exec -it lk-postgres psql -U postgres -c "\password postgres"
```

and enter the `LK_PG_SUPERUSER_PASSWORD` value from `~/.lamikraft-dev/dev-secrets.env`; or
discard every local database with `docker compose down` and `docker volume rm lamikraft_pgdata`,
then `npm run setup`. For `lk_owner` / `lk_app`, `lk db ensure-roles` re-applies the passwords.

**Paths with spaces.** The main checkout lives at `D:\Lamikraft ERP`. The scripts never build shell
command strings, so the space is safe through `npm run ...`. When typing commands yourself, quote
paths (`cd "D:\Lamikraft ERP\backend"`). Create extra worktrees on short paths without spaces
(`D:\lk-wt\<lane>`) to stay clear of Windows path-length limits in `node_modules` and `.next`.

**127.0.0.1, never localhost.** `localhost` can resolve to `::1` while the servers listen on
`127.0.0.1`, and the browser treats the two as different origins: cookies land in a different jar
and every write fails the Origin/CSRF check with 403. Open `http://127.0.0.1:3000`, not
`http://localhost:3000`. `npm run dev` refuses to start when `LK_PUBLIC_ORIGIN` or
`LK_API_INTERNAL_URL` uses `localhost`.

**`uv run --locked` / `uv sync --locked` fails with "lockfile needs to be updated".** `pyproject.toml`
changed without a new `uv.lock`. Only the integrator relocks; pull their latest lockfile.

**`lk db heads` prints 2 (or `check` fails on "alembic heads == 1").** Two branches each added a
migration. Reparent yours with `lk db reparent <file>` (see [Worktree slots](#worktree-slots)).

**"another e2e run is in progress".** Another worktree is running `npm run test:e2e`. Wait for it.
A lock left by a crashed run is replaced automatically when its process is gone; if the message
persists with no e2e run active, delete `~/.lamikraft-dev/e2e.lock`.

**"Terminate batch job (Y/N)?" after Ctrl+C.** Windows prints this for the npm shim of `next dev`.
Ignore it: `dev` stops the remaining processes itself.

**A command exits with code 3.** Something it needs does not exist yet (for example
`lk seed demo` before the seed module lands, or `apps/web` without a `gen:api` script). The
message names the missing piece.

**Start a worktree's databases from scratch.**

```
cd backend
uv run python -m app.cli db drop --yes
uv run python -m app.cli db create
uv run python -m app.cli db migrate
```

Add `--test` to the first two commands for the test database (the test harness migrates it).

## Optional S3 endpoint (MinIO)

`npm run db:up -- --s3` starts MinIO on `127.0.0.1:9000` (console `9001`) with the generated root
credentials from the shared secrets file. To point the app at it, set in `.env`:
`LK_STORAGE_BACKEND=s3`, `LK_S3_ENDPOINT_URL=http://127.0.0.1:9000`, `LK_S3_BUCKET=<bucket>`,
`LK_S3_REGION=us-east-1`, `AWS_ACCESS_KEY_ID=<LK_MINIO_ROOT_USER>`,
`AWS_SECRET_ACCESS_KEY=<LK_MINIO_ROOT_PASSWORD>`. Upstream MinIO no longer publishes maintained
free images, so this is a local smoke test only and never a production dependency; the S3
adapter's contract tests use moto and need no container.
