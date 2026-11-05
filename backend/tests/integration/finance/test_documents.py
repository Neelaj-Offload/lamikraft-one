"""Invoice PDFs and the list CSV: a draft is watermarked and labelled "Draft — not valid for trade", unconfigured
company identity, bank details and terms print labelled placeholders (never invented values); an issued invoice
prints its number, the configured identity and terms, and no draft label; the list CSV is formula-inert."""

from __future__ import annotations

import csv
import io

import pytest
from pypdf import PdfReader
from sqlalchemy import update

from app.modules.finance import documents, invoices
from app.modules.finance.models import Invoice
from app.platform.org import service as org
from tests.integration.finance.world import ANANYA, PRIYA, FinWorld

pytestmark = pytest.mark.db


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def _pdf(w: FinWorld, invoice_id: object) -> str:
    with w.uow(ANANYA) as uow:
        d = invoices.get_invoice(uow, invoice_id)  # type: ignore[arg-type]
        return _text(documents.render(uow, d))


def test_draft_pdf_labelled_with_placeholders(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("100")
    d = w.draft(challan_id=ids["challan_id"])
    text = _pdf(w, d.id)
    assert "Draft — not valid for trade" in text and "draft — no number" in text
    assert "Not configured" in text and "Invoice terms are not configured" in text
    assert "Not calculated" in text and "Bank details" in text
    assert documents.filename(w.get(d.id)).endswith("-draft.pdf")


def test_issued_pdf_prints_identity_terms_and_number(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    with w.uow(PRIYA, step_up=True) as uow:
        current = org.get_setting(uow, "document_terms")
        org.update_setting(uow, "document_terms", expected_version=current.version or 0,
                           value={"invoice": "Payment within 30 days of the invoice date."})
    inv = w.issued_invoice("10")
    text = _pdf(w, inv.id)
    assert inv.document_number in text and "Lamikraft Industries Private Limited" in text
    assert "Payment within 30 days" in text and "not valid for trade" not in text


def test_invoice_list_csv_is_formula_inert(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("5")
    d = w.draft(challan_id=ids["challan_id"])
    with w.system() as uow:
        uow.session.execute(update(Invoice).where(Invoice.id == d.id).values(party_name="@SUM(1,2)"))
    from app.modules.finance.schemas import InvoiceFilters

    with w.uow(ANANYA) as uow:
        page = invoices.list_invoices(uow, InvoiceFilters())
    rows = list(csv.DictReader(io.StringIO(documents.list_csv(page.items).decode("utf-8-sig"))))
    assert rows[0]["Party"] == "'@SUM(1,2)" and rows[0]["Label"] == "Draft — not valid for trade"
