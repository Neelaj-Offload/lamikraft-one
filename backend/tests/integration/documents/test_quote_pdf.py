"""The quotation PDF (LM-56, BUG-03): rendered from the issued revision snapshot only, A4, the item table header
repeated on every page, € ₹ £ glyphs extracted from the embedded fonts, totals exactly as persisted (surcharge and the
threshold note only when the persisted result applied them), "Page x of y", deterministic bytes = the revision's
``document_sha256``, and the HTTP download headers."""

from __future__ import annotations

import hashlib
import io
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.modules.approvals import service as approvals
from app.modules.sales import service as sales
from app.modules.sales.documents import NOT_CONFIGURED, render_quote_pdf
from app.modules.sales.schemas import QuoteCreate, QuoteLineCreate
from app.seed.world import keys
from tests.integration.sales.http import API, as_, problem
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI
A4 = (595.0, 842.0)
MANUAL_LINES = 44


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


def _approve_review(world: SalesWorld, quote_id: uuid.UUID) -> None:
    review = world.transition(MEERA, quote_id, "submit_review")
    with world.uow(SAHIL) as uow:
        proposal = approvals.get(uow, review.review.review_proposal_id)
        approvals.decide(uow, proposal.id, decision="approve", content_hash_seen=proposal.content_hash,
                         expected_version=proposal.version, reason="Sample order below minimum, surcharge applies")


def _below_minimum_quote(world: SalesWorld) -> uuid.UUID:
    """EUR, surcharge toggle on, 44 manual lines + one catalog line: EUR 1,016.00 + 400.00 surcharge."""
    with world.uow(MEERA) as uow:
        quote = sales.create_quote(uow, QuoteCreate(
            party_id=world.ref("NORDHAUS"), apply_minimum_surcharge=True, customer_reference="PO Łódź-77",
            remarks="Unicode check: € ₹ £ — Größe, café, Ærø. Prices per piece.",
        ))
        for i in range(1, MANUAL_LINES + 1):
            quote, _line = sales.add_line(uow, quote.id, QuoteLineCreate(
                expected_version=quote.version, line_type="manual", description=f"Sample panel № {i} (₹ / £ reference)",
                quantity=Decimal("1"), unit_price=Decimal("10"), unit_code="pcs",
            ))
        quote, _line = sales.add_line(uow, quote.id, QuoteLineCreate(
            expected_version=quote.version, product_id=world.ref("OAK_TRAY"), quantity=Decimal("24"),
        ))
        return quote.id


def test_layout_unicode_pagination_and_totals(world: SalesWorld) -> None:
    quote_id = _below_minimum_quote(world)
    with world.uow(MEERA) as uow:
        draft = sales.get_quote(uow, quote_id)
    assert draft.totals.minimum.status == "BELOW" and draft.totals.surcharge_applied
    assert str(draft.totals.grand_total.amount) == "1416.00" and draft.review.reasons == ["below_minimum"]
    _approve_review(world, quote_id)
    sent = world.transition(MEERA, quote_id, "mark_sent")
    assert sent.status == "sent" and sent.revision_no == 1

    with world.uow(MEERA) as uow:
        snapshot, expected_sha = sales.revision_document(uow, quote_id, 1)
    pdf = render_quote_pdf(snapshot)
    assert hashlib.sha256(pdf).hexdigest() == expected_sha  # same snapshot -> same bytes as at issue
    assert render_quote_pdf(snapshot) == pdf
    assert pdf.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(pdf))
    pages = _pages(pdf)
    assert len(pages) >= 2, "45 lines must spill onto a second page"
    for page in reader.pages:
        assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == A4
    item_pages = [n for n, text in enumerate(pages, start=1) if "Sample panel" in text or keys.PRODUCTS.OAK_TRAY in text]
    assert len(item_pages) >= 2, "the item table must continue across pages"
    for n, text in enumerate(pages, start=1):
        if n in item_pages:
            assert "Unit price" in text and "Line total" in text, f"table header not repeated on page {n}"
        assert f"Page {n} of {len(pages)}" in text
        assert sent.quote_number in text
    text = "\n".join(pages)
    for glyph in ("€", "₹", "£", "№", "Łódź", "Größe", "Ærø"):
        assert glyph in text, glyph
    assert not [ch for ch in text if 0xE000 <= ord(ch) <= 0xF8FF], "private-use code points leaked"
    assert NOT_CONFIGURED in text and "Quotation" in text and keys.PARTY_NAMES["NORDHAUS"] in text
    assert "Sample panel № 44" in text and keys.PRODUCTS.OAK_TRAY in text
    # totals exactly as persisted: subtotal, surcharge (applied), grand total excluding taxes, threshold note
    assert "Subtotal" in text and "€1,016.00" in text
    assert "Shipping surcharge" in text and "€400.00" in text
    assert "Grand total (excludes taxes)" in text and "€1,416.00" in text
    assert "Minimum invoice value: €5,000.00" in text
    assert "Discount" not in text  # no discount row when the persisted discount is zero
    assert "internal" not in text.lower()  # internal notes never reach the document


