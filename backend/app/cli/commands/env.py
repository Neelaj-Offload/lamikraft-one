"""``lk env``: per-worktree ``.env`` generation on top of machine-shared dev secrets."""

from __future__ import annotations

import argparse
import base64
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from app.cli import CliError, arg, command, dotenv, err, group, out
from app.cli.paths import repo_root, shared_secrets_path

group("env", "Local environment files (.env per worktree, shared dev secrets)")

PG_HOST = "127.0.0.1"
PG_PORT = 54329
MAX_SLOT = 9  # slot 10 would put its API on 8100, the e2e API port of slot 0

SHARED_KEYS = (
    "LK_PG_SUPERUSER_PASSWORD",
    "LK_DB_OWNER_PASSWORD",
    "LK_DB_APP_PASSWORD",
    "LK_MINIO_ROOT_USER",
    "LK_MINIO_ROOT_PASSWORD",
)
# Values a developer may have changed (or that encrypt data at rest) survive `--force`.
KEPT_ON_FORCE = (
    "LK_SECRET_KEY",
    "LK_DATA_ENCRYPTION_KEYS",
    "LK_AI_MODE",
    "LK_WHATSAPP_MODE",
    "LK_EMAIL_MODE",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
)


def _slot(value: str) -> int:
    try:
        slot = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("slot must be an integer") from None
    if not 0 <= slot <= MAX_SLOT:
        raise argparse.ArgumentTypeError(f"slot must be between 0 and {MAX_SLOT}")
    return slot


def _new_shared_value(key: str) -> str:
    return "lk-minio" if key == "LK_MINIO_ROOT_USER" else secrets.token_urlsafe(24)  # 32 chars


def _render_shared(values: Mapping[str, str]) -> str:
    return dotenv.render(
        [
            "Lamikraft One - machine-shared development secrets (never commit, never paste into chat).",
            "Created by `lk env init`; every worktree on this machine copies these into its own .env.",
            "The Postgres superuser password is fixed when the lamikraft_pgdata volume is first created.",
        ],
        [(None, [(k, values[k]) for k in SHARED_KEYS])],
    )


def ensure_shared_secrets(seed: Mapping[str, str]) -> tuple[dict[str, str], str]:
    """Create the shared secrets file once (seeding from an existing .env so an initialised
    database volume keeps working), or add keys introduced since it was created."""
    path = shared_secrets_path()
    for _ in range(3):
        if path.is_file():
            current = dotenv.read(path)
            missing = [k for k in SHARED_KEYS if not current.get(k)]
            if not missing:
                return current, "reused"
            for key in missing:
                current[key] = seed.get(key) or _new_shared_value(key)
            dotenv.write_private(path, _render_shared(current), exclusive=False)
            return current, f"updated (added {', '.join(missing)})"
        values = {k: seed.get(k) or _new_shared_value(k) for k in SHARED_KEYS}
        if dotenv.write_private(path, _render_shared(values), exclusive=True):
            return values, "created"
    raise CliError(f"could not create {path}")


def build_env(
    *, slot: int, root: Path, shared: Mapping[str, str], previous: Mapping[str, str]
) -> tuple[str, list[str]]:
    api, web = 8000 + 10 * slot, 3000 + 10 * slot
    storage = (root / "backend" / "var" / f"storage-slot{slot}").as_posix()
    kept = [k for k in KEPT_ON_FORCE if previous.get(k)]

    def keep(key: str, default: str) -> str:
        return previous[key] if key in kept else default

    sections: list[dotenv.Section] = [
        ("runtime", [("LK_ENV", "development"), ("LK_SLOT", str(slot))]),
        (
            "database: compose service postgres (container lk-postgres), shared by all worktrees",
            [
                ("LK_PG_HOST", PG_HOST),
                ("LK_PG_PORT", str(PG_PORT)),
                ("LK_DB_NAME", f"lk_wt{slot}"),
                ("LK_PG_SUPERUSER_PASSWORD", shared["LK_PG_SUPERUSER_PASSWORD"]),
                ("LK_DB_OWNER_PASSWORD", shared["LK_DB_OWNER_PASSWORD"]),
                ("LK_DB_APP_PASSWORD", shared["LK_DB_APP_PASSWORD"]),
            ],
        ),
        (
            f"ports and origins for slot {slot} (api 8000+10N, web 3000+10N, e2e 8100+10N / 3100+10N)",
            [
                ("LK_API_PORT", str(api)),
                ("LK_WEB_PORT", str(web)),
                ("LK_E2E_API_PORT", str(8100 + 10 * slot)),
                ("LK_E2E_WEB_PORT", str(3100 + 10 * slot)),
                ("LK_PUBLIC_ORIGIN", f"http://127.0.0.1:{web}"),
                ("LK_API_INTERNAL_URL", f"http://127.0.0.1:{api}"),
            ],
        ),
        (
            "application secrets for this worktree",
            [
                ("LK_SECRET_KEY", keep("LK_SECRET_KEY", secrets.token_urlsafe(64))),
                (
                    "LK_DATA_ENCRYPTION_KEYS",
                    keep(
                        "LK_DATA_ENCRYPTION_KEYS", "k1:" + base64.b64encode(secrets.token_bytes(32)).decode()
                    ),
                ),
            ],
        ),
        ("storage", [("LK_STORAGE_DIR", storage)]),
        (
            "providers: demo mode needs no keys (see .env.example for live mode)",
            [
                ("LK_AI_MODE", keep("LK_AI_MODE", "demo")),
                ("LK_WHATSAPP_MODE", keep("LK_WHATSAPP_MODE", "demo")),
                ("LK_EMAIL_MODE", keep("LK_EMAIL_MODE", "demo")),
                ("ANTHROPIC_API_KEY", keep("ANTHROPIC_API_KEY", "")),
                ("GEMINI_API_KEY", keep("GEMINI_API_KEY", "")),
            ],
        ),
        (
            "optional MinIO (compose profile s3, dev-only smoke tests)",
            [
                ("LK_MINIO_ROOT_USER", shared["LK_MINIO_ROOT_USER"]),
                ("LK_MINIO_ROOT_PASSWORD", shared["LK_MINIO_ROOT_PASSWORD"]),
            ],
        ),
    ]
    written = {key for _, entries in sections for key, _ in entries}
    extras = [(k, v) for k, v in previous.items() if k not in written]
    if extras:
        sections.append(("kept from the previous .env", extras))
        kept.extend(k for k, _ in extras)
    header = [
        f"Lamikraft One - local environment for worktree slot {slot}. Never commit this file.",
        f"Written by `lk env init --slot {slot}` at {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}.",
        f"Database passwords are copied from {shared_secrets_path().as_posix()} (shared by all worktrees).",
    ]
    return dotenv.render(header, sections), kept


