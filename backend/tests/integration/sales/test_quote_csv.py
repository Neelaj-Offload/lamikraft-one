"""Quote CSV exports (LM-57, API-38, BUG-04, SEC-02): rows bounded by the export scope, persisted line counts and
totals, creator/owner names (not ids), UTF-8 BOM and formula escaping; the per-quote lines CSV."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest

from app.core.errors import Forbidden, NotFound
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteFilters
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, NEHA, SAHIL, RAVI = keys.USERS.MEERA, keys.USERS.NEHA, keys.USERS.SAHIL, keys.USERS.RAVI


def _rows(content: bytes) -> list[dict[str, str]]:
    assert content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM so Excel opens € and ₹ correctly
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def test_line_counts_names_totals_and_escaping(sales_world: SalesWorld) -> None:
    w = sales_world
    q = w.new_draft(MEERA, "NORDHAUS", ("OAK_TRAY", "240"), ("MAPLE_TRIVET", "10"), customer_reference="=HYPERLINK(\"http://x\")")
    with w.uow(MEERA) as uow:
        rows = _rows(sales.export_quotes_csv(uow, QuoteFilters()))
    numbers = {r["Quote number"] for r in rows}
    assert numbers == {keys.QUOTES.BERG_WON, keys.QUOTES.PRIOR_WON, keys.QUOTES.MAISON_OVERRIDE, keys.QUOTES.BERG_EXPIRING,
                       keys.QUOTES.NORDHAUS_DRAFT, q.quote_number}  # SEC-02: never Neha's quotes
    row = next(r for r in rows if r["Quote number"] == q.quote_number)
    assert row["Total lines"] == "2" and row["Owner"] == "Meera Iyer" and row["Created by"] == "Meera Iyer"  # BUG-04
    assert row["Customer reference"].startswith("'=HYPERLINK")  # formula escaped
    assert (row["Gross subtotal"], row["Grand total"], row["Currency"], row["Status"]) == ("5855.00", "5855.00", "EUR", "draft")
    assert row["Tax"] == "Excludes taxes"
    with w.uow(NEHA) as uow:
        neha = {r["Quote number"] for r in _rows(sales.export_quotes_csv(uow, QuoteFilters()))}
    assert q.quote_number not in neha and keys.QUOTES.THORNBURY_EXPIRING in neha
    with w.uow(SAHIL) as uow:  # management exports everything, filters apply before export
        filtered = _rows(sales.export_quotes_csv(uow, QuoteFilters(status=["won"])))  # type: ignore[list-item]
    assert {r["Quote number"] for r in filtered} == {keys.QUOTES.BERG_WON, keys.QUOTES.PRIOR_WON}
    with pytest.raises(Forbidden), w.uow(RAVI) as uow:  # operations read quotes but do not export
        sales.export_quotes_csv(uow, QuoteFilters())
    # the per-quote lines CSV: same scope rules, lines in order, grand total row
    with w.uow(MEERA) as uow:
        name, content = sales.export_quote_lines_csv(uow, q.id)
    lines = _rows(content)
    assert name == f"{q.quote_number}-lines.csv"
    assert [(r["Line"], r["Quantity"], r["Unit price"], r["Line total"]) for r in lines[:2]] == [
        ("1", "240", "24.0000", "5760.00"), ("2", "10", "9.5000", "95.00")]
    assert lines[-1]["Description"] == "Grand total" and lines[-1]["Line total"] == "5855.00"
    with pytest.raises(NotFound), w.uow(NEHA) as uow:
        sales.export_quote_lines_csv(uow, q.id)
    with pytest.raises(Forbidden), w.uow(RAVI) as uow:
        sales.export_quote_lines_csv(uow, q.id)
    assert Decimal(row["Net subtotal"]) == Decimal("5855.00")
