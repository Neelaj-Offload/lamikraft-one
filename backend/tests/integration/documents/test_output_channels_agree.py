"""BUG-03: every output channel reads the persisted engine result, so the totals agree to the cent.

Slice 1 has two channels: the API detail (and list row) and the issued PDF. CSV export and the print view are Slice 2;
when they land they join the same assertion."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.documents import format_money
from app.seed.world import keys
from tests.integration.sales.http import API, as_
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
ISSUED = ("Q_BERG_WON", "Q_THORNBURY_LOST", "PRIOR_WON", "Q_THORNBURY_EXPIRING", "Q_BERG_EXPIRING")


def test_api_pdf_csv_print_totals_identical(sales_client: TestClient, sales_world: SalesWorld) -> None:
    sahil = as_(keys.USERS.SAHIL)
    rows = {q["id"]: q for q in sales_client.get(f"{API}/sales/quotes", params={"limit": 50}, headers=sahil).json()["items"]}
    for key in ISSUED:
        quote_id = str(sales_world.ref(key))
        detail = sales_client.get(f"{API}/sales/quotes/{quote_id}", headers=sahil).json()
        totals = detail["totals"]
        currency = detail["currency"]
        grand = totals["grand_total"]
        assert grand["currency"] == currency and rows[quote_id]["grand_total"] == grand, key  # list row = detail
        revision = sales_client.get(f"{API}/sales/quotes/{quote_id}/revisions/{detail['revision_no']}", headers=sahil).json()
        assert revision["snapshot"]["totals"]["grand_total"] == format(Decimal(grand["amount"]).quantize(Decimal("0.0001")), "f"), key
        pdf = sales_client.get(f"{API}/sales/quotes/{quote_id}/revisions/{detail['revision_no']}/document.pdf", headers=sahil)
        assert pdf.status_code == 200, pdf.text
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf.content)).pages)
        grand_text = format_money(Decimal(grand["amount"]), currency)
        assert "Grand total (excludes taxes)" in text and grand_text in text, (key, grand_text)
        assert format_money(Decimal(totals["gross_subtotal"]["amount"]), currency) in text, key
        surcharge = Decimal(totals["surcharge"]["amount"])
        assert ("Shipping surcharge" in text) is bool(totals["surcharge_applied"]), key
        assert surcharge == 0 or format_money(surcharge, currency) in text, key
