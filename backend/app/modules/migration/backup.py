"""``lk backup create`` and ``lk backup restore-rehearsal`` (ADR-048: the backup round trip is proven in Slice 5).

Create (docs/runbooks/backup-restore.md):
1. a REPEATABLE READ transaction exports a snapshot; table row counts, the Alembic revision and the RLS facts are read
   in it, and ``pg_dump --snapshot`` dumps exactly that state, so the manifest's counts describe the dump;
2. ``pg_dump -Fc`` runs inside the compose PostgreSQL container (``docker exec lk-postgres``; the container must carry
   the compose label ``com.docker.compose.project=lamikraft``), streamed to ``<backup dir>/db.dump`` with its sha256;
3. the file store (``LK_STORAGE_DIR``, LocalFs) is zipped with a per-file sha256 list;
4. ``manifest.json`` records all of it; one ``migration_backup`` row per company and ``system.backup.completed``.

Restore rehearsal: verifies the dump checksum, creates a **temporary** database ``lk_rehearsal_<8 hex>`` (never an
existing one), ``pg_restore``s into it, runs the verification queries (Alembic revision, table set, every row count,
RLS forced on the same tables, RLS fails closed for ``lk_app``, storage checksums), always drops the temporary
database, records the outcome on the backup's rows and emits ``system.restore_rehearsal.completed``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import BACKEND_DIR, get_settings
from app.modules.migration.models import BackupRecord, BackupStatus, RehearsalOutcome

COMPOSE_PROJECT = "lamikraft"
DEFAULT_CONTAINER = "lk-postgres"
_DB_NAME = re.compile(r"^lk_[a-z0-9_]{1,60}$")
_REHEARSAL_DB = re.compile(r"^lk_rehearsal_[0-9a-f]{8}$")
_BACKUP_ID = re.compile(r"^bk-\d{8}T\d{6}Z-[0-9a-f]{6}$")
CHUNK = 1 << 20


class BackupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class BackupResult:
    backup_id: str
    status: str
    directory: Path
    manifest: dict[str, Any]
    error_code: str | None = None


@dataclass
class RehearsalResult:
    backup_id: str
    outcome: str
    database: str
    seconds: float
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c["passed"])

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c["passed"])


# ---- configuration --------------------------------------------------------------------------------------------------
def backup_root() -> Path:
    return Path(os.environ.get("LK_BACKUP_DIR") or (BACKEND_DIR / "var" / "backups"))


def container_name() -> str:
    return os.environ.get("LK_PG_CONTAINER") or DEFAULT_CONTAINER


def _docker(*args: str) -> list[str]:
    return ["docker", *args]


def check_container(name: str | None = None) -> str:
    """The compose PostgreSQL container, refused unless it is running and belongs to the ``lamikraft`` project."""
    name = name or container_name()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
            _docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}|{{.State.Running}}', name),
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError("docker_unavailable", f"docker is not available: {exc}") from exc
    if proc.returncode != 0:
        raise BackupError("container_not_found", f"container {name} was not found (start it with npm run db:up)")
    project, _, running = proc.stdout.strip().partition("|")
    if project != COMPOSE_PROJECT:
        raise BackupError("foreign_container", f"container {name} is not part of the {COMPOSE_PROJECT} compose project")
    if running != "true":
        raise BackupError("container_stopped", f"container {name} is not running")
    return name


def new_backup_id(now: datetime | None = None) -> str:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return f"bk-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _superuser(dbname: str, *, autocommit: bool = False) -> Any:
    from app.cli import pg

    return pg.connect("superuser", dbname, autocommit=autocommit)


def _db_facts(conn: Any) -> dict[str, Any]:
    tables = [r[0] for r in conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname").fetchall()]
    counts: dict[str, int] = {}
    from psycopg import sql

    for t in tables:
        counts[t] = int(conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))).fetchone()[0])
    rls = sorted(r[0] for r in conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relrowsecurity AND c.relforcerowsecurity").fetchall())
    policies = int(conn.execute("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'").fetchone()[0])
    revision = None
    if "alembic_version" in counts:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        revision = row[0] if row else None
    version = conn.execute("SHOW server_version").fetchone()[0]
    return {"tables": counts, "rls_forced_tables": rls, "policies": policies, "alembic_revision": revision,
            "server_version": version}


def _snapshot_storage(storage: Path, target: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if storage.is_dir():
            for path in sorted(p for p in storage.rglob("*") if p.is_file()):
                rel = path.relative_to(storage).as_posix()
                digest = _sha256_file(path)
                size = path.stat().st_size
                zf.write(path, rel)
                files.append({"path": rel, "sha256": digest, "bytes": size})
                total += size
    listing = "\n".join(f"{f['path']}:{f['sha256']}" for f in files)
    return {"file": target.name, "files": len(files), "bytes": total, "sha256": _sha256_file(target),
            "listing_sha256": hashlib.sha256(listing.encode()).hexdigest(), "entries": files}


def _companies() -> list[uuid.UUID]:
    from app.platform.authz.context import ActorContext
    from app.platform.org.models import Company
    from app.platform.uow import UnitOfWork

    with UnitOfWork(ActorContext.system(None, reason="backup")) as uow:
        return list(uow.session.scalars(select(Company.id).order_by(Company.company_key)))


def _record(backup_id: str, values: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
    """Insert or update the backup's row in every company and emit ``event`` once per company."""
    from app.platform.authz.context import ActorContext
    from app.platform.uow import UnitOfWork

    for company_id in _companies():
        with UnitOfWork(ActorContext.system(company_id, reason="backup")) as uow:
            row = uow.session.scalar(select(BackupRecord).where(BackupRecord.backup_id == backup_id))
            if row is None and "status" not in values:
                continue  # a company created after the backup has no row to update
            if row is None:
                row = uow.add(BackupRecord(backup_id=backup_id, **values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
            uow.flush()
            uow.emit(event, aggregate_id=row.id, payload=payload)
            uow.audit(event, resource_type="migration.backup", resource_label=backup_id,
                      outcome="success" if values.get("status", "completed") != "failed" else "failed",
                      details={k: v for k, v in payload.items() if k != "database"})


# ---- create ----------------------------------------------------------------------------------------------------------
def create_backup(*, output_root: Path | None = None) -> BackupResult:
    settings = get_settings()
    database = settings.db_name
    if not _DB_NAME.match(database):
        raise BackupError("unsafe_database_name", f"refusing to back up {database!r}")
    container = check_container()
    started = datetime.now(UTC)
    backup_id = new_backup_id(started)
    folder = (output_root or backup_root()) / backup_id
    folder.mkdir(parents=True, exist_ok=False)
    dump = folder / "db.dump"
    try:
        with _superuser(database, autocommit=True) as conn:
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            facts = _db_facts(conn)
            tool = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
                _docker("exec", container, "pg_dump", "--version"), capture_output=True,
                                  text=True, timeout=30, check=False).stdout.strip()
            h = hashlib.sha256()
            size = 0
            with dump.open("wb") as fh:
                proc = subprocess.Popen(  # noqa: S603 - fixed argument vector, no shell
                    _docker("exec", container, "pg_dump", "-U", settings.pg_superuser, "-d", database, "-Fc",
                            "--no-password", f"--snapshot={snapshot}"),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                assert proc.stdout is not None
                for chunk in iter(lambda: proc.stdout.read(CHUNK), b""):  # type: ignore[union-attr]
                    fh.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
                stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
                code = proc.wait(timeout=3600)
            conn.execute("COMMIT")
        if code != 0 or size == 0:
            raise BackupError("pg_dump_failed", f"pg_dump exited {code}: {stderr.strip()[:500]}")
        storage = _snapshot_storage(Path(settings.storage_dir), folder / "storage.zip") if settings.storage_backend == "local_fs" else {
            "file": None, "files": 0, "bytes": 0, "sha256": None, "listing_sha256": None, "entries": [],
            "note": "S3 storage is not snapshotted here; use bucket versioning (runbook)"}
        finished = datetime.now(UTC)
        manifest = {
            "backup_id": backup_id, "format": 1, "created_at": started.isoformat(), "finished_at": finished.isoformat(),
            "database": database, "server_version": facts["server_version"], "pg_dump": tool,
            "container": container, "alembic_revision": facts["alembic_revision"],
            "dump": {"file": dump.name, "format": "custom", "bytes": size, "sha256": h.hexdigest()},
            "storage": storage, "tables": facts["tables"], "rls_forced_tables": facts["rls_forced_tables"],
            "policies": facts["policies"],
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest_sha = _sha256_file(folder / "manifest.json")
        _record(backup_id, {
            "status": BackupStatus.COMPLETED.value, "database": database,
            "alembic_revision": facts["alembic_revision"], "started_at": started, "finished_at": finished,
            "dump_bytes": size, "dump_sha256": h.hexdigest(), "storage_files": storage["files"],
            "storage_bytes": storage["bytes"], "storage_sha256": storage["sha256"], "manifest_sha256": manifest_sha,
            "table_count": len(facts["tables"]), "row_total": sum(facts["tables"].values()),
        }, "system.backup.completed", {"backup_id": backup_id, "database": database, "dump_sha256": h.hexdigest(),
                                       "dump_bytes": size})
        return BackupResult(backup_id, BackupStatus.COMPLETED.value, folder, manifest)
    except BackupError as exc:
        _fail(backup_id, database, started, exc.code, exc.message)
        raise
    except Exception as exc:
        _fail(backup_id, database, started, type(exc).__name__, str(exc))
        raise BackupError("backup_failed", f"{type(exc).__name__}: {exc}") from exc


def _fail(backup_id: str, database: str, started: datetime, code: str, detail: str) -> None:
    try:
        _record(backup_id, {"status": BackupStatus.FAILED.value, "database": database, "started_at": started,
                            "finished_at": datetime.now(UTC), "error_code": code[:60], "error_detail": detail[:4000]},
                "system.backup.failed", {"backup_id": backup_id, "database": database, "error_code": code[:60]})
    except Exception as exc:  # noqa: BLE001 - recording the failure must not hide the original error
        import structlog

        structlog.get_logger(__name__).warning("backup.failure_not_recorded", backup_id=backup_id, error=str(exc))


# ---- restore rehearsal --------------------------------------------------------------------------------------------------
def find_backup(backup_id: str | None, *, root: Path | None = None) -> Path:
    base = root or backup_root()
    if backup_id:
        if not _BACKUP_ID.match(backup_id):
            raise BackupError("bad_backup_id", f"{backup_id!r} is not a backup id")
        folder = base / backup_id
        if not (folder / "manifest.json").is_file():
            raise BackupError("backup_not_found", f"no completed backup {backup_id} under {base}")
        return folder
    candidates = sorted((p for p in base.glob("bk-*") if (p / "manifest.json").is_file()), key=lambda p: p.name)
    if not candidates:
        raise BackupError("backup_not_found", f"no completed backup under {base}; run lk backup create")
    return candidates[-1]


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str | None = None) -> bool:
    checks.append({"check": name, "passed": bool(passed), "detail": detail})
    return passed


def _drop(name: str) -> None:
    from psycopg import sql

    with _superuser("postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> "
                     "pg_backend_pid()", [name])
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _exists(name: str) -> bool:
    with _superuser("postgres", autocommit=True) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone() is not None


def restore_rehearsal(backup_id: str | None = None, *, root: Path | None = None) -> RehearsalResult:
    from psycopg import sql

    settings = get_settings()
    folder = find_backup(backup_id, root=root)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    bid = manifest["backup_id"]
    container = check_container()
    checks: list[dict[str, Any]] = []
    started = time.monotonic()
    temp = f"lk_rehearsal_{secrets.token_hex(4)}"
    if not _REHEARSAL_DB.match(temp) or temp in (settings.db_name, manifest["database"]):
        raise BackupError("unsafe_rehearsal_target", f"refusing to restore into {temp}")
    dump = folder / manifest["dump"]["file"]
    if not _check(checks, "dump_checksum", dump.is_file() and _sha256_file(dump) == manifest["dump"]["sha256"],
                  f"sha256 {manifest['dump']['sha256'][:16]}..."):
        return _finish(bid, temp, started, checks)
    if _exists(temp):
        raise BackupError("rehearsal_target_exists", f"{temp} already exists; refusing to restore over it")
    try:
        with _superuser("postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                sql.Identifier(temp), sql.Identifier(settings.db_owner_user)))
        with dump.open("rb") as fh:
            proc = subprocess.run(  # noqa: S603 - fixed argument vector, no shell
                _docker("exec", "-i", container, "pg_restore", "-U", settings.pg_superuser, "-d", temp,
                        "--exit-on-error", "--no-password"),
                stdin=fh, capture_output=True, timeout=3600, check=False,
            )
        _check(checks, "pg_restore", proc.returncode == 0,
               f"exit {proc.returncode}" + (f": {proc.stderr.decode('utf-8', 'replace')[:300]}" if proc.returncode else ""))
        with _superuser(temp) as conn:
            facts = _db_facts(conn)
            conn.rollback()
        _check(checks, "alembic_revision", facts["alembic_revision"] == manifest["alembic_revision"],
               f"{facts['alembic_revision']} (backup {manifest['alembic_revision']})")
        expected: dict[str, int] = manifest["tables"]
        missing = sorted(set(expected) - set(facts["tables"]))
        extra = sorted(set(facts["tables"]) - set(expected))
        _check(checks, "tables_present", not missing and not extra,
               f"{len(facts['tables'])} tables" + (f"; missing {missing[:5]}" if missing else "")
               + (f"; extra {extra[:5]}" if extra else ""))
        wrong = {t: (facts["tables"].get(t), n) for t, n in expected.items() if facts["tables"].get(t) != n}
        _check(checks, "row_counts", not wrong,
               f"{sum(expected.values())} rows in {len(expected)} tables" + (f"; differ {dict(list(wrong.items())[:5])}"
                                                                             if wrong else ""))
        _check(checks, "rls_forced", facts["rls_forced_tables"] == manifest["rls_forced_tables"]
               and facts["policies"] == manifest["policies"],
               f"{len(facts['rls_forced_tables'])} tables, {facts['policies']} policies")
        _check(checks, "rls_fails_closed", *_rls_closed(temp, manifest))
        _check(checks, "storage_checksums", *_verify_storage(folder, manifest))
    except Exception as exc:  # noqa: BLE001 - every failure becomes a failed check; the drop still runs
        _check(checks, "rehearsal_error", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        try:
            _drop(temp)
        finally:
            _check(checks, "temporary_database_dropped", not _exists(temp), temp)
    return _finish(bid, temp, started, checks, folder)


def _rls_closed(temp: str, manifest: dict[str, Any]) -> tuple[bool, str]:
    """As ``lk_app`` without ``app.company_id``, a tenant table with rows reads as empty."""
    import psycopg
    from psycopg import sql

    settings = get_settings()
    target = next((t for t in ("company_setting", "audit_log", "domain_event", "migration_run", "parties_party")
                   if manifest["tables"].get(t, 0) > 0 and t in manifest["rls_forced_tables"]), None)
    if target is None:
        target = next((t for t in manifest["rls_forced_tables"] if manifest["tables"].get(t, 0) > 0), None)
    if target is None:
        return True, "no tenant rows in the backup to probe"
    with psycopg.connect(host=settings.pg_host, port=settings.pg_port, user=settings.db_app_user,
                         password=settings.db_app_password.get_secret_value(), dbname=temp, connect_timeout=5,
                         application_name="lk-rehearsal") as conn:
        seen = int(conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(target))).fetchone()[0])
    return seen == 0, f"lk_app sees {seen} of {manifest['tables'][target]} rows in {target} without a tenant"


def _verify_storage(folder: Path, manifest: dict[str, Any]) -> tuple[bool, str]:
    storage = manifest.get("storage") or {}
    if not storage.get("file"):
        return True, storage.get("note") or "no file store snapshot"
    archive = folder / storage["file"]
    if not archive.is_file() or _sha256_file(archive) != storage["sha256"]:
        return False, "storage.zip is missing or its checksum differs"
    scratch = Path(tempfile.mkdtemp(prefix="lk-rehearsal-"))
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                target = (scratch / name).resolve()
                if not target.is_relative_to(scratch.resolve()):
                    return False, f"unsafe path in the archive: {name}"
            zf.extractall(scratch)
        bad = [e["path"] for e in storage["entries"] if _sha256_file(scratch / e["path"]) != e["sha256"]]
        return not bad, f"{len(storage['entries'])} files verified" + (f"; {len(bad)} differ" if bad else "")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _finish(backup_id: str, temp: str, started: float, checks: list[dict[str, Any]],
            folder: Path | None = None) -> RehearsalResult:
    seconds = round(time.monotonic() - started, 2)
    outcome = RehearsalOutcome.PASSED.value if checks and all(c["passed"] for c in checks) else RehearsalOutcome.FAILED.value
    result = RehearsalResult(backup_id, outcome, temp, seconds, checks)
    if folder is not None:
        (folder / f"rehearsal-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps({
            "backup_id": backup_id, "outcome": outcome, "temporary_database": temp, "seconds": seconds,
            "checks": checks}, indent=2), encoding="utf-8")
    _record(backup_id, {"rehearsal_outcome": outcome, "rehearsed_at": datetime.now(UTC), "rehearsal_checks": checks,
                        "rehearsal_seconds": Decimal(str(seconds))},
            "system.restore_rehearsal.completed", {"backup_id": backup_id, "outcome": outcome,
                                                   "checks_passed": result.passed, "checks_failed": result.failed})
    return result


__all__ = [
    "BackupError",
    "BackupResult",
    "RehearsalResult",
    "backup_root",
    "check_container",
    "create_backup",
    "find_backup",
    "restore_rehearsal",
]
