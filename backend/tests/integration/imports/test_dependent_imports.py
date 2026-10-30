"""Product-dependent imports (LM-30..34, FG-PKG-01..04, FG-MED-03/04, FG-LKP, FG-PRC-04/16, BUG-09/12, SCN-G1/G2):
packaging alias conflicts with row numbers, orphans quarantined then released by a recheck, specifications with
dimension parsing, pricing through the pricing services, media without duplicates, lookups upserted and exported."""

from __future__ import annotations

import pytest

from app.core.errors import Conflict
from app.modules.catalogue import lookups
from app.modules.catalogue import media as catalogue_media
from app.modules.catalogue import service as catalogue
from app.modules.imports import service
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.imports.helpers import admin, commit, csv_bytes, issues, rows, run, start, validate

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("media_storage")]

OAK, MAPLE = keys.PRODUCTS.OAK_TRAY, keys.PRODUCTS.MAPLE_TRIVET


def test_alias_conflict_quarantined_with_row_numbers(world: World) -> None:
    data = csv_bytes(
        ["product_key", "carton_qty", "master_carton_qty", "unit_weight_g", "unit_weight_kg", "unit_packing_type"],
        [[OAK, 24, 12, "", "", ""],               # row 2: carton conflict
         [MAPLE, "", "", 450, 0.5, ""],            # row 3: weight conflict
         [keys.PRODUCTS.ASH_BOARD, 24, "24.0", 450, 0.45, "Poly bag"]],  # row 4: consistent pairs
    )
    job = start(world, "packaging", data)
    job = validate(world, job.id)
    conflicts = [i for i in issues(world, job.id, code="ALIAS_CONFLICT")]
    assert sorted(i.row_number for i in conflicts) == [2, 3]
    assert {i.field for i in conflicts} == {"carton_qty", "unit_weight_g"}
    assert any("master_carton_qty=12" in (i.raw_value or "") and "carton_qty=24" in (i.raw_value or "") for i in conflicts)
    job = commit(world, job.id)
    assert job.counts["committed"] == 1 and job.counts["quarantined"] == 2
    ash = catalogue.get_product_by_key(admin(world), keys.PRODUCTS.ASH_BOARD)
    assert ash.packaging is not None and ash.packaging.carton_qty == 24 and str(ash.packaging.unit_weight_g) == "450"
    assert ash.packaging.alias_provenance and "carton_qty" in ash.packaging.alias_provenance
    oak = catalogue.get_product_by_key(admin(world), OAK)
    assert oak.packaging is not None and oak.packaging.carton_qty == 24  # untouched by the quarantined row


def test_orphan_rows_quarantined_then_released_by_recheck(world: World) -> None:
    data = csv_bytes(["product_key", "carton_qty", "packing_type"], [["NEW-001", 10, "Box"], [OAK, 24, "Poly bag"]])
    job = run(world, "packaging", data)
    assert job.counts["quarantined"] == 1
    assert [i.code for i in issues(world, job.id, severity="quarantine")] == ["ORPHAN_PRODUCT"]
    run(world, "products_master", csv_bytes(["product_key", "category"],
                                            [["NEW-001", keys.TAXONOMY_NAMES[keys.CATEGORIES.SERVEWARE]]]))
    with UnitOfWork(admin(world)) as uow:
        child = service.recheck_quarantine(uow, job.id)
    from tests.support import drain

    drain()
    child = service.get_job(admin(world), child.id)
    assert child.parent_job_id == job.id and child.counts.get("valid") == 1
    child = commit(world, child.id)
    assert child.counts["committed"] == 1
    assert catalogue.get_product_by_key(admin(world), "NEW-001").packaging.carton_qty == 10  # type: ignore[union-attr]
    parent_rows = rows(world, job.id, status="released")
    assert [r.row_number for r in parent_rows] == [2]
    with UnitOfWork(admin(world)) as uow, pytest.raises(Conflict):  # nothing left to recheck: committed exactly once
        service.recheck_quarantine(uow, job.id)


def test_orphans_quarantined_and_dimensions_parsed(world: World) -> None:
    data = csv_bytes(
        ["product_key", "length_mm", "width_mm", "thickness_mm", "Plate 1 Size (mm)", "working_size_mm", "type"],
        [[OAK, "45 cm", 300, "0.80", "Ø 300", "300-350", "Tray"], ["GHOST-1", 100, 100, 12, "", "", ""]],
    )
    job = run(world, "specifications", data)
    assert job.counts["committed"] == 1 and job.counts["quarantined"] == 1
    oak = catalogue.get_product_by_key(admin(world), OAK)
    assert oak.specification is not None and str(oak.specification.length_mm) == "450"
    assert str(oak.specification.thickness_mm) == "0.8" and oak.specification.type == "Tray"
    dims = {d.kind.value: d for d in oak.dimensions}
    assert str(dims["plate_1_size"].diameter_mm) == "300" and dims["working_size"].parse_status.value == "unparsed"
    assert "DIMENSION_UNPARSED" in {i.code for i in issues(world, job.id)}


