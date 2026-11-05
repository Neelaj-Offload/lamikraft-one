"""Accounting handoff adapters (operations.md §9): ``csv`` (journal export) and ``demo`` (labelled simulated
acknowledgement). A live adapter (Tally, Zoho Books, ...) is added when the owner chooses the system (BUILD_STATE §5 #3)."""

from __future__ import annotations

from app.modules.finance.adapters.base import AccountingAdapter, AdapterResult, JournalDocument
from app.modules.finance.adapters.csv_export import CsvExportAdapter
from app.modules.finance.adapters.demo import DemoAdapter

ADAPTERS: dict[str, AccountingAdapter] = {"csv": CsvExportAdapter(), "demo": DemoAdapter()}

__all__ = ["ADAPTERS", "AccountingAdapter", "AdapterResult", "CsvExportAdapter", "DemoAdapter", "JournalDocument"]
