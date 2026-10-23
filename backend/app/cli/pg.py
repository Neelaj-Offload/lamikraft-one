"""PostgreSQL connections for CLI commands (psycopg, sync). Credentials come from ``Settings``."""

from __future__ import annotations

from typing import Literal

import psycopg

from app.cli import CliError
from app.core.config import Settings, get_settings

Role = Literal["superuser", "owner", "app"]

_ENV_FOR_ROLE: dict[Role, str] = {
    "superuser": "LK_PG_SUPERUSER_PASSWORD",
    "owner": "LK_DB_OWNER_PASSWORD",
    "app": "LK_DB_APP_PASSWORD",
}


def settings() -> Settings:
    return get_settings()


def role_name(role: Role, s: Settings | None = None) -> str:
    s = s or settings()
    return {"superuser": s.pg_superuser, "owner": s.db_owner_user, "app": s.db_app_user}[role]


def role_password(role: Role, s: Settings | None = None) -> str:
    s = s or settings()
    secret = {
        "superuser": s.pg_superuser_password,
        "owner": s.db_owner_password,
        "app": s.db_app_password,
    }[role]
    value = secret.get_secret_value()
    if not value:
        raise CliError(
            f"{_ENV_FOR_ROLE[role]} is empty",
            hint="run 'lk env init --slot N' (from backend/: uv run python -m app.cli env init --slot 0)",
        )
    return value


def database_name(*, test: bool, s: Settings | None = None) -> str:
    """``LK_DB_NAME``, or its ``_test`` sibling (already-suffixed names are kept, as in tests/conftest.py)."""
    s = s or settings()
    if test and not s.db_name.endswith("_test"):
        return f"{s.db_name}_test"
    return s.db_name


def first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def connect(role: Role, dbname: str, *, autocommit: bool = False) -> psycopg.Connection:
    s = settings()
    user = role_name(role, s)
    try:
        return psycopg.connect(
            host=s.pg_host,
            port=s.pg_port,
            user=user,
            password=role_password(role, s),
            dbname=dbname,
            connect_timeout=5,
            autocommit=autocommit,
            application_name="lk-cli",
        )
    except psycopg.OperationalError as exc:
        message = first_line(exc)
        if "password authentication failed" in message:
            hint = (
                "the password does not match the server. The superuser password is fixed when the "
                "lamikraft_pgdata volume is created; see docs/runbooks/local-dev.md (Troubleshooting)."
            )
        elif "does not exist" in message:
            hint = "run 'lk db ensure-roles' and 'lk db create' (npm run setup does both)"
        else:
            hint = "start PostgreSQL with 'npm run db:up' (docker compose up -d postgres)"
        raise CliError(
            f"cannot connect to PostgreSQL at {s.pg_host}:{s.pg_port} as {user} (database {dbname}): {message}",
            hint=hint,
        ) from exc