def test_orphans_quarantined_and_price_alias_conflict(world: World) -> None:
    data = csv_bytes(
        ["product_key", "price_type", "currency", "price", "final_price", "unit_of_sale"],
        [[OAK, "export", "EUR", "26", "", "pcs"],        # row 2: new draft list STD-EXPORT-EUR
         [MAPLE, "export", "EUR", "10", "11", "pcs"],    # row 3: PRICE_AMBIGUOUS
         ["NOPE-1", "export", "EUR", "5", "", "pcs"],    # row 4: orphan
         [OAK, "", "", "30", "", "pcs"],                  # row 5: blank type/currency
         [OAK, "sample", "USD", "40", "", "pcs"]],       # row 6: new draft list STD-SAMPLE-USD
    )
    job = start(world, "pricing", data)
    job = validate(world, job.id)
    by_row = {r.row_number: r for r in rows(world, job.id)}
    assert "PRICE_AMBIGUOUS" in by_row[3].issue_codes and by_row[3].status == "quarantined"
    assert "ORPHAN_PRODUCT" in by_row[4].issue_codes
    assert {"PRICE_TYPE_MISSING", "CURRENCY_MISSING"} <= set(by_row[5].issue_codes)
    assert by_row[6].action == "insert"
    job = commit(world, job.id)
    by_row = {r.row_number: r for r in rows(world, job.id)}
    assert by_row[6].status == "committed"
    from app.modules.pricing import service as pricing

    with UnitOfWork(admin(world)) as uow:
        new_list = pricing.find_price_list(uow, "STD-SAMPLE-USD")
        assert new_list is not None and new_list.status == "draft" and new_list.source_kind == "import"
    # row 2: the seeded EUR list is not a STD-* list, so the import creates its own draft standard list
    assert by_row[2].status == "committed"


def test_reimport_creates_no_duplicate_media(world: World) -> None:
    data = csv_bytes(
        ["product_key", "media_type", "file_url", "drive_link", "file_name", "original_filename"],
        [[OAK, "image", "https://drive.google.com/file/d/Abc123/view", "https://drive.google.com/open?id=Abc123",
          "front.jpg", "IMG_001.jpg"],
         [OAK, "", "", "", "", ""]],
    )
    first = run(world, "media", data)
    assert first.counts["committed"] == 1 and first.counts["rejected"] == 1  # row 3 has no location
    codes = {i.code for i in issues(world, first.id)}
    assert {"FILENAME_DIFFERS", "LOCATION_MISSING"} <= codes
    second = run(world, "media", data)
    assert second.counts.get("unchanged") == 1 and "committed" not in second.counts
    groups = catalogue_media.list_media(admin(world), world.ref("OAK_TRAY"))
    assert len(groups.image) == 1
    assert groups.image[0].ingest_status == "external_only" and groups.image[0].source_url_key == "gdrive:Abc123"
    assert groups.image[0].file_name == "front.jpg" and groups.image[0].original_filename == "IMG_001.jpg"


def test_location_alias_group_conflict_quarantined(world: World) -> None:
    data = csv_bytes(["product_key", "media_type", "file_url", "file_path"],
                     [[OAK, "document", "https://example.com/a.pdf", "docs/b.pdf"]])
    job = run(world, "media", data)
    assert job.counts["quarantined"] == 1 and issues(world, job.id, code="ALIAS_CONFLICT")[0].row_number == 2


def test_filename_pair_kept(world: World) -> None:
    data = csv_bytes(["product_key", "media_type", "storage_path", "original_filename"],
                     [[OAK, "document", "legacy/spec.pdf", "Spec sheet.pdf"]])
    run(world, "media", data)
    doc = catalogue_media.list_media(admin(world), world.ref("OAK_TRAY")).document[0]
    assert doc.file_name == "Spec sheet.pdf" and doc.original_filename == "Spec sheet.pdf"
    assert doc.source_kind == "import_reference" and doc.content_url is None


def test_upsert_idempotent_browse_and_export(world: World) -> None:
    data = csv_bytes(["lookup_type", "key_1", "key_2", "value_1", "notes"],
                     [["finish", "MT", "", "Matte", "=cmd"], ["finish", "GL", "", "Gloss", ""], ["edge", "PVC", "2mm", "x", ""]])
    first = run(world, "lookup_reference", data)
    assert first.counts["committed"] == 3
    again = run(world, "lookup_reference", data)
    assert again.counts.get("unchanged") == 3
    changed = csv_bytes(["lookup_type", "key_1", "key_2", "value_1"], [["finish", "MT", "", "Matt"]])
    assert run(world, "lookup_reference", changed).counts["committed"] == 1
    page = lookups.list_lookups(admin(world), lookup_type="finish")
    assert page.total == 2 and {r.value_1 for r in page.items} == {"Matt", "Gloss"}
    assert [t.lookup_type for t in lookups.lookup_types(admin(world))] == ["edge", "finish"]
    exported = lookups.export_lookups_csv(admin(world)).decode("utf-8")
    assert exported.startswith("﻿") and "\"'=cmd\"" in exported  # formula guard on export
