"""Parsing the leads spreadsheet (pure; no database). The workbook is built in the test with invented names."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from app.modules.parties import lead_import as li

HEADER = (
    "Create Date", "Company / Brand name", "Country", "Interested In", "Asign To", "Lead Action", "Lead Source",
    "Requierment", "Website",
    "Contact Person", "Designation", "Email Id", "Contact Number", "Source",
    "Contact Person (2)", "Designation(2)", "Email Id(2)", "Contact Number(2)", "Source",
    "Contact Person (3)", "Designation(3)", "Email Id(3)", "Contact Number(3)", "Source",
    "Contact Person (4)", "Designation(4)", "Email Id(4)", "Contact Number(4)", "Source",
    "Contact Person (5)", "Designation(5)", "Email Id(5)", "Contact Number(5)",
    "State", "City", "Pincode", "Address Line", "Address Line (2)",
)


def row(**cells: object) -> list[object]:
    values: list[object] = [None] * len(HEADER)
    names = {
        "date": 0, "company": 1, "country": 2, "interests": 3, "owner": 4, "action": 5, "source": 6, "req": 7,
        "web": 8, "c1": 9, "d1": 10, "e1": 11, "p1": 12, "s1": 13, "c2": 14, "d2": 15, "e2": 16, "p2": 17, "s2": 18,
        "c5": 29, "e5": 31, "state": 33, "city": 34, "pin": 35, "addr": 36, "addr2": 37,
    }
    for key, value in cells.items():
        values[names[key]] = value
    return values


def build(tmp_path: Path, *rows: list[object]) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(HEADER))
    for r in rows:
        ws.append(r)
    path = tmp_path / "leads.xlsx"
    wb.save(path)
    return path


def test_full_row_is_parsed(tmp_path: Path) -> None:
    sheet = li.parse_sheet(build(tmp_path, row(
        date="15-Jan-2026", company="  Harbour Kitchen Supply ", country="United States",
        interests="LAMIKRAFT, TABLE TOP", owner="Jane Example", action="NA", source="NRA CHICAGO 2026",
        req="CHOPPING BOARDS, PLATTERS", web="www.harbour.example", c1="ROSA GRANT", d1="BUYER",
        e1="rosa@harbour.example", p1="+1 555 0100", s1="NRA CHICAGO 2026", c2=None, e2="info@harbour.example",
        s2="WEBSITE", state="Texas", city="WACO", pin=76701, addr="600 MARY AVE",
    )))
    assert sheet.issues == []
    r = sheet.rows[0]
    assert (r.company, r.country_code, r.owner_name) == ("Harbour Kitchen Supply", "US", "Jane Example")
    assert r.interests == ["lamikraft", "table_top"] and r.lead_action is None
    assert r.first_contact_on == date(2026, 1, 15) and r.source_label == "NRA CHICAGO 2026"
    assert [c.name for c in r.contacts] == ["ROSA GRANT", "info@harbour.example"]
    assert r.contacts[0].job_title == "BUYER" and r.contacts[1].source == "WEBSITE"
    assert r.address == {"line1": "600 MARY AVE", "line2": None, "city": "WACO", "region": "Texas",
                         "postal_code": "76701"}


def test_rejections_and_warnings(tmp_path: Path) -> None:
    sheet = li.parse_sheet(build(
        tmp_path,
        row(company=None, country="Italy"),
        row(company="No Country Srl"),
        row(company="Atlantis Trading", country="Atlantis"),
        row(company="Typo Mail GmbH", country="Germany", c1="KARL", e1="karl@typo-mail", interests="LAMIKRAFT, SPOONS",
            date="sometime"),
    ))
    rejected = [(i.row_no, i.message) for i in sheet.issues if i.severity == "rejected"]
    assert rejected == [(2, "No company name"), (3, "Unknown country: blank"), (4, "Unknown country: Atlantis")]
    kept = sheet.rows[0]
    assert kept.company == "Typo Mail GmbH" and kept.contacts[0].email is None
    assert "Unverified email for KARL: karl@typo-mail" in kept.notes
    warnings = [i.message for i in sheet.issues if i.severity == "warning"]
    assert any("SPOONS" in w for w in warnings) and any("Create date not understood" in w for w in warnings)


def test_contact_blocks(tmp_path: Path) -> None:
    sheet = li.parse_sheet(build(tmp_path, row(
        company="Blocks Ltd", country="United Kingdom",
        c1="ANNA", e1="anna@blocks.example, sales@blocks.example",
        c2=None, e2="+30 210 4839011", p2=None,
        c5="LAST ONE", e5="last@blocks.example",
    )))
    r = sheet.rows[0]
    assert [c.name for c in r.contacts] == ["ANNA", "Contact", "LAST ONE"]
    assert r.contacts[0].email == "anna@blocks.example" and r.contacts[0].other_emails == ["sales@blocks.example"]
    assert r.contacts[1].phone == "+30 210 4839011" and r.contacts[1].email is None


def test_excel_date_cells_and_lead_action(tmp_path: Path) -> None:
    sheet = li.parse_sheet(build(tmp_path, row(company="Dated Co", country="France", date=datetime(2026, 3, 12),
                                               action="Order Form Issued")))
    assert sheet.rows[0].first_contact_on == date(2026, 3, 12)
    assert sheet.rows[0].lead_action == "Order Form Issued"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SPOGA 2022 & INTERGASTRA 2026", ("SPOGA 2022", ["INTERGASTRA 2026"])),
        ("VISITING CARD & HOST MILANO 2025", ("VISITING CARD", ["HOST MILANO 2025"])),
        ("MAISON & OBJET TRADE FARE 2026", ("MAISON & OBJET TRADE FARE 2026", [])),
        ("WEBSITE", ("WEBSITE", [])),
        (None, (None, [])),
    ],
)
def test_split_sources(raw: str | None, expected: tuple[str | None, list[str]]) -> None:
    assert li.split_sources(raw) == expected


def test_labels_and_currency() -> None:
    assert li.pretty_label("NRA CHICAGO 2026") == "NRA Chicago 2026"
    assert li.pretty_label("MAISON AND OBJET SHOW 2026") == "Maison and Objet Show 2026"
    assert [li.currency_for(c) for c in ("DE", "GB", "IN", "US", "AU", "BG")] == ["EUR", "GBP", "INR", "USD", "USD", "EUR"]