def test_non_eur_quote_has_no_surcharge_or_threshold_note(sales_world: SalesWorld) -> None:
    """GBP: the minimum is NOT_EVALUATED, so no surcharge row and no note, whatever the toggle says (fixtures §11)."""
    with sales_world.uow(NEHA) as uow:
        snapshot, sha = sales.revision_document(uow, sales_world.ref("Q_THORNBURY_EXPIRING"), 1)
    pdf = render_quote_pdf(snapshot)
    assert hashlib.sha256(pdf).hexdigest() == sha
    text = "\n".join(_pages(pdf))
    assert keys.QUOTES.THORNBURY_EXPIRING in text and "£5,880.00" in text and "£21.00" in text
    assert "Grand total (excludes taxes)" in text and "Shipping surcharge" not in text and "Minimum invoice value" not in text
    assert "Valid until" in text and "12 Oct 2026" in text and "12 Sep 2026" in text  # issued Sat 12 Sep, valid 30 days


def test_pdf_download_headers_and_scope(sales_client: TestClient, sales_world: SalesWorld) -> None:
    berg = sales_world.ref("Q_BERG_EXPIRING")
    r = sales_client.get(f"{API}/sales/quotes/{berg}/revisions/1/document.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline;") and f"{keys.QUOTES.BERG_EXPIRING}-r1.pdf" in r.headers["content-disposition"]
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["content-security-policy"] == "sandbox"
    assert r.headers["cache-control"] == "private, no-store"  # the route's own policy, not the middleware default
    assert r.headers.get_list("x-content-type-options") == ["nosniff"] and len(r.headers.get_list("cache-control")) == 1
    with sales_world.uow(MEERA) as uow:
        _snapshot, sha = sales.revision_document(uow, berg, 1)
    assert hashlib.sha256(r.content).hexdigest() == sha == r.headers["x-document-sha256"]
    assert r.headers["etag"] == f'"{sha}"'
    # Neha (own scope) cannot see Meera's quote: 404; Ravi reads but may not export: 403; unknown revision: 404
    problem(sales_client.get(f"{API}/sales/quotes/{berg}/revisions/1/document.pdf", headers=as_(NEHA)), 404, "not_found")
    problem(sales_client.get(f"{API}/sales/quotes/{berg}/revisions/1/document.pdf", headers=as_(RAVI)), 403, "permission_denied")
    problem(sales_client.get(f"{API}/sales/quotes/{berg}/revisions/2/document.pdf"), 404, "not_found")
    draft = sales_world.ref("Q_NORDHAUS_DRAFT")  # visible but never issued: nothing to export (403 with the reason)
    problem(sales_client.get(f"{API}/sales/quotes/{draft}/revisions/1/document.pdf"), 403, "quote_not_issued")
