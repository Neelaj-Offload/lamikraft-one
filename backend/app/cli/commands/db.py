"""``lk db``: roles, databases, migrations and status for the local PostgreSQL cluster.

Every statement composes identifiers and literals with ``psycopg.sql``; passwords are sent as
SCRAM verifiers computed client-side, so plaintext never reaches the server log.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from app.cli import EXIT_FAILURE, CliError, arg, command, group, out, pg

group("db", "PostgreSQL roles, databases and Alembic migrations")

REQUIRED_EXTENSIONS = ("btree_gist", "pg_trgm")
APP_ROLE_SETTINGS = {"statement_timeout": "30s", "idle_in_transaction_session_timeout": "60s"}
OWNER_ATTRIBUTES = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
APP_ATTRIBUTES = "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
DROPPABLE_PREFIX = "lk_wt"

_TEST = arg("--test", action="store_true", help="target the test database (LK_DB_NAME + '_test')")


def _scram(conn: psycopg.Connection, user: str, password: str) -> str:
    return conn.pgconn.encrypt_password(password.encode(), user.encode(), b"scram-sha-256").decode()


def _role_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name]).fetchone() is not None


def _scalar(conn: psycopg.Connection, query: str, params: list[Any] | None = None) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None:
        raise CliError(f"query returned no row: {query}")
    return row[0]


LOGIN_ROLES: tuple[pg.Role, ...] = ("owner", "app")


@command("db", "ensure-roles", help="Create or update the lk_owner and lk_app login roles (idempotent)")
def ensure_roles(args: argparse.Namespace) -> int:
    s = pg.settings()
    owner, app = pg.role_name("owner", s), pg.role_name("app", s)
    if len({owner, app, s.pg_superuser}) != 3:
        raise CliError("the owner, app and superuser role names must all differ")
    with pg.connect("superuser", "postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('lk_cli.ensure_roles'))")
        for role in LOGIN_ROLES:
            name = pg.role_name(role, s)
            attributes = OWNER_ATTRIBUTES if role == "owner" else APP_ATTRIBUTES
            created = not _role_exists(conn, name)
            if created:
                conn.execute(sql.SQL("CREATE ROLE {} WITH LOGIN").format(sql.Identifier(name)))
            verifier = _scram(conn, name, pg.role_password(role, s))
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH " + attributes + " PASSWORD {}").format(
                    sql.Identifier(name), sql.Literal(verifier)
                )
            )
            out(f"role {name}: {'created' if created else 'exists'}; attributes and password applied")
        for setting, value in APP_ROLE_SETTINGS.items():
            conn.execute(
                sql.SQL("ALTER ROLE {} SET {} = {}").format(
                    sql.Identifier(app), sql.Identifier(setting), sql.Literal(value)
                )
            )
        out(f"role {app}: " + ", ".join(f"{k}={v}" for k, v in APP_ROLE_SETTINGS.items()))
        conn.execute("SELECT pg_advisory_unlock(hashtext('lk_cli.ensure_roles'))")
    return 0


@command(
    "db",
    "create",
    help="Create the worktree database owned by lk_owner, with extensions and lk_app grants (idempotent)",
    arguments=[_TEST],
)
def create(args: argparse.Namespace) -> int:
    s = pg.settings()
    name = pg.database_name(test=args.test, s=s)
    owner, app = pg.role_name("owner", s), pg.role_name("app", s)
    with pg.connect("superuser", "postgres", autocommit=True) as conn:
        missing = [r for r in (owner, app) if not _role_exists(conn, r)]
        if missing:
            raise CliError(
                f"role(s) {', '.join(missing)} do not exist", hint="run 'lk db ensure-roles' first"
            )
        row = conn.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", [name]
        ).fetchone()
        if row is None:
            try:
                conn.execute(
                    sql.SQL("CREATE DATABASE {} WITH OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                        sql.Identifier(name), sql.Identifier(owner)
                    )
                )
                out(f"database {name}: created (owner {owner})")
            except psycopg.errors.DuplicateDatabase:
                out(f"database {name}: created concurrently by another process")
        elif row[0] != owner:
            conn.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(name), sql.Identifier(owner))
            )
            out(f"database {name}: exists; owner changed from {row[0]} to {owner}")
        else:
            out(f"database {name}: exists (owner {owner})")

    ident = {"db": sql.Identifier(name), "owner": sql.Identifier(owner), "app": sql.Identifier(app)}
    statements = [
        *(
            sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(e))
            for e in REQUIRED_EXTENSIONS
        ),
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
        sql.SQL("ALTER SCHEMA public OWNER TO {owner}").format(**ident),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {app}").format(**ident),
        sql.SQL("GRANT CONNECT ON DATABASE {db} TO {app}").format(**ident),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}"
        ).format(**ident),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app}"
        ).format(**ident),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO {app}"
        ).format(**ident),
    ]
    with pg.connect("superuser", name) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('lk_cli.db_bootstrap'))")
        for statement in statements:
            conn.execute(statement)
    out(
        f"database {name}: extensions {', '.join(REQUIRED_EXTENSIONS)}; schema public owned by {owner}; "
        f"{app} has USAGE + default DML/sequence/function grants"
    )
    return 0


@command(
    "db",
    "drop",
    help="Drop the worktree database (never in production; only databases named lk_wt*)",
    arguments=[_TEST, arg("--yes", action="store_true", help="do not ask for confirmation")],
)
def drop(args: argparse.Namespace) -> int:
    s = pg.settings()
    if s.is_production:
        raise CliError("refusing to drop a database while LK_ENV=production")
    name = pg.database_name(test=args.test, s=s)
    if not name.startswith(DROPPABLE_PREFIX):
        raise CliError(f"refusing to drop {name!r}: only databases named {DROPPABLE_PREFIX}* can be dropped")
    if not args.yes:
        if not sys.stdin.isatty():
            raise CliError(f"dropping {name} needs confirmation", hint="pass --yes")
        try:
            answer = input(f"Drop database {name} and all its data? Type the name to confirm: ")
        except EOFError:
            raise CliError(f"dropping {name} needs confirmation", hint="pass --yes") from None
        if answer.strip() != name:
            raise CliError("not confirmed; nothing was dropped")
    with pg.connect("superuser", "postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone() is not None
        if not exists:
            out(f"database {name}: does not exist")
            return 0
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    out(f"database {name}: dropped")
    return 0


@command(
    "db",
    "migrate",
    help="Run Alembic migrations as lk_owner (default: upgrade to head)",
    arguments=[_TEST, arg("--revision", default="head", help="target revision (default: head)")],
)
def migrate(args: argparse.Namespace) -> int:
    from alembic import command as alembic_command

    from app.cli.alembic_support import load_config
    from app.core.config import reset_settings_cache

    cfg = load_config()
    name = pg.database_name(test=args.test)
    if args.test:
        # The migration environment reads Settings, so point Settings itself at the test database.
        os.environ["LK_DB_NAME"] = name
        reset_settings_cache()
    with pg.connect("owner", name):
        pass
    s = pg.settings()
    cfg.attributes["database_url"] = s.owner_database_url  # read by migrations/env.py
    out(f"migrating {name} as {s.db_owner_user} to {args.revision}")
    alembic_command.upgrade(cfg, args.revision)
    out(f"database {name}: at {args.revision}")
    return 0


@command(
    "db",
    "heads",
    help="Print the number of Alembic heads; exits 1 unless there is exactly one",
    arguments=[arg("--verbose", action="store_true", help="also list each head and its file")],
)
def heads(args: argparse.Namespace) -> int:
    from app.cli.alembic_support import script_directory

    script = script_directory()
    found = script.get_heads()
    out(str(len(found)))
    if args.verbose or len(found) != 1:
        for head in found:
            revision = script.get_revision(head)
            location = Path(revision.path).name if revision is not None and revision.path else "?"
            out(f"  {head}  {location}")
    if len(found) != 1:
        out("expected exactly 1 head; rebase onto the integrator's head and run 'lk db reparent <file>'")
        return EXIT_FAILURE
    return 0


@command(
    "db",
    "reparent",
    help="Point a revision file's down_revision at the current single head (used after rebasing a lane)",
    arguments=[arg("path", type=Path, help="path to the revision file to rewrite")],
)
def reparent(args: argparse.Namespace) -> int:
    from app.cli.alembic_support import reparent as reparent_file
    from app.cli.alembic_support import revision_graph, script_directory

    path: Path = args.path.resolve()
    if not path.is_file():
        raise CliError(f"{path.as_posix()} does not exist")
    graph = revision_graph(script_directory())
    info, new_down = reparent_file(path, graph)
    old = ", ".join(info.down_revision) or "None"
    if info.down_revision == ((new_down,) if new_down else ()):
        out(f"{path.name}: down_revision already {old}; unchanged")
    else:
        out(f"{path.name}: down_revision {old} -> {new_down or 'None'}")
    remaining = script_directory().get_heads()
    out(f"alembic heads now: {len(remaining)}")
    return 0 if len(remaining) == 1 else EXIT_FAILURE


def _role_report(conn: psycopg.Connection, names: list[str]) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication,"
        " coalesce(rolconfig, '{}') FROM pg_roles WHERE rolname = ANY(%s)",
        [names],
    ).fetchall()
    report: dict[str, dict[str, Any]] = {}
    for name, login, superuser, bypassrls, createdb, createrole, replication, config in rows:
        report[name] = {
            "login": login,
            "superuser": superuser,
            "bypassrls": bypassrls,
            "createdb": createdb,
            "createrole": createrole,
            "replication": replication,
            "settings": dict(item.split("=", 1) for item in config),
        }
    return report


def _database_report(name: str, owner: str, app: str) -> dict[str, Any]:
    with pg.connect("superuser", name) as conn:
        extensions = dict(conn.execute("SELECT extname, extversion FROM pg_extension ORDER BY 1").fetchall())
        schema_owner, app_create, app_usage, app_connect = conn.execute(
            "SELECT (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'public'),"
            " has_schema_privilege(%s, 'public', 'CREATE'), has_schema_privilege(%s, 'public', 'USAGE'),"
            " has_database_privilege(%s, current_database(), 'CONNECT')",
            [app, app, app],
        ).fetchone() or (None, None, None, None)
        acl_rows = conn.execute(
            "SELECT d.defaclobjtype, d.defaclacl::text FROM pg_default_acl d"
            " JOIN pg_namespace n ON n.oid = d.defaclnamespace"
            " WHERE d.defaclrole = to_regrole(%s) AND n.nspname = 'public'",
            [owner],
        ).fetchall()
        alembic = None
        if _scalar(conn, "SELECT to_regclass('public.alembic_version')") is not None:
            alembic = [r[0] for r in conn.execute("SELECT version_num FROM alembic_version").fetchall()]
    kinds = {"r": "tables", "S": "sequences", "f": "functions"}
    default_grants = {
        kinds.get(kind, kind): any(entry.startswith(f"{app}=") for entry in acl.strip("{}").split(","))
        for kind, acl in acl_rows
    }
    return {
        "extensions": extensions,
        "schema_public_owner": schema_owner,
        "app_can_create_in_public": app_create,
        "app_usage_on_public": app_usage,
        "app_can_connect": app_connect,
        "default_grants_to_app": {k: default_grants.get(k, False) for k in kinds.values()},
        "alembic_version": alembic,
    }


def _login_report(role: pg.Role, name: str) -> dict[str, Any]:
    try:
        with pg.connect(role, name) as conn:
            user, timeout, idle = conn.execute(
                "SELECT current_user, current_setting('statement_timeout'),"
                " current_setting('idle_in_transaction_session_timeout')"
            ).fetchone() or (None, None, None)
        return {
            "ok": True,
            "user": user,
            "statement_timeout": timeout,
            "idle_in_transaction_session_timeout": idle,
        }
    except CliError as exc:
        return {"ok": False, "error": exc.message}


def collect_status() -> tuple[dict[str, Any], list[str]]:
    s = pg.settings()
    owner, app = pg.role_name("owner", s), pg.role_name("app", s)
    names = list(dict.fromkeys([pg.database_name(test=False, s=s), pg.database_name(test=True, s=s)]))
    problems: list[str] = []
    with pg.connect("superuser", "postgres") as conn:
        version = _scalar(conn, "SHOW server_version")
        roles = _role_report(conn, [owner, app])
        owners = dict(
            conn.execute(
                "SELECT datname, pg_get_userbyid(datdba) FROM pg_database WHERE datname = ANY(%s)", [names]
            ).fetchall()
        )
    status: dict[str, Any] = {
        "server": {"host": s.pg_host, "port": s.pg_port, "version": version},
        "roles": roles,
        "databases": {},
        "logins": {},
    }
    for role_name in (owner, app):
        if role_name not in roles:
            problems.append(f"role {role_name} is missing (run lk db ensure-roles)")
    app_role = roles.get(app)
    if app_role:
        for flag in ("superuser", "bypassrls", "createdb", "createrole", "replication"):
            if app_role[flag]:
                problems.append(f"{app} must not have {flag.upper()}")
        for key, value in APP_ROLE_SETTINGS.items():
            if app_role["settings"].get(key) != value:
                problems.append(f"{app} should have {key}={value} (run lk db ensure-roles)")
    if roles.get(owner, {}).get("superuser"):
        problems.append(f"{owner} must not be a superuser")
    for name in names:
        if name not in owners:
            status["databases"][name] = None
            problems.append(
                f"database {name} is missing (run lk db create{' --test' if name.endswith('_test') else ''})"
            )
            continue
        report = _database_report(name, owner, app)
        report["owner"] = owners[name]
        status["databases"][name] = report
        if owners[name] != owner:
            problems.append(f"database {name} is owned by {owners[name]}, expected {owner}")
        for ext in REQUIRED_EXTENSIONS:
            if ext not in report["extensions"]:
                problems.append(f"extension {ext} is missing in {name}")
        if report["schema_public_owner"] != owner:
            problems.append(
                f"schema public in {name} is owned by {report['schema_public_owner']}, expected {owner}"
            )
        if report["app_can_create_in_public"]:
            problems.append(f"{app} can CREATE in {name}.public")
        if not report["app_usage_on_public"] or not report["app_can_connect"]:
            problems.append(f"{app} lacks CONNECT or USAGE on {name}")
        for kind, granted in report["default_grants_to_app"].items():
            if not granted:
                problems.append(f"default privileges on {kind} for {app} are missing in {name}")
    if names[0] in owners:
        for role in LOGIN_ROLES:
            login = _login_report(role, names[0])
            status["logins"][pg.role_name(role, s)] = login
            if not login["ok"]:
                problems.append(f"login as {pg.role_name(role, s)} failed: {login['error']}")
    return status, problems


def _yes_no(value: object) -> str:
    return "yes" if value else "no"


@command(
    "db",
    "status",
    help="Check connectivity, roles (including RLS-relevant attributes), databases and extensions",
    arguments=[arg("--json", action="store_true", help="print the report as JSON")],
)
def status(args: argparse.Namespace) -> int:
    report, problems = collect_status()
    if args.json:
        out(json.dumps({"report": report, "problems": problems}, indent=2, sort_keys=True, default=str))
        return EXIT_FAILURE if problems else 0
    server = report["server"]
    out(f"server     {server['host']}:{server['port']}  PostgreSQL {server['version']}  (superuser login ok)")
    out("roles")
    for name, info in sorted(report["roles"].items()):
        flags = " ".join(
            f"{flag}={_yes_no(info[flag])}"
            for flag in ("login", "superuser", "bypassrls", "createdb", "createrole", "replication")
        )
        settings = ", ".join(f"{k}={v}" for k, v in sorted(info["settings"].items())) or "-"
        out(f"  {name:<10} {flags}  settings: {settings}")
    out("databases")
    for name, info in report["databases"].items():
        if info is None:
            out(f"  {name:<14} MISSING")
            continue
        extensions = ", ".join(f"{k} {v}" for k, v in sorted(info["extensions"].items()))
        grants = ", ".join(f"{k}={_yes_no(v)}" for k, v in info["default_grants_to_app"].items())
        alembic = ", ".join(info["alembic_version"]) if info["alembic_version"] else "not migrated"
        out(
            f"  {name:<14} owner={info['owner']}  public owner={info['schema_public_owner']}  alembic: {alembic}"
        )
        out(f"  {'':<14} extensions: {extensions}")
        out(
            f"  {'':<14} app: connect={_yes_no(info['app_can_connect'])} usage={_yes_no(info['app_usage_on_public'])} "
            f"create={_yes_no(info['app_can_create_in_public'])}  default grants: {grants}"
        )
    if report["logins"]:
        out("logins")
        for name, login in report["logins"].items():
            if login["ok"]:
                out(
                    f"  {name:<10} ok  statement_timeout={login['statement_timeout']} "
                    f"idle_in_transaction_session_timeout={login['idle_in_transaction_session_timeout']}"
                )
            else:
                out(f"  {name:<10} FAILED  {login['error']}")
    if problems:
        out(f"problems ({len(problems)})")
        for problem in problems:
            out(f"  - {problem}")
        return EXIT_FAILURE
    out("status: ok")
    return 0
