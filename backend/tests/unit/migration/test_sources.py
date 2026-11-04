"""Legacy export readers: Extended JSON unwrapping, JSON / JSON Lines / CSV / XLSX rows, the export digest, media
path containment, and the candidate-name normaliser."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.migration.parties import country_code, normalise_name
from app.modules.migration.sources import SourceError, as_text, media_path, read_export, row_hash, unwrap

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "legacy_export"


def test_extended_json_wrappers_become_text() -> None:
    doc = {"_id": {"$oid": "65f1"}, "total": {"$numberDecimal": "1850.00"}, "at": {"$date": "2025-02-01T10:00:00Z"},
           "ms": {"$date": {"$numberLong": "0"}}, "n": 40, "f": 120.0, "g": 12.5, "ok": True,
           "nested": {"grant": ["edit_all_quotes"]}}
    out = unwrap(doc)
    assert out["_id"] == "65f1" and out["total"] == "1850.00" and out["at"] == "2025-02-01T10:00:00Z"
    assert out["ms"].startswith("1970-01-01T00:00:00") and out["n"] == "40" and out["f"] == "120.0"
    assert out["g"] == "12.5" and out["ok"] is True and out["nested"] == {"grant": ["edit_all_quotes"]}
    assert as_text(True) == "true" and as_text({"b": 1, "a": 2}) == '{"a":2,"b":1}' and as_text(None) is None


def test_fixture_export_reads_every_format() -> None:
    source = read_export(FIXTURE)
    assert source.files["packaging"].format == "xlsx" and len(source.rows("packaging")) == 4
    assert source.files["quote_lines"].format == "jsonl" and len(source.rows("quote_lines")) == 9
    assert source.files["custom_products"].format == "json" and len(source.rows("custom_products")) == 4
    assert source.files["quote_settings"].format == "json" and len(source.rows("quote_settings")) == 1
    taxonomy = source.rows("category_taxonomy")[0]
    assert taxonomy.values["sub_category"] == "Trays" and taxonomy.row_number == 2  # headers normalised
    packaging = source.rows("packaging")[0].values
    assert packaging["carton_qty"] == "24" and packaging["inner_pack_qty"] == ""
    assert source.ignored == ["notes.txt"] and source.authorised
    assert source.digest == read_export(FIXTURE).digest


def test_credentials_do_not_change_the_row_hash() -> None:
    assert row_hash({"id": "u1", "password_hash": "a"}) == row_hash({"id": "u1", "password_hash": "b"})


def test_two_files_for_one_collection_are_refused(tmp_path: Path) -> None:
    (tmp_path / "quotes.json").write_text("[]", encoding="utf-8")
    (tmp_path / "quotes.csv").write_text("id\n", encoding="utf-8")
    with pytest.raises(SourceError) as caught:
        read_export(tmp_path)
    assert caught.value.code == "duplicate_source_file"


def test_bad_json_and_empty_exports_are_refused(tmp_path: Path) -> None:
    with pytest.raises(SourceError) as empty:
        read_export(tmp_path)
    assert empty.value.code == "empty_export"
    (tmp_path / "users.jsonl").write_text('{"id": 1}\n{oops\n', encoding="utf-8")
    with pytest.raises(SourceError) as bad:
        read_export(tmp_path)
    assert bad.value.code == "bad_json"


def test_media_paths_stay_inside_the_export() -> None:
    assert media_path(FIXTURE, "oak_tray.png") == (FIXTURE / "media" / "oak_tray.png").resolve()
    assert media_path(FIXTURE, "media/oak_tray.png") == (FIXTURE / "media" / "oak_tray.png").resolve()
    for outside in ("../outside.pdf", "/etc/passwd", "C:/Windows/win.ini", "media/../../x.png", "..\\x.png"):
        assert media_path(FIXTURE, outside) is None, outside
    missing = media_path(FIXTURE, "missing.png")
    assert missing is not None and not missing.exists()


def test_candidate_names_drop_legal_forms_and_punctuation() -> None:
    assert normalise_name("NORDHAUS GMBH.") == normalise_name("Nordhaus GmbH") == "nordhaus"
    assert normalise_name("Berg & Co. AB") == "berg"
    assert normalise_name("Maison Lumière") == "maison lumière"
    assert country_code("germany") == "DE" and country_code("United Kingdom") == "GB" and country_code("se") == "SE"
    assert country_code("Atlantis") is None


def test_cleared_legacy_collections_are_reported_as_skipped(tmp_path: Path) -> None:
    """FG-MSC-01/02: ``revision_history`` and the legacy ``products`` collection are not migrated, only reported."""
    (tmp_path / "products_master.csv").write_text("product_key,category\nK1,Trays\n", encoding="utf-8")
    for name in ("products.json", "revision_history.json", "search_history.jsonl"):
        (tmp_path / name).write_text("[]", encoding="utf-8")
    source = read_export(tmp_path)
    assert set(source.files) == {"products_master"}
    assert source.ignored == ["products.json", "revision_history.json", "search_history.jsonl"]
