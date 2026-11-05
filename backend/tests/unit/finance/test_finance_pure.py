"""Pure finance rules: ageing buckets by days past due, line-level HALF_UP rounding to the minor unit, tax only from a
profile rate, balanced and formula-inert journal rows from both adapters, and the transition table."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.finance import common as c
from app.modules.finance.adapters import ADAPTERS
from app.modules.finance.adapters.base import AccountCodes, JournalDocument, journal_rows
from app.modules.finance.ageing import bucket_of
from app.modules.finance.invoices import REASON_REQUIRED, TRANSITIONS

AS_OF = date(2026, 10, 12)


@pytest.mark.parametrize(
    ("days_past_due", "bucket"),
    [(-5, "current"), (0, "current"), (1, "days_1_30"), (30, "days_1_30"), (31, "days_31_60"), (60, "days_31_60"),
     (61, "days_61_90"), (90, "days_61_90"), (91, "days_over_90"), (400, "days_over_90")],
)
def test_ageing_buckets(days_past_due: int, bucket: str) -> None:
    assert bucket_of(AS_OF, AS_OF - timedelta(days=days_past_due)) == bucket


def test_no_due_date_counts_as_current() -> None:
    assert bucket_of(AS_OF, None) == "current"


def test_line_rounding_half_up_to_the_minor_unit_and_tax_from_the_rate_only() -> None:
    assert c.line_amount(Decimal("3"), Decimal("0.335"), "EUR") == Decimal("1.0100")  # 1.005 -> 1.01 (HALF_UP)
    assert c.line_amount(Decimal("1"), Decimal("2.345"), "INR") == Decimal("2.3500")
    assert c.tax_of(Decimal("100.05"), Decimal("18"), "INR") == Decimal("18.0100")  # 18.009 -> 18.01
    assert c.tax_of(Decimal("100"), None, "EUR") is None  # no profile: no tax is invented


def _doc(doc_type: str, party: str = "Nordhaus", tax: Decimal | None = Decimal("18.00")) -> JournalDocument:
    return JournalDocument(invoice_id="x", doc_type=doc_type, document_number="INV-2026-27-0001", document_date=AS_OF,
                           party_name=party, party_number="P-1", currency="EUR", subtotal=Decimal("100.00"), tax=tax,
                           total=Decimal("100.00") + (tax or 0), customer_reference=None)


CODES = AccountCodes(receivable="1100", sales="4000", tax="2200", sales_returns="4100")


@pytest.mark.parametrize("doc_type", ["invoice", "credit_note"])
def test_journal_rows_balance(doc_type: str) -> None:
    rows = journal_rows("AX-1", "CSV export", [_doc(doc_type)], CODES)
    debit = sum(Decimal(r[8] or 0) for r in rows)
    credit = sum(Decimal(r[9] or 0) for r in rows)
    assert debit == credit == Decimal("118.00") and len(rows) == 3
    accounts = {r[7] for r in rows}
    assert accounts == ({"1100", "4100", "2200"} if doc_type == "credit_note" else {"1100", "4000", "2200"})


def test_adapters_write_inert_csv_and_only_demo_acknowledges() -> None:
    doc = _doc("invoice", party="=cmd|' /C calc'!A0", tax=None)
    csv_out = ADAPTERS["csv"].export("AX-1", [doc], CODES)
    demo_out = ADAPTERS["demo"].export("AX-2", [doc], CODES)
    assert csv_out.acknowledgements == {} and not csv_out.simulated
    assert demo_out.simulated and demo_out.acknowledgements == {"INV-2026-27-0001": ("DEMO-INV-2026-27-0001", Decimal("100.00"))}
    for out in (csv_out, demo_out):
        rows = list(csv.DictReader(io.StringIO(out.content.decode("utf-8-sig"))))
        assert {r["Party"] for r in rows} == {"'=cmd|' /C calc'!A0"}


def test_transition_table() -> None:
    assert TRANSITIONS[("draft", "submit")] == "pending_approval"
    assert TRANSITIONS[("pending_approval", "approve")] == "approved"
    assert TRANSITIONS[("approved", "issue")] == "issued"
    assert not any(frm == "issued" for frm, _ in TRANSITIONS)  # issued is final: corrections are credit notes
    assert ("draft", "issue") not in TRANSITIONS and ("pending_approval", "issue") not in TRANSITIONS
    assert REASON_REQUIRED == {"reject", "cancel"}
