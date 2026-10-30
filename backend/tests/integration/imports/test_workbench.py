"""The workbench mechanics (LM-35..38, UI-87/88, API-30..33, LP-04.3..04.9, BUG-12, SCN-G1): preview, validation
counts, the uncapped report, batched resumable commits, review-time staleness, rollback, history, scope and the
demo-only reset."""

from __future__ import annotations

import csv
import io

import pytest

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.modules.catalogue import lookups
from app.modules.catalogue import service as catalogue
from app.modules.catalogue.schemas import ProductUpdate
from app.modules.imports import demo_reset, engine, service
from app.modules.imports.schemas import CommitRequest, DemoResetRequest, MappingUpdate, RollbackRequest
from app.platform.authz.permissions import Scope
from app.platform.identity.errors import ReauthRequired
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World, build_personas
from tests.integration.imports.helpers import (
    admin,
    commit,
    csv_bytes,
    issues,
    remap,
    rows,
    run,
    start,
    validate,
)

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]

SERVEWARE = keys.TAXONOMY_NAMES[keys.CATEGORIES.SERVEWARE]


def test_preview_lists_duplicates_with_row_numbers(world: World) -> None:
    data = csv_bytes(
        ["Product Key", "Category", "Product Name", "Mystery Column"],
        [["DUP-1", SERVEWARE, "A", "x"], ["DUP-2", SERVEWARE, "B", ""], ["DUP-1", SERVEWARE, "A", "x"],
         ["DUP-2", SERVEWARE, "B changed", ""]] + [[f"P-{i}", SERVEWARE, "n", ""] for i in range(30)],
    )
    job = start(world, "products_master", data)
    preview = service.preview(admin(world), job.id)
    assert len(preview.rows) == 20 and preview.total_rows == 34 and preview.rows[0]["row_number"] == 2
    assert {h.original: h.field for h in preview.headers} == {
        "Product Key": "product_key", "Category": "category", "Product Name": "product_name", "Mystery Column": None
    }
    dups = {d.key: d for d in preview.duplicate_keys}
    assert dups["DUP-1"].row_numbers == [2, 4] and dups["DUP-1"].identical
    assert dups["DUP-2"].row_numbers == [3, 5] and not dups["DUP-2"].identical
    again = start(world, "products_master", data)
    assert service.preview(admin(world), again.id).same_file_jobs == [job.id]  # same sha256: warned, not blocked
    job = validate(world, job.id)
    by_row = {r.row_number: r.status for r in rows(world, job.id)}
    assert by_row[4] == "duplicate_identical" and by_row[2] == "valid"
    assert by_row[3] == by_row[5] == "quarantined"
    job = commit(world, job.id)
    extra = catalogue.get_product_by_key(admin(world), "DUP-1").provenance.source_extra
    assert extra == {"Mystery Column": "x"}  # unmapped columns are kept, never dropped


def test_all_issues_counts_and_orphans(world: World) -> None:
    data = csv_bytes(["product_key", "carton_qty", "inner_qty"],
                     [["ORPH-1", 10, ""], [keys.PRODUCTS.OAK_TRAY, "ten", ""], [keys.PRODUCTS.ASH_BOARD, 12, 3]])
    job = validate(world, start(world, "packaging", data).id)
    assert job.status == "validated"
    assert job.counts["quarantined"] == 1 and job.counts["rejected"] == 1 and job.counts["valid"] == 1
    assert job.counts["to_update"] == 1 and job.counts["issues_error"] >= 1
    with pytest.raises(Conflict) as exc, UnitOfWork(admin(world)) as uow:  # excluded rows need an acknowledgement
        service.request_commit(uow, job.id, CommitRequest(expected_version=job.version))
    assert exc.value.code == "excluded_rows_not_acknowledged"


def test_all_errors_reported_uncapped(world: World) -> None:
    data = csv_bytes(["product_key", "carton_qty"], [[f"K{i}", "=bad"] for i in range(250)])
    job = validate(world, start(world, "packaging", data).id)
    assert service.list_issues(admin(world), job.id, severity="error").total == 250
    report = service.issues_report_csv(admin(world), job.id).decode("utf-8")
    lines = list(csv.reader(io.StringIO(report.lstrip("﻿"))))
    assert lines[0] == ["row_number", "column", "field", "code", "severity", "message", "value"]
    errors = [r for r in lines[1:] if r[4] == "error"]
    assert sorted(int(r[0]) for r in errors) == list(range(2, 252))
    assert all(r[1] == "carton_qty" for r in errors)


