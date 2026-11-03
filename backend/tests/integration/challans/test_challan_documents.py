"""Output channels (LM-90, LM-91, API-59, API-64, FG-DC-10, BUG-03): the PDF, the print view data and the CSV read the
same snapshot; Unicode names and currency signs survive; long challans paginate without losing text; terms and
signature blocks come from settings; internal notes are never printed; CSV text is spreadsheet-inert and scoped."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.modules.challans import documents
from app.modules.challans import service as challans
from app.modules.challans.models import Challan
from app.modules.challans.schemas import ChallanLineAdd, ChallanUpdate, LineType
from app.platform.collab import service as notes
from app.seed.world import keys
from tests.integration.challans.conftest import CHALLANS, as_, problem
from tests.integration.challans.world import ChallanWorld

pytestmark = pytest.mark.db
RAVI, SAHIL, MEERA, PRIYA = keys.USERS.RAVI, keys.USERS.SAHIL, keys.USERS.MEERA, keys.USERS.PRIYA
SECRET = "INTERNAL ONLY: customer owes ₹ 12,000 — hold next dispatch"


def _text(pdf: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def test_pdf_unicode_pagination_terms_signatures_no_internal_notes(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    draft = w.new_draft(RAVI, party_id=w.ref("MAISON"), shipping_name="Maison Atelier — Entrepôt B, Lyon",
                        remarks="Printed remark: handle with care · ₹ and € signs survive", reference_no="PO/€/₹-77")
    with w.uow(RAVI) as uow:
        c = uow.repo(Challan).get(draft.id)
        for i in range(60):  # enough rows to spill over several pages
            c, _ = challans.add_line(uow, draft.id, ChallanLineAdd(
                expected_version=c.version, line_type=LineType.MANUAL, item_name=f"Zeile {i + 1}: Räuchereiche Tablett „Ø 45 cm“ — नमूना",
                item_code=f"ZE-{i + 1:03d}", quantity=Decimal("3"), unit="pcs", remarks="Fragil" if i % 2 else None,
            ))
        notes.save_note(uow, "challans.challan", draft.id, body=SECRET, expected_version=0)
    issued = w.transition(RAVI, draft.id, "issue")
    # the PDF: rendered from the frozen revision, deterministic, with the recorded hash as ETag
    r = challan_client.get(f"{CHALLANS}/{draft.id}/document.pdf", headers=as_(RAVI))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert r.headers["content-security-policy"] == "sandbox" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["etag"] == f'"{r.headers["x-document-sha256"]}"'
    again = challan_client.get(f"{CHALLANS}/{draft.id}/revisions/1/document.pdf", headers=as_(RAVI))
    assert again.content == r.content  # pure function of the snapshot
    text, pages = _text(r.content)
    assert pages >= 2 and all(f"ZE-{i:03d}" in text for i in range(1, 61)), "every line survives pagination"
    assert "Delivery challan" in text and issued.challan_number in text and "Maison Atelier" in text
    assert "Entrepôt B" in text and "€" in text and "₹" in text and "Räuchereiche" in text
    assert "Total quantity" in text and "180 pcs" in text
    assert "Printed remark" in text and "Terms and conditions" in text and "Demo terms placeholder" in text
    for label in documents.SIGNATURES:
        assert label in text, label
    assert "Page 1 of" in text or "1 of" in text
    assert "INTERNAL ONLY" not in text and "owes" not in text and "12,000" not in text  # FG-DC-11 / LM-95
    # a draft renders live with a DRAFT watermark and no ETag
    other = w.new_draft(RAVI, ("OAK_TRAY", "4"), party_id=w.ref("NORDHAUS"))
    d = challan_client.get(f"{CHALLANS}/{other.id}/document.pdf", headers=as_(RAVI))
    assert d.status_code == 200 and "etag" not in d.headers and "draft" in d.headers["content-disposition"]
    assert "DRAFT" in _text(d.content)[0]
    # terms from settings replace the demo text on the next render of a draft (issued revisions keep theirs)
    with w.uow(PRIYA, recent_auth_at=w.ctx.clock.now()) as uow:  # a settings change needs a recent sign-in
        from app.platform.org import service as org

        current = org.get_setting(uow, "document_terms")
        org.update_setting(uow, "document_terms", value={**current.value, "challan": "1. Own terms line.\n2. Second clause."}, expected_version=current.version)
    fresh = challan_client.get(f"{CHALLANS}/{other.id}/document.pdf", headers=as_(RAVI))
    fresh_text = _text(fresh.content)[0]
    assert "Own terms line" in fresh_text and "Demo terms placeholder" not in fresh_text
    assert "Demo terms placeholder" in _text(challan_client.get(f"{CHALLANS}/{draft.id}/document.pdf", headers=as_(RAVI)).content)[0]


def test_print_view_matches_pdf_and_api(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    cid = w.ref(keys.CHALLAN_REFS.JOB_WORK)
    with w.uow(RAVI) as uow:
        notes.save_note(uow, "challans.challan", cid, body=SECRET, expected_version=0)
    api = challan_client.get(f"{CHALLANS}/{cid}", headers=as_(RAVI)).json()
    view = challan_client.get(f"{CHALLANS}/{cid}/print", headers=as_(RAVI)).json()
    pdf_text = _text(challan_client.get(f"{CHALLANS}/{cid}/document.pdf", headers=as_(RAVI)).content)[0]
    assert view["challan_number"] == api["challan_number"] == keys.CHALLANS.JOB_WORK
    assert view["type_label"] == "Job Work" and view["return_label"] == "Returnable" and view["destination_label"] == "Fabricator"
    assert view["to_block"]["lines"][0] == api["destination_party"] == keys.PARTY_NAMES["PRECISION_EDGE"]
    assert view["from_block"]["lines"][0] == api["source_location"]
    assert [ln["quantity"] for ln in view["lines"]] == [ln["quantity"] for ln in api["lines"]] == ["12"]
    assert view["total_quantity"] == api["quantity_by_unit"] == {"sheets": "12"}  # the product's unit of sale
    assert view["signatures"] == list(documents.SIGNATURES) and view["terms_are_demo"] is True and view["watermark"] is None
    assert "INTERNAL ONLY" not in str(view) and "INTERNAL ONLY" not in pdf_text
    assert "12 sheets" in pdf_text and keys.PARTY_NAMES["PRECISION_EDGE"] in pdf_text
    assert "Not configured" in view["company_lines"][0] and "address" in view["not_configured"]


def test_csv_escaped_and_scoped(challan_client, challan_world: ChallanWorld) -> None:  # type: ignore[no-untyped-def]
    w = challan_world
    hostile = w.new_draft(RAVI, ("OAK_TRAY", "2"), party_id=w.ref("NORDHAUS"), reference_no="=HYPERLINK(\"http://evil\")",
                          shipping_name="+cmd|' /C calc'!A0", remarks="\t@SUM(1+1)")
    with w.uow(RAVI) as uow:
        challans.update_challan(uow, hostile.id, ChallanUpdate(expected_version=hostile.version, remarks="-2+3"))
    r = challan_client.get(f"{CHALLANS}/export.csv", headers=as_(RAVI))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8")
    assert body.startswith("﻿") and "\r\n" in body
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    header, data = rows[0], rows[1:]
    assert header == list(documents.CSV_HEADERS)
    by_number = {row[0]: row for row in data}
    assert set(by_number) == {keys.CHALLANS.JOB_WORK, keys.CHALLANS.SAMPLE_MAISON, keys.CHALLANS.OUTWARD_DRAFT, hostile.challan_number}
    row = by_number[hostile.challan_number]
    assert row[header.index("Reference")] == "'=HYPERLINK(\"http://evil\")"
    assert row[header.index("Shipping name")] == "'+cmd|' /C calc'!A0"
    assert row[header.index("Remarks")] == "'-2+3"
    assert row[header.index("Lines")] == "1" and row[header.index("Total quantity")] == "2 pcs"
    assert by_number[keys.CHALLANS.JOB_WORK][header.index("Status")] == "Issued"
    assert by_number[keys.CHALLANS.JOB_WORK][header.index("Owner")] == keys.PEOPLE[RAVI].name
    # the list, the summary and the CSV agree on the set and the counts (BUG-03 for documents)
    listed = challan_client.get(CHALLANS, params={"limit": 50}, headers=as_(RAVI)).json()
    assert {c["challan_number"] for c in listed["items"]} == set(by_number)
    for item in listed["items"]:
        assert by_number[item["challan_number"]][header.index("Lines")] == str(item["line_count"])
    # scope: Meera (sales, own) exports nothing of Ravi's; filters apply to the export too
    meera = challan_client.get(f"{CHALLANS}/export.csv", headers=as_(MEERA))
    assert meera.status_code == 200 and len(list(csv.reader(io.StringIO(meera.content.decode("utf-8").lstrip("﻿"))))) == 1
    filtered = challan_client.get(f"{CHALLANS}/export.csv", params={"status": "draft"}, headers=as_(SAHIL))
    drafts = list(csv.reader(io.StringIO(filtered.content.decode("utf-8").lstrip("﻿"))))[1:]
    assert {row[0] for row in drafts} == {keys.CHALLANS.OUTWARD_DRAFT, hostile.challan_number}
    # without the export right the route is 403 (Kabir: warehouse template has no challan export)
    problem(challan_client.get(f"{CHALLANS}/export.csv", headers=as_(keys.USERS.KABIR)), 403, "permission_denied")
