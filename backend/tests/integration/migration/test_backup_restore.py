"""Scenario M (backup part, ADR-048): ``lk backup create`` dumps a committed database through the compose container
with a snapshot-consistent manifest, and the restore rehearsal restores it into a temporary database, passes every
verification query, drops the temporary database and records the outcome. Needs Docker and the ``lk-postgres``
container (skipped otherwise)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.modules.migration.backup import BackupError, check_container, create_backup, restore_rehearsal
from app.modules.migration.models import BackupRecord
from app.platform.authz.context import ActorContext
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from tests.support import create_company

pytestmark = [pytest.mark.db, pytest.mark.committed]


@pytest.fixture
def backup_env(committed_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    try:
        check_container()
    except BackupError as exc:
        pytest.skip(f"compose PostgreSQL container unavailable: {exc.code}")
    storage = tmp_path / "storage"
    (storage / "ab").mkdir(parents=True)
    (storage / "ab" / "file.bin").write_bytes(b"stored bytes")
    monkeypatch.setenv("LK_STORAGE_DIR", str(storage))
    monkeypatch.setenv("LK_STORAGE_BACKEND", "local_fs")
    monkeypatch.setenv("LK_BACKUP_DIR", str(tmp_path / "backups"))
    reset_settings_cache()
    yield tmp_path / "backups"
    reset_settings_cache()


def test_backup_then_restore_rehearsal_round_trip(backup_env: Path, committed_db: str) -> None:
    company_id, _branch = create_company()
    result = create_backup()
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert result.status == "completed" and manifest["database"] == committed_db
    assert manifest["dump"]["bytes"] > 0 and len(manifest["dump"]["sha256"]) == 64
    assert manifest["tables"]["company"] >= 1 and manifest["alembic_revision"]
    assert manifest["storage"]["files"] == 1 and manifest["storage"]["entries"][0]["path"] == "ab/file.bin"
    assert "migration_backup" in manifest["rls_forced_tables"]

    rehearsal = restore_rehearsal(result.backup_id)
    checks = {c["check"]: c for c in rehearsal.checks}
    assert rehearsal.outcome == "passed", rehearsal.checks
    assert set(checks) >= {"dump_checksum", "pg_restore", "alembic_revision", "tables_present", "row_counts",
                           "rls_forced", "rls_fails_closed", "storage_checksums", "temporary_database_dropped"}
    assert rehearsal.database.startswith("lk_rehearsal_") and rehearsal.database != committed_db
    assert list(result.directory.glob("rehearsal-*.json"))

    with UnitOfWork(ActorContext.system(company_id, reason="test")) as uow:
        row = uow.session.scalar(select(BackupRecord).where(BackupRecord.backup_id == result.backup_id))
        assert row is not None and row.status == "completed" and row.rehearsal_outcome == "passed"
        assert row.dump_sha256 == manifest["dump"]["sha256"] and row.storage_files == 1
        events = set(uow.session.scalars(select(DomainEvent.event_type).where(DomainEvent.company_id == company_id)))
        assert {"system.backup.completed", "system.restore_rehearsal.completed"} <= events


def test_a_tampered_dump_fails_the_rehearsal_without_restoring(backup_env: Path, committed_db: str) -> None:
    create_company()
    result = create_backup()
    dump = result.directory / "db.dump"
    dump.write_bytes(dump.read_bytes() + b"tampered")
    rehearsal = restore_rehearsal(result.backup_id)
    assert rehearsal.outcome == "failed" and rehearsal.checks[0]["check"] == "dump_checksum"
    assert not rehearsal.checks[0]["passed"] and len(rehearsal.checks) == 1


def test_unknown_backups_are_refused(backup_env: Path) -> None:
    with pytest.raises(BackupError) as bad:
        restore_rehearsal("../../etc")
    assert bad.value.code == "bad_backup_id"
    with pytest.raises(BackupError) as missing:
        restore_rehearsal("bk-20260101T000000Z-abcdef")
    assert missing.value.code == "backup_not_found"
