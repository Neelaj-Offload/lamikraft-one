# Hosting Lamikraft One (Vercel + Railway)

Decided 2026-11-25 (CRM programme module 6): the web app (`apps/one`) on **Vercel**, the API, the worker and
**Postgres on Railway (Singapore)**, files in an S3-compatible bucket, first on a free `*.vercel.app` address. The browser
only ever talks to the Vercel address: Next rewrites `/api/*` to the Railway API, so cookies, CSRF and Origin checks
stay same-origin.

```
browser ──https──> Vercel (apps/one, Next.js, region bom1)
                      │  /api/*  (rewrite, baked in at build)
                      ▼
                   Railway (Singapore): api  ── private network ──>  Postgres 17
                                         worker ──────────────────┘
                   files: S3-compatible bucket (Railway bucket or Cloudflare R2)
```

Never commit credentials. Every secret below goes into the provider's environment settings.

## 1. Code on GitHub

Railway and Vercel deploy from a GitHub repository. The owner creates a **private** repository on their account and
pushes `main` (AGENTS.md rule 1 is lifted only for this, on the owner's explicit go-ahead).

## 2. Railway project

1. New project → **Postgres** (Singapore). Note `PGHOST`, `PGPORT`, `PGUSER` (superuser), `PGPASSWORD`.
2. **Bucket** (or Cloudflare R2): note endpoint, bucket name, access key id and secret.
3. Service **api** from the repo, root directory `backend`, Dockerfile build, `LK_PROCESS=api`, public domain on.
4. Service **worker** from the same repo and root, `LK_PROCESS=worker`, no public domain.

Shared variables for both services (Railway "shared variables"):

| Variable | Value |
|---|---|
| `LK_ENV` | `production` |
| `LK_PG_HOST` / `LK_PG_PORT` | the Postgres private host and port (`${{Postgres.PGHOST}}`, `${{Postgres.PGPORT}}`) |
| `LK_PG_SUPERUSER` / `LK_PG_SUPERUSER_PASSWORD` | `${{Postgres.PGUSER}}` / `${{Postgres.PGPASSWORD}}` (only for the one-time role setup) |
| `LK_DB_NAME` | `lamikraft` |
| `LK_DB_OWNER_USER` / `LK_DB_OWNER_PASSWORD` | `lk_owner` / a new long random password |
| `LK_DB_APP_USER` / `LK_DB_APP_PASSWORD` | `lk_app` / a new long random password (RLS applies to this role) |
| `LK_PUBLIC_ORIGIN` | `https://<project>.vercel.app` (exactly the address people open) |
| `LK_TRUSTED_PROXY_HOPS` | `2` (Vercel, then Railway's edge) |
| `LK_SECRET_KEY` | 64 random bytes, base64 |
| `LK_DATA_ENCRYPTION_KEYS` | as `.env.example` describes (key id and 32-byte key) |
| `LK_STORAGE_BACKEND` | `s3` |
| `LK_S3_ENDPOINT_URL`, `LK_S3_BUCKET`, `LK_S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | from the bucket |
| `LK_AI_MODE`, `LK_WHATSAPP_MODE`, `LK_EMAIL_MODE` | `demo` until the owner places live keys |
| `LK_AMAZON_LWA_CLIENT_ID`, `LK_AMAZON_LWA_CLIENT_SECRET`, `LK_AMAZON_REFRESH_TOKEN`, `LK_AMAZON_SELLER_ID` | only after Amazon approves the developer profile; then switch the Amazon channel to Live in Sales › Marketplaces |

## 3. One-time database setup (Railway shell on the api service)

```sh
python -m app.cli db ensure-roles     # creates lk_owner and lk_app (needs the superuser variables)
python -m app.cli db create           # the lamikraft database with the extensions
python -m app.cli db migrate          # also runs on every api start
python -m app.cli admin create-first --email <owner email> --name "<owner name>" \
  --company-key lamikraft --company-name "<legal name>" --display-company-name "Lamikraft"
```

The password is typed at the prompt (never on the command line). Afterwards remove `LK_PG_SUPERUSER_PASSWORD` from
the services.

## 4. Vercel project

1. Import the GitHub repository; **Root Directory** `apps/one`; keep "Include files outside the root directory" on
   (the app imports `apps/web/src`). `apps/one/vercel.json` installs at the repository root and builds in Mumbai.
2. Environment variables (Production): `LK_API_INTERNAL_URL=https://<api service>.up.railway.app` and
   `LK_PUBLIC_ORIGIN=https://<project>.vercel.app`. Both are read **at build time**; redeploy after changing them.

## 5. First sign-in and data

1. Open `https://<project>.vercel.app`, sign in as the first administrator, set up MFA.
2. Settings › Company: legal name, address, GSTIN, bank accounts (documents print placeholders until then).
3. Settings › People: invite the team (Sahil, Priya, Priyanka Khanna, Akshay Khanna, Priyanka Chatterjee, Priyanka Roy
   Rudra, Anirudh, Francis …); copy each invite link (email stays Demo until SMTP is configured).
4. Leads: `python -m app.cli import leads <file> --as <admin email> --owner "Priyanka Khanna=<email>" ...` first
   without `--apply` (dry run), then with `--apply`. Upload the sheet to the api service shell temporarily and delete it
   afterwards.
5. Warehouses (Operations › Stock): add the NL and US warehouses with market Export; then opening stock per product.

## 6. Custom domain later

Add the domain in Vercel, point the DNS record as Vercel shows, then change `LK_PUBLIC_ORIGIN` on Railway and Vercel
to the new address and redeploy both.

## 7. Backups

Railway Postgres has daily snapshots on paid plans; keep `lk backup create` (docs/runbooks/backup-restore.md) for an
off-platform copy to the bucket.
