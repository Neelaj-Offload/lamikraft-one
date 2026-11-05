"""``DemoAdapter``: records the export and returns a **simulated** acknowledgement (labelled Demo everywhere; no
external system is contacted and nothing is posted to any books)."""

from __future__ import annotations

from app.modules.finance.adapters.base import AccountCodes, AdapterResult, JournalDocument, journal_csv


class DemoAdapter:
    kind = "demo"
    mode_label = "Demo (simulated, not posted)"

    def export(self, batch_number: str, documents: list[JournalDocument], codes: AccountCodes) -> AdapterResult:
        return AdapterResult(
            content=journal_csv(batch_number, self.mode_label, documents, codes),
            acknowledgements={d.document_number: (f"DEMO-{d.document_number}", d.total) for d in documents},
            acknowledgement_ref=f"DEMO-ACK-{batch_number}",
            simulated=True,
        )