@command(
    "env",
    "init",
    help="Write the repo-root .env for a worktree slot (creates the shared dev secrets on first use)",
    arguments=[
        arg("--slot", type=_slot, required=True, help=f"worktree slot 0-{MAX_SLOT}; sets ports and DB name"),
        arg(
            "--force",
            action="store_true",
            help="rewrite an existing .env (keeps its secrets and provider keys)",
        ),
        arg("--fresh", action="store_true", help="with --force: regenerate everything, keep nothing"),
    ],
)
def env_init(args: argparse.Namespace) -> int:
    if args.fresh and not args.force:
        raise CliError("--fresh only applies together with --force")
    root = repo_root()
    env_path = root / ".env"
    previous = dotenv.read(env_path)
    shared, status = ensure_shared_secrets(previous)
    out(f"shared dev secrets: {shared_secrets_path().as_posix()} ({status})")

    if env_path.exists() and not args.force:
        drift = [k for k in SHARED_KEYS[:3] if previous.get(k) and previous[k] != shared[k]]
        if drift:
            err(f"warning: {', '.join(drift)} in .env differ from the shared secrets file.")
        raise CliError(
            f"{env_path.as_posix()} already exists",
            hint="pass --force to rewrite it (secrets and provider keys are kept unless --fresh)",
        )

    content, kept = build_env(
        slot=args.slot, root=root, shared=shared, previous={} if args.fresh else previous
    )
    dotenv.write_private(env_path, content, exclusive=False)
    (root / "backend" / "var" / f"storage-slot{args.slot}").mkdir(parents=True, exist_ok=True)

    slot = args.slot
    out(f"wrote {env_path.as_posix()} for slot {slot}")
    if kept:
        out(f"  kept from the previous .env: {', '.join(kept)}")
    out(f"  database  lk_wt{slot} and lk_wt{slot}_test on {PG_HOST}:{PG_PORT}")
    out(f"  api       http://127.0.0.1:{8000 + 10 * slot}   web http://127.0.0.1:{3000 + 10 * slot}")
    out(f"  e2e       api :{8100 + 10 * slot}   web :{3100 + 10 * slot}")
    out(f"  storage   {(root / 'backend' / 'var' / f'storage-slot{slot}').as_posix()}")
    out("next: npm run setup  (or lk db ensure-roles, lk db create, lk db create --test, lk db migrate)")
    return 0


@command("env", "show", help="Show the effective local configuration (secrets are shown only as set/missing)")
def env_show(args: argparse.Namespace) -> int:
    from app.core.config import get_settings

    root = repo_root()
    env_path = root / ".env"
    file_values = dotenv.read(env_path)
    s = get_settings()

    def state(value: str) -> str:
        return "set" if value else "MISSING"

    out(f".env            {env_path.as_posix()} ({'present' if env_path.is_file() else 'missing'})")
    out(
        f"shared secrets  {shared_secrets_path().as_posix()} ({'present' if shared_secrets_path().is_file() else 'missing'})"
    )
    out(f"env / slot      {s.env} / {s.slot}")
    out(f"database        {s.db_name} (test: {s.db_name}_test) on {s.pg_host}:{s.pg_port}")
    out(f"api / web       {s.api_host}:{s.api_port} / {s.public_origin}")
    out(f"api internal    {file_values.get('LK_API_INTERNAL_URL', '(not set)')}")
    out(
        f"e2e ports       api {file_values.get('LK_E2E_API_PORT', '?')}  web {file_values.get('LK_E2E_WEB_PORT', '?')}"
    )
    out(f"storage         {s.storage_backend} {Path(s.storage_dir).as_posix()}")
    out(f"modes           ai={s.ai_mode} whatsapp={s.whatsapp_mode} email={s.email_mode}")
    out(
        "secrets         "
        f"superuser={state(s.pg_superuser_password.get_secret_value())} "
        f"owner={state(s.db_owner_password.get_secret_value())} "
        f"app={state(s.db_app_password.get_secret_value())} "
        f"secret_key={state(s.secret_key.get_secret_value())} "
        f"encryption_keys={state(s.data_encryption_keys.get_secret_value())}"
    )
    out(
        "provider keys   "
        f"anthropic={'set' if s.anthropic_api_key.get_secret_value() else 'not set'} "
        f"gemini={'set' if s.gemini_api_key.get_secret_value() else 'not set'}"
    )
    return 0
