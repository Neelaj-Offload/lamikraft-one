"""The adapter interface: ``export(batch)`` returns the journal file and (for adapters that talk to a system) the
acknowledgements; ``fetch_status`` is reserved for live adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.core.csv_safe import write_csv

JOURNAL_HEADERS = (
    "Batch",
    "Mode",
    "Voucher date",
    "Voucher type",
    "Voucher number",
    "Party",
    "Party number",
    "Account",
    "Debit",
    "Credit",
    "Currency",
    "Narration",
)


@dataclass(frozen=True)
class JournalDocument:
    invoice_id: str
    doc_type: str
    document_number: str
    document_date: date
    party_name: str
    party_number: str | None
    currency: str
    subtotal: Decimal
    tax: Decimal | None
    total: Decimal
    customer_reference: str | None


@dataclass(frozen=True)
class AccountCodes:
    receivable: str
    sales: str
    tax: str | None
    sales_returns: str | None


@dataclass
class AdapterResult:
    content: bytes
    #: document_number -> (external reference, acknowledged total); empty when nothing was acknowledged
    acknowledgements: dict[str, tuple[str, Decimal]] = field(default_factory=dict)
    acknowledgement_ref: str | None = None
    simulated: bool = False


class AccountingAdapter(Protocol):
    kind: str
    mode_label: str

    def export(self, batch_number: str, documents: list[JournalDocument], codes: AccountCodes) -> AdapterResult: ...


def journal_rows(batch_number: str, mode_label: str, documents: list[JournalDocument], codes: AccountCodes) -> list[list[object]]:
    """Balanced journal lines per document (debits = credits per voucher). Every text cell goes through csv_safe."""
    rows: list[list[object]] = []
    for d in documents:
        credit_note = d.doc_type == "credit_note"
        vtype = "Credit note" if credit_note else "Sales invoice"
        narration = f"{vtype} {d.document_number} to {d.party_name}" + (f" (ref {d.customer_reference})" if d.customer_reference else "")
        base = [batch_number, mode_label, d.document_date, vtype, d.document_number, d.party_name, d.party_number or ""]
        receivable = [codes.receivable, None, d.total] if credit_note else [codes.receivable, d.total, None]
        revenue_account = (codes.sales_returns or codes.sales) if credit_note else codes.sales
        revenue = [revenue_account, d.subtotal, None] if credit_note else [revenue_account, None, d.subtotal]
        rows.append([*base, *receivable, d.currency, narration])
        rows.append([*base, *revenue, d.currency, narration])
        if d.tax:
            tax = [codes.tax, d.tax, None] if credit_note else [codes.tax, None, d.tax]
            rows.append([*base, *tax, d.currency, narration])
    return rows


def journal_csv(batch_number: str, mode_label: str, documents: list[JournalDocument], codes: AccountCodes) -> bytes:
    return write_csv(JOURNAL_HEADERS, journal_rows(batch_number, mode_label, documents, codes))