def test_commit_batches_resume_after_failure(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    data = csv_bytes(["lookup_type", "key_1", "value_1"], [["bulk", f"K{i:04}", str(i)] for i in range(1100)])
    job = validate(world, start(world, "lookup_reference", data).id)
    real = engine.commit_batch
    calls = {"n": 0}

    def flaky(uow, job_id, row_ids):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected failure in batch 3")
        return real(uow, job_id, row_ids)

    monkeypatch.setattr(engine, "commit_batch", flaky)
    job = commit(world, job.id)
    assert job.status == "commit_failed" and job.error_code == "RuntimeError"
    assert job.counts["committed"] == 1000 and lookups.list_lookups(admin(world), lookup_type="bulk").total == 1000
    monkeypatch.setattr(engine, "commit_batch", real)
    job = commit(world, job.id)  # resume: committed rows are skipped
    assert job.status == "committed" and job.counts["committed"] == 1100
    assert lookups.list_lookups(admin(world), lookup_type="bulk").total == 1100


def test_target_changed_since_review_not_overwritten(world: World) -> None:
    oak = catalogue.get_product_by_key(admin(world), keys.PRODUCTS.OAK_TRAY)
    data = csv_bytes(["product_key", "category", "finish"], [[oak.product_key, SERVEWARE, "Imported finish"]])
    job = validate(world, start(world, "products_master", data).id)
    assert rows(world, job.id)[0].action == "update"
    with UnitOfWork(admin(world)) as uow:  # someone edits the product in the UI after the review
        catalogue.update_product(uow, oak.id, ProductUpdate(expected_version=oak.version, finish="UI finish"))
    job = commit(world, job.id)
    assert job.counts["quarantined"] == 1
    assert issues(world, job.id, code="TARGET_CHANGED_SINCE_REVIEW")[0].row_number == 2
    assert catalogue.get_product_by_key(admin(world), oak.product_key).finish == "UI finish"


def test_rollback_blocked_when_referenced_or_later_edited(world: World) -> None:
    run(world, "category_taxonomy", csv_bytes(["category", "subcategory"], [["Garden", "Planters"]]))
    data = csv_bytes(["product_key", "category", "finish"],
                     [["RB-1", "Garden", "Raw"], ["RB-2", "Garden", "Raw"], [keys.PRODUCTS.OAK_TRAY, SERVEWARE, "Oiled"]])
    job = run(world, "products_master", data)
    assert job.counts["committed"] == 3
    rb2 = catalogue.get_product_by_key(admin(world), "RB-2")
    with UnitOfWork(admin(world)) as uow:  # later work on an imported product
        catalogue.update_product(uow, rb2.id, ProductUpdate(expected_version=rb2.version, finish="Edited later"))
    with UnitOfWork(admin(world)) as uow:
        plan = service.rollback_plan(uow, job.id)
    by_entity = {i.entity_id: i for i in plan.items}
    assert by_entity[rb2.id].status == "blocked" and by_entity[rb2.id].reason_code == "LATER_EDIT"
    assert plan.reversible == 2 and plan.blocked == 1
    with pytest.raises(Conflict) as blocked, UnitOfWork(admin(world)) as uow:
        service.rollback(uow, job.id, RollbackRequest(mode="all", plan_hash=plan.plan_hash))
    assert blocked.value.code == "rollback_blocked"
    with pytest.raises(Conflict) as stale, UnitOfWork(admin(world)) as uow:
        service.rollback(uow, job.id, RollbackRequest(mode="reversible_only", plan_hash="0" * 64))
    assert stale.value.code == "rollback_plan_changed"
    with pytest.raises(ReauthRequired), UnitOfWork(world.actor(keys.USERS.PRIYA)) as uow:  # needs a fresh sign-in
        service.rollback(uow, job.id, RollbackRequest(mode="reversible_only", plan_hash=plan.plan_hash))
    with UnitOfWork(admin(world)) as uow:
        done = service.rollback(uow, job.id, RollbackRequest(mode="reversible_only", plan_hash=plan.plan_hash))
    assert done.status == "partially_rolled_back"
    with pytest.raises(NotFound):
        catalogue.get_product_by_key(admin(world), "RB-1")  # unreferenced insert removed
    assert catalogue.get_product_by_key(admin(world), "RB-2").finish == "Edited later"  # later work kept
    oak = catalogue.get_product_by_key(admin(world), keys.PRODUCTS.OAK_TRAY)
    assert oak.finish == "Matte lacquer"  # the import's field change restored


def test_rollback_unreferenced_import_restores_before_state(world: World) -> None:
    data = csv_bytes(["product_key", "carton_qty", "packing_type"], [[keys.PRODUCTS.WALNUT_BOARD, 6, "Crate"]])
    job = run(world, "packaging", data)
    walnut = catalogue.get_product_by_key(admin(world), keys.PRODUCTS.WALNUT_BOARD)
    assert walnut.packaging is not None and walnut.packaging.carton_qty == 6
    with UnitOfWork(admin(world)) as uow:
        plan = service.rollback_plan(uow, job.id)
    with UnitOfWork(admin(world)) as uow:
        done = service.rollback(uow, job.id, RollbackRequest(mode="all", plan_hash=plan.plan_hash))
    assert done.status == "rolled_back"
    restored = catalogue.get_product_by_key(admin(world), keys.PRODUCTS.WALNUT_BOARD)
    assert restored.packaging is None or restored.packaging.carton_qty is None


def test_jobs_mappings_hashes_durable(world: World) -> None:
    data = csv_bytes(["Key", "Cat"], [["H-1", SERVEWARE]])
    job = start(world, "products_master", data, "history.csv")
    job = remap(world, job.id, {"Key": "product_key", "Cat": "category"}, blank_cells="clear")
    assert job.mapping == {"Key": "product_key", "Cat": "category"} and job.options.blank_cells == "clear"
    with pytest.raises(ValidationFailed), UnitOfWork(admin(world)) as uow:  # a field mapped twice
        service.set_mapping(uow, job.id, MappingUpdate(expected_version=job.version,
                                                       mapping={"Key": "product_key", "Cat": "product_key"}))
    job = commit(world, validate(world, job.id).id)
    history = service.list_jobs(admin(world), import_type="products_master")  # type: ignore[arg-type]
    found = next(j for j in history.items if j.id == job.id)
    assert found.file_name == "history.csv" and len(found.file_sha256) == 64 and found.status == "committed"
    assert service.list_jobs(admin(world), status="committed").total >= 1
    detail = service.get_job(admin(world), job.id)
    assert detail.source_url.endswith(f"{detail.source_file_id}/content")
    assert service.list_changes(admin(world), job.id).items[0].entity_table == "catalogue_product"


def test_job_scope_and_permissions(world: World) -> None:
    job = start(world, "lookup_reference", csv_bytes(["lookup_type", "key_1"], [["t", "k"]]))
    with pytest.raises(Forbidden):  # sales hold no imports keys
        service.get_job(world.actor(keys.USERS.MEERA), job.id)
    other = build_personas()
    with pytest.raises(NotFound):  # another company: no existence leak
        service.get_job(other.actor(keys.USERS.PRIYA), job.id)
    base = admin(world)
    own_scope = base.with_(permissions={**base.permissions, "imports.job.read": Scope.OWN})
    assert service.get_job(own_scope, job.id).id == job.id  # own job visible at own scope


def test_pricing_supersedes_into_an_active_standard_list(world: World) -> None:
    from app.modules.pricing import service as pricing

    data = csv_bytes(["product_key", "price_type", "currency", "final_price", "unit_of_sale", "valid_from"],
                     [[keys.PRODUCTS.OAK_TRAY, "domestic", "INR", "1500", "pcs", "2026-01-01"]])
    run(world, "pricing", data)
    with UnitOfWork(admin(world)) as uow:
        pl = pricing.find_price_list(uow, "STD-DOMESTIC-INR")
        assert pl is not None
        pricing.activate_price_list(uow, pl.id)
    newer = csv_bytes(["product_key", "price_type", "currency", "final_price", "unit_of_sale"],
                      [[keys.PRODUCTS.OAK_TRAY, "domestic", "INR", "1650", "pcs"]])
    job = run(world, "pricing", newer)
    assert job.counts["committed"] == 1
    assert rows(world, job.id)[0].diff == {"unit_price": ["1500", "1650"]}
    with UnitOfWork(admin(world)) as uow:
        plan = service.rollback_plan(uow, job.id)
    assert plan.items[0].reason_code == "NOT_REVERSIBLE"  # price history is never erased by a rollback


def test_refused_for_non_demo_and_guarded(world: World) -> None:
    from app.platform.org.models import Company

    with UnitOfWork(admin(world)) as uow:  # the seeded world's prices reference its products
        preview = demo_reset.preview(uow)
    assert preview.is_demo and not preview.allowed and preview.reason_code == "demo_data_referenced"
    assert preview.blocking_references.get("pricing_price_list_item", 0) > 0
    fresh = build_personas()
    run(fresh, "lookup_reference", csv_bytes(["lookup_type", "key_1"], [["t", "k"]]))
    run(fresh, "category_taxonomy", csv_bytes(["category"], [["Only"]]))
    with UnitOfWork(admin(fresh)) as uow:
        preview = demo_reset.preview(uow)
    assert preview.allowed and preview.token and preview.counts["catalogue_category"] == 1
    with pytest.raises(ValidationFailed), UnitOfWork(admin(fresh)) as uow:
        demo_reset.execute(uow, DemoResetRequest(token=preview.token, phrase="reset"))
    with pytest.raises(Conflict), UnitOfWork(admin(fresh)) as uow:
        demo_reset.execute(uow, DemoResetRequest(token="1.forged-signature", phrase=preview.phrase))
    with pytest.raises(Forbidden), UnitOfWork(fresh.actor(keys.USERS.SAHIL)) as uow:
        demo_reset.preview(uow)
    with UnitOfWork(admin(fresh)) as uow:
        result = demo_reset.execute(uow, DemoResetRequest(token=preview.token, phrase=preview.phrase))
    assert result.deleted["catalogue_lookup_reference"] == 1
    assert catalogue.list_categories(admin(fresh), include_inactive=True) == []
    with UnitOfWork(admin(fresh)) as uow:  # a production company is refused even with the permission
        uow.session.query(Company).filter(Company.id == fresh.company_id).update({"is_demo": False})
    with pytest.raises(Forbidden), UnitOfWork(admin(fresh)) as uow:
        demo_reset.execute(uow, DemoResetRequest(token=preview.token, phrase=preview.phrase))
