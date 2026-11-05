"""``CsvExportAdapter``: a journal-ready, formula-escaped CSV the accountant imports into the books. Nothing is
acknowledged automatically: reconciliation imports the accounting-side references and totals."""

from __future__ import annotations

from app.modules.finance.adapters.base import AccountCodes, AdapterResult, JournalDocument, journal_csv


class CsvExportAdapter:
    kind = "csv"
    mode_label = "CSV export"

    def export(self, batch_number: str, documents: list[JournalDocument], codes: AccountCodes) -> AdapterResult:
        return AdapterResult(content=journal_csv(batch_number, self.mode_label, documents, codes))
