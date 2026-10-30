"""Header normalisation, mapping suggestions, readers and value rules of the import workbench (LM-39, FG-PRD-12)."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.core.errors import ValidationFailed
from app.modules.imports.definitions import DEFINITIONS
from app.modules.imports.definitions.base import Issue, as_date, product_status
from app.modules.imports.definitions.media_master import location_key
from app.modules.imports.headers import analyse_headers, normalise_header, suggest_mapping
from app.modules.imports.readers import read_csv, read_xlsx


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Product Key", "product_key"),
        (" PRODUCT-KEY ", "product_key"),
        ("Unit Weight (g)", "unit_weight_g"),
        ("Plate 1 Size (mm)", "plate_1_size_mm"),
        ("﻿category", "category"),
        ("Ｃａｒｔｏｎ Qty", "carton_qty"),  # full-width letters fold through NFKC
        ("Sub-Category", "sub_category"),
    ],
)
def test_normalise_header(header: str, expected: str) -> None:
    assert normalise_header(header) == expected


def test_normalisation_aliases_and_collisions() -> None:
    infos, collisions = analyse_headers(["Product Key", "product-key", "Sub Category", "Plate 1 Size (mm)", "Mystery"])
    assert collisions == {"product_key": ["Product Key", "product-key"]}
    products = suggest_mapping(infos, DEFINITIONS["products_master"].field_spellings(), collisions)
    assert products["Product Key"] is None and products["product-key"] is None  # explicit mapping needed
    assert products["Sub Category"] == "subcategory" and products["Mystery"] is None
    specs = suggest_mapping(infos, DEFINITIONS["specifications"].field_spellings(), collisions)
    assert specs["Plate 1 Size (mm)"] == "plate1_size_mm"


def test_csv_reader_keeps_identifiers_as_text_and_row_numbers() -> None:
    data = "﻿product_key;decor_no;name\nLK-1;0120;Oak\n\nLK-2;120.0;=1+1\n".encode()
    sheet = read_csv(data)
    assert sheet.delimiter == ";" and sheet.encoding == "utf-8-sig"
    assert sheet.rows == [(2, {"product_key": "LK-1", "decor_no": "0120", "name": "Oak"}),
                          (4, {"product_key": "LK-2", "decor_no": "120.0", "name": "=1+1"})]


def test_csv_reader_falls_back_to_cp1252_with_a_note() -> None:
    sheet = read_csv("product_key,name\nLK-1,Caf\xe9\n".encode("cp1252"))
    assert sheet.rows[0][1]["name"] == "Café" and sheet.notes[0][2] == "ENCODING_FALLBACK"


def test_xlsx_reader_numbers_text_and_zero_formats() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["product_key", "decor_no", "padded", "width", "price"])
    ws.append(["LK-1", "0120", 120, 120.0, 24.5])
    ws["C2"].number_format = "0000"
    buf = io.BytesIO()
    wb.save(buf)
    sheet = read_xlsx(buf.getvalue())
    assert sheet.rows[0] == (2, {"product_key": "LK-1", "decor_no": "0120", "padded": "0120", "width": "120",
                                 "price": "24.5"})


def test_xlsx_zip_guard_rejects_non_workbooks() -> None:
    with pytest.raises(ValidationFailed):
        read_xlsx(b"PK\x03\x04 not really a zip")


def test_status_aliases() -> None:
    issues: list[Issue] = []
    assert product_status("In Dev", issues) == "under_development"
    assert product_status("Under Development", issues) == "under_development"
    assert product_status("ACTIVE", issues) == "active"
    assert product_status("sold out", issues) is None and issues[0].code == "STATUS_UNKNOWN"


def test_dates_follow_the_order_and_reject_garbage() -> None:
    issues: list[Issue] = []
    assert str(as_date("03/04/2026", "valid_from", issues)) == "2026-04-03"
    assert str(as_date("03/04/2026", "valid_from", issues, order="MDY")) == "2026-03-04"
    assert as_date("31/31/2026", "valid_from", issues) is None and issues[-1].code == "NOT_A_DATE"


def test_media_location_keys() -> None:
    assert location_key("https://drive.google.com/file/d/AbC_1/view?usp=sharing") == "gdrive:AbC_1"
    assert location_key("https://drive.google.com/open?id=AbC_1") == "gdrive:AbC_1"
    assert location_key("HTTPS://Example.COM/a/B.jpg#frag") == "https://example.com/a/B.jpg"
    assert location_key("images\\oak\\front.jpg") == "images/oak/front.jpg"
