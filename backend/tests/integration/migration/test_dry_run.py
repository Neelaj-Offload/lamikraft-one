"""Scenario M (migration part): the dry run over the synthetic legacy export reconciles every row and the historical
totals by currency, quarantines every deliberate conflict with its original values, writes no domain data (no stock
from legacy challans), reruns without duplicating its ID map or candidates, and records unreadable exports as failed
runs."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.modules.migration.dry_run import run_dry_run
from app.modules.migration.models import MigrationIdMap, MigrationIssue, MigrationRun, PartyCandidate
from app.modules.migration.sources import SourceError
from app.platform.uow import UnitOfWork
from tests.integration.catalogue.world import World
from tests.integration.migration.helpers import FIXTURE, operator

pytestmark = pytest.mark.db

EXPECTED = {  # entity: (rows, accepted, quarantined, rejected, exact repeats)
    "category_taxonomy": (5, 4, 0, 0, 1),
    "products_master": (10, 4, 5, 1, 0),
    "pricing": (8, 3, 5, 0, 0),
    "packaging": (4, 2, 2, 0, 0),
    "specifications": (3, 2, 1, 0, 0),
    "media": (6, 5, 1, 0, 0),
    "lookup_reference": (2, 2, 0, 0, 0),
    "users": (6, 3, 3, 0, 0),
    "quote_settings": (1, 1, 0, 0, 0),
    "custom_products": (4, 2, 2, 0, 0),
    "quotes": (8, 4, 4, 0, 0),
    "quote_lines": (9, 7, 2, 0, 0),
    "quote_revisions": (4, 2, 1, 1, 0),
    "grain_locked_decors": (3, 2, 0, 0, 1),
    "delivery_challans": (4, 2, 2, 0, 0),
    "delivery_challan_lines": (4, 3, 1, 0, 0),
    "opening_balances": (6, 2, 3, 1, 0),
}


def _count(world: World, model: type) -> int:
    with UnitOfWork(operator(world)) as uow:
        return int(uow.session.scalar(select(func.count()).select_from(model)) or 0)


def _issues(world: World, run_id: object, **where: str) -> list[MigrationIssue]:
    with UnitOfWork(operator(world)) as uow:
        stmt = select(MigrationIssue).where(MigrationIssue.run_id == run_id)
        for k, v in where.items():
            stmt = stmt.where(getattr(MigrationIssue, k) == v)
        return list(uow.session.scalars(stmt))


def _domain_counts(world: World) -> dict[str, int]:
    from app.modules.catalogue.models import Product, ProductMedia
    from app.modules.challans.models import Challan
    from app.modules.parties.models import Party
    from app.modules.pricing.models import PriceListItem
    from app.modules.sales.models import Quote

    return {m.__tablename__: _count(world, m) for m in (Product, ProductMedia, PriceListItem, Quote, Challan, Party)}


def test_dry_run_reconciles_every_row_and_the_totals_by_currency(world: World, export_dir: Path) -> None:
    before = _domain_counts(world)
    result = run_dry_run(operator(world), export_dir)
    report = result.report
    assert result.status == "completed" and report["reconciled"] is True
    for entity, (rows, accepted, quarantined, rejected, repeats) in EXPECTED.items():
        c = report["entities"][entity]
        assert (c["source_rows"], c["accepted"], c["quarantined"], c["rejected"], c["duplicate_identical"]) == (
            rows, accepted, quarantined, rejected, repeats), entity
        assert c["balanced"], entity
    totals = report["quotes"]["totals_by_currency"]
    assert totals["EUR"]["source_quotes"] == 5 and totals["EUR"]["source_total"] == "5750.00"
    assert totals["EUR"]["accepted_total"] == "4250.00" and totals["EUR"]["recomputed_total"] == "3850.00"
    assert totals["EUR"]["discrepancy_total"] == "400.00"
    assert totals["GBP"]["accepted_total"] == "280.00" and totals["GBP"]["recomputed_total"] == "270.00"
    assert totals["INR"]["accepted_total"] == totals["INR"]["recomputed_total"] == "10500.00"
    numbers = {d["quote_number"]: d for d in report["quotes"]["discrepancies"]}
    assert numbers["LK-QT-2025-0002"]["difference"] == "400.00" and set(numbers) == {"LK-QT-2025-0002", "LK-QT-2025-0003"}
    # file hashes: every source file and every reachable media file, with the export digest
    files = {f["file"]: f for f in report["source"]["files"]}
    assert files["packaging.xlsx"]["format"] == "xlsx" and files["quotes.json"]["rows"] == 8
    assert all(len(f["sha256"]) == 64 for f in files.values()) and len(report["source"]["digest"]) == 64
    assert report["source"]["ignored_files"] == ["notes.txt"] and report["source"]["authorised"] is True
    assert {m["path"] for m in report["media"]["files"]} == {"media/oak_tray.png", "media/walnut_board.png"}
    assert report["links"]["quote_lines->quotes"] == {"linked": 7, "orphans": 1}
    assert report["links"]["pricing->products"] == {"linked": 3, "orphans": 1}
    # legacy challans are documents only; nothing is written to the domain by a dry run
    assert report["challans"] == {"documents": 2, "lines": 3, "inventory_effect": "none", "stock_movements": 0}
    assert _domain_counts(world) == before


def test_every_deliberate_conflict_is_quarantined_with_its_original_values(world: World, export_dir: Path) -> None:
    result = run_dry_run(operator(world), export_dir)
    codes = {(i.entity, i.code, i.severity) for i in _issues(world, result.run_id)}
    for expected in [
        ("packaging", "ALIAS_CONFLICT", "quarantine"),
        ("pricing", "PRICE_AMBIGUOUS", "quarantine"),
        ("pricing", "CURRENCY_MISSING", "quarantine"),
        ("pricing", "ORPHAN_PRODUCT", "quarantine"),
        ("products_master", "DUPLICATE_IDENTITY", "quarantine"),
        ("products_master", "KEY_CASE_COLLISION", "quarantine"),
        ("products_master", "CATEGORY_NOT_FOUND", "quarantine"),
        ("products_master", "DISPLAY_SKU_SHARED", "info"),
        ("products_master", "DECOR_FLOAT_ARTEFACT_NORMALISED", "warning"),
        ("media", "MEDIA_INACCESSIBLE", "warning"),
        ("media", "MEDIA_NOT_FETCHED", "warning"),
        ("media", "MEDIA_PATH_OUTSIDE_EXPORT", "quarantine"),
        ("users", "DUPLICATE_IDENTITY", "quarantine"),
        ("users", "ROLE_UNKNOWN", "quarantine"),
        ("users", "CREDENTIAL_DROPPED", "info"),
        ("quotes", "DUPLICATE_IDENTITY", "quarantine"),
        ("quotes", "STATUS_UNKNOWN", "quarantine"),
        ("quotes", "CURRENCY_MISSING", "quarantine"),
        ("quotes", "LEGACY_TOTAL_DISCREPANCY", "warning"),
        ("quotes", "LINE_COUNT_MISMATCH", "warning"),
        ("quotes", "ATTRIBUTION_NAME_ONLY", "info"),
        ("quote_lines", "ORPHAN_LINE", "quarantine"),
        ("quote_lines", "LINE_TYPE_UNKNOWN", "quarantine"),
        ("quote_lines", "LINE_TOTAL_DISCREPANCY", "warning"),
        ("quote_lines", "LINE_PRODUCT_UNRESOLVED", "warning"),
        ("quote_revisions", "ORPHAN_REVISION", "quarantine"),
        ("quote_revisions", "SNAPSHOT_UNREADABLE", "error"),
        ("custom_products", "DUPLICATE_IDENTITY", "quarantine"),
        ("custom_products", "BASE_PRODUCT_UNRESOLVED", "warning"),
        ("delivery_challans", "DUPLICATE_IDENTITY", "quarantine"),
        ("delivery_challans", "STATUS_UNVALIDATED", "warning"),
        ("delivery_challan_lines", "ORPHAN_LINE", "quarantine"),
        ("opening_balances", "DUPLICATE_LOCATION", "quarantine"),
        ("opening_balances", "NEGATIVE_QUANTITY", "error"),
        ("grain_locked_decors", "DUPLICATE_IDENTICAL", "info"),
    ]:
        assert expected in codes, expected
    conflict = next(i for i in _issues(world, result.run_id, code="ALIAS_CONFLICT") if i.source_key == "LKX-1002")
    assert conflict.raw is not None and conflict.raw["carton_qty"] == "12" and conflict.raw["master_carton_qty"] == "10"
    assert conflict.source_file == "packaging.xlsx" and conflict.row_number == 3
    ambiguous = [i for i in _issues(world, result.run_id, code="PRICE_AMBIGUOUS") if i.source_key == "LKX-1003|export|EUR"]
    assert sorted(i.raw["price"] for i in ambiguous if i.raw) == ["14.00", "14.50"]
    # legacy credentials never leave the export: not in issues, not in the report
    every_raw = json.dumps([i.raw for i in _issues(world, result.run_id)])
    assert "password_hash" not in every_raw and "$2b$" not in every_raw
    assert "$2b$" not in json.dumps(result.report)


def test_rerun_reuses_the_id_map_and_candidates_without_duplication(world: World, export_dir: Path) -> None:
    first = run_dry_run(operator(world), export_dir)
    maps, candidates = _count(world, MigrationIdMap), _count(world, PartyCandidate)
    assert first.report["id_maps"]["new"] == maps == first.report["id_maps"]["total"]
    second = run_dry_run(operator(world), export_dir)
    assert second.report["id_maps"] == {"total": maps, "new": 0, "changed": 0, "unchanged": maps,
                                        "status_changed": 0, "missing_from_export": 0}
    assert _count(world, MigrationIdMap) == maps and _count(world, PartyCandidate) == candidates
    assert _count(world, MigrationRun) == 2 and second.report["source"]["digest"] == first.report["source"]["digest"]
    # a corrected export: the price conflict resolved (the 14.50 row removed) -> the key is planned, not quarantined
    pricing = export_dir / "pricing.csv"
    pricing.write_text(pricing.read_text(encoding="utf-8").replace(
        'LKX-1003,export,EUR,14.50,,pcs,,,second EUR export price\n', ''), encoding="utf-8")
    third = run_dry_run(operator(world), export_dir)
    assert third.report["entities"]["pricing"]["accepted"] == 4
    assert third.report["id_maps"]["status_changed"] == 1 and third.report["id_maps"]["new"] == 0
    assert _count(world, MigrationIdMap) == maps
    with UnitOfWork(operator(world)) as uow:
        row = uow.session.scalar(select(MigrationIdMap).where(MigrationIdMap.source_entity == "pricing",
                                                              MigrationIdMap.source_key == "LKX-1003|export|EUR"))
        assert row is not None and row.status == "planned" and row.first_run_id == first.run_id
        assert row.last_run_id == third.run_id


def test_party_candidates_are_suggested_never_merged(world: World, export_dir: Path) -> None:
    from app.modules.parties.models import Party

    parties_before = _count(world, Party)
    run_dry_run(operator(world), export_dir)
    with UnitOfWork(operator(world)) as uow:
        rows = {(c.name_key, c.country_key): c for c in uow.session.scalars(select(PartyCandidate))}
        nordhaus = rows[("nordhaus", "DE")]
        thornbury = rows[("thornbury kitchens", "GB")]
        assert nordhaus.occurrences == 2 and {v["name"] for v in nordhaus.variants} == {"Nordhaus GmbH", "NORDHAUS GMBH."}
        assert nordhaus.match_kind == "name_tokens" and nordhaus.suggested_party_id == world.ref("NORDHAUS")
        assert thornbury.match_kind == "exact_name" and thornbury.score == Decimal("1.000")
        assert ("kaveri exports", "IN") in rows and rows[("kaveri exports", "IN")].suggested_party_id is None
        assert all(c.status == "proposed" and c.linked_party_id is None for c in rows.values())
    assert _count(world, Party) == parties_before


def test_unreadable_exports_stop_before_analysis_and_are_recorded(world: World, export_dir: Path) -> None:
    (export_dir / "products.json").write_text("[]", encoding="utf-8")  # a second file for products_master
    with pytest.raises(SourceError) as caught:
        run_dry_run(operator(world), export_dir)
    assert caught.value.code == "duplicate_source_file"
    with UnitOfWork(operator(world)) as uow:
        run = uow.session.scalar(select(MigrationRun))
        assert run is not None and run.status == "failed" and run.error_code == "duplicate_source_file"


def test_fixture_is_the_committed_synthetic_export() -> None:
    manifest = json.loads((FIXTURE / "export_manifest.json").read_text(encoding="utf-8"))
    assert "Synthetic" in manifest["authorised_by"]
