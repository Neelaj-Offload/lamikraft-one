"""Scenario M (apply): refused without the backup flag, a verified backup or an authorised export; writes the
catalogue through the import workbench, stores reachable media with checksums, archives legacy documents exactly,
creates no stock and no quotes or challans from legacy documents, and applies twice without duplicating anything.
The opening-balance batch is staged, approved by a second person and refused at posting until inventory exists."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.errors import ServiceUnavailable
from app.modules.migration import opening
from app.modules.migration.apply import ApplyRefused, run_apply
from app.modules.migration.dry_run import run_dry_run
from app.modules.migration.models import (
    BackupRecord,
    LegacyRecord,
    MigrationIdMap,
    MigrationRun,
    OpeningBatch,
)
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.migration.helpers import operator

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]


def _verified_backup(world: World, *, hours_ago: float = 1, outcome: str = "passed") -> str:
    from app.core.clock import get_clock
    from app.core.config import get_settings

    backup_id = f"bk-20261012T000000Z-{uuid.uuid4().hex[:6]}"
    with UnitOfWork(ActorContext.system(world.company_id, reason="test")) as uow:
        uow.add(BackupRecord(backup_id=backup_id, status="completed", database=get_settings().db_name,
                             started_at=get_clock().now() - timedelta(hours=hours_ago), rehearsal_outcome=outcome,
                             rehearsed_at=get_clock().now(), rehearsal_checks=[]))
    return backup_id


def _count(world: World, model: type, *where: object) -> int:
    with UnitOfWork(operator(world)) as uow:
        return int(uow.session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_apply_is_refused_without_its_guards(world: World, export_dir: Path) -> None:
    actor = operator(world)
    with pytest.raises(ApplyRefused) as flag:
        run_apply(actor, export_dir, i_have_a_backup=False)
    assert flag.value.code == "backup_flag_required"
    with pytest.raises(ApplyRefused) as none:
        run_apply(actor, export_dir, i_have_a_backup=True)
    assert none.value.code == "no_verified_backup"
    _verified_backup(world, hours_ago=30)  # too old
    _verified_backup(world, outcome="failed")  # rehearsal failed
    with pytest.raises(ApplyRefused) as stale:
        run_apply(actor, export_dir, i_have_a_backup=True)
    assert stale.value.code == "no_verified_backup"
    _verified_backup(world)
    (export_dir / "export_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ApplyRefused) as unauthorised:
        run_apply(actor, export_dir, i_have_a_backup=True)
    assert unauthorised.value.code == "export_not_authorised"
    sales = world.actor(keys.USERS.MEERA)
    with pytest.raises(ApplyRefused) as denied:
        run_apply(sales, export_dir, i_have_a_backup=True)
    assert denied.value.code == "permission_denied"
    assert _count(world, MigrationRun) == 0  # nothing ran


def test_apply_writes_through_the_workbench_and_reruns_without_duplication(world: World, export_dir: Path) -> None:
    from app.modules.catalogue.models import Product, ProductMedia
    from app.modules.challans.models import Challan
    from app.modules.imports.models import ImportJob
    from app.modules.sales.models import Quote

    backup_id = _verified_backup(world)
    quotes, challans = _count(world, Quote), _count(world, Challan)
    products = _count(world, Product)
    result = run_apply(operator(world), export_dir, i_have_a_backup=True)
    applied = result.report["apply"]
    assert result.status == "completed" and applied["backup_id"] == backup_id and applied["stock_movements"] == 0
    catalogue = applied["catalogue"]
    assert catalogue["products_master"]["job_status"] == "committed" and catalogue["products_master"]["rows"] == 4
    assert _count(world, Product) == products + 4
    keys_now = set(_product_keys(world))
    assert {"LKX-1001", "LKX-1002", "LKX-1003", "LKX-1008"} <= keys_now
    assert not ({"LKX-1004", "LKX-1005", "lkx-1005", "LKX-1006", "LKX-1007"} & keys_now)  # quarantined / rejected stay out
    assert catalogue["media"]["files_stored"] == 2
    assert _count(world, ProductMedia, ProductMedia.source_kind == "upload") >= 2
    # legacy documents archived exactly; no quote or challan rows and no stock
    assert _count(world, Quote) == quotes and _count(world, Challan) == challans
    with UnitOfWork(operator(world)) as uow:
        q2 = uow.session.scalar(select(LegacyRecord).where(LegacyRecord.source_entity == "quotes",
                                                           LegacyRecord.source_key == "q-2"))
        assert q2 is not None and q2.document_number == "LK-QT-2025-0002" and q2.has_discrepancy
        assert str(q2.legacy_total) == "2400.0000" and str(q2.recomputed_total) == "2000.0000"
        assert q2.payload["quote"]["total_amount"] == "2400.00" and len(q2.payload["lines"]) == 2
        assert q2.party_candidate_id is not None
        d1 = uow.session.scalar(select(LegacyRecord).where(LegacyRecord.source_entity == "delivery_challans",
                                                           LegacyRecord.source_key == "d-1"))
        assert d1 is not None and d1.payload["inventory_effect"] == "none" and len(d1.payload["lines"]) == 2
        user = uow.session.scalar(select(LegacyRecord).where(LegacyRecord.source_entity == "users",
                                                             LegacyRecord.source_key == "u-meera"))
        assert user is not None and "password_hash" not in json.dumps(user.payload)
        assert user.payload["planned_access"]["kind"] == "invitation"
        assert user.payload["planned_access"]["grant"] and user.payload["planned_access"]["revoke"]
        lines = uow.session.scalar(select(MigrationIdMap).where(MigrationIdMap.source_entity == "quote_lines",
                                                                MigrationIdMap.source_key == "l-3"))
        assert lines is not None and lines.status == "applied" and lines.target_id == q2.id
    records, jobs, maps = _count(world, LegacyRecord), _count(world, ImportJob), _count(world, MigrationIdMap)
    again = run_apply(operator(world), export_dir, i_have_a_backup=True)
    second = again.report["apply"]
    assert _count(world, LegacyRecord) == records and _count(world, MigrationIdMap) == maps
    assert _count(world, Product) == products + 4 and _count(world, ImportJob) == jobs  # nothing to import twice
    assert all("job_id" not in e for e in second["catalogue"].values())
    assert second["catalogue"]["products_master"]["skipped_already_applied"] == 4
    assert all(s.get("new", 0) == 0 for s in second["legacy_records"].values())


def _product_keys(world: World) -> list[str]:
    from app.modules.catalogue.models import Product

    with UnitOfWork(operator(world)) as uow:
        return list(uow.session.scalars(select(Product.product_key)))


def test_opening_balances_are_a_separate_second_person_batch(world: World, export_dir: Path) -> None:
    stager = operator(world)
    result = run_dry_run(stager, export_dir, keep_analysis=True)
    assert result.analysis is not None
    batch_id = opening.stage_batch(stager, result.analysis, result.run_id)
    assert batch_id is not None
    with UnitOfWork(stager) as uow:
        batch = uow.session.get(OpeningBatch, batch_id)
        assert batch is not None and batch.status == "staged" and batch.line_count == 2
        assert batch.quarantined_count == 3 and batch.totals == {"PCS": "52"}
        version = batch.version
    with pytest.raises(Exception) as same:
        opening.approve_batch(stager, batch_id, version)
    assert getattr(same.value, "code", "") == "approver_is_stager"
    second = world.actor(keys.USERS.SAHIL).with_(permissions={**world.actor(keys.USERS.SAHIL).permissions,
                                                              "migration.apply.execute": stager.scope_for(
                                                                  "migration.apply.execute")})
    approved = opening.approve_batch(second, batch_id, version)
    assert approved["status"] == "approved"
    with pytest.raises(ServiceUnavailable) as unavailable:
        opening.post_batch(second, batch_id, approved["version"])
    assert unavailable.value.code == "inventory_module_unavailable"
