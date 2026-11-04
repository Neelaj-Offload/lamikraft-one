"""The accounting handoff (operations.md §9): the CSV adapter writes a balanced, formula-inert journal and blocks
documents without account codes; the Demo adapter records the export with a labelled simulated acknowledgement;
reconciliation compares exported with acknowledged and lists every mismatch; nothing claims a live connection."""

from __future__ import annotations

import csv
import hashlib
import io
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.core.errors import ValidationFailed
from app.modules.finance import accounting
from app.modules.finance.models import Invoice
from app.modules.finance.schemas import AckLine, ExportRequest, ReconcileRequest
from app.platform.org import service as org
from tests.integration.finance.world import ANANYA, SAHIL, FinWorld

pytestmark = pytest.mark.db
EVIL = '=HYPERLINK("http://evil.test","x")'


def _map(w: FinWorld, **codes: str) -> None:
    with w.uow(ANANYA, step_up=True) as uow:
        current = org.get_setting(uow, "finance_account_mapping")
        org.update_setting(uow, "finance_account_mapping", expected_version=current.version or 0, value=codes)


def _export(w: FinWorld, adapter: str) -> object:
    with w.uow(ANANYA, step_up=True) as uow:
        return accounting.export_read(uow, accounting.run_export(uow, ExportRequest(adapter=adapter)))  # type: ignore[arg-type]


def _rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def test_csv_export_inert_formulas_and_mapping_blocks(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    ids = w.delivered("100")
    profile = w.verified_profile()
    d = w.draft(challan_id=ids["challan_id"], tax_profile_id=profile)
    with w.system() as uow:  # a hostile party name reaching the journal (test-only write to the draft snapshot)
        uow.session.execute(update(Invoice).where(Invoice.id == d.id).values(party_name=EVIL))
    w.act(ANANYA, d.id, "submit")
    w.act(SAHIL, d.id, "approve")
    assert w.act(ANANYA, d.id, "issue").issued

    # no account codes: the batch fails, nothing is exported, the document stays pending
    failed = _export(w, "csv")
    assert (failed.status, failed.error_code, failed.blocked_count, failed.document_count) == ("failed", "account_mapping_missing", 1, 0)
    assert failed.blocked[0].reason == "account_mapping_missing"
    assert w.events("finance.accounting_export.failed")[-1].payload["error_code"] == "account_mapping_missing"
    with w.uow(ANANYA) as uow:
        assert accounting.status(uow).pending_documents == 1

    _map(w, receivable_account="1100-AR", sales_account="4000-SALES")
    done = _export(w, "csv")
    assert (done.status, done.document_count, done.simulated, done.acknowledgement_ref) == ("completed", 1, False, None)
    assert [i.status for i in done.items] == ["exported"]
    with w.uow(ANANYA) as uow:
        name, content = accounting.export_content(uow, done.id)
    assert name.endswith("-journal.csv") and hashlib.sha256(content).hexdigest() == done.content_sha256
    rows = _rows(content)
    assert len(rows) == 2  # receivable debit + sales credit (no tax on a 0 % profile)
    assert {r["Party"] for r in rows} == {"'" + EVIL}  # formula-inert
    assert all(not r["Narration"].startswith(("=", "+", "-", "@")) for r in rows)
    debit = sum(Decimal(r["Debit"] or 0) for r in rows)
    credit = sum(Decimal(r["Credit"] or 0) for r in rows)
    assert debit == credit == Decimal("2400.0000")
    assert {r["Mode"] for r in rows} == {"CSV export"}
    # a document is exported once: a second batch has nothing to export
    again = _export(w, "csv")
    assert (again.status, again.error_code) == ("failed", "nothing_to_export")

    # CSV reconciliation needs the accounting side's lines; a differing total is a mismatch
    with w.uow(ANANYA, step_up=True) as uow, pytest.raises(ValidationFailed):
        accounting.reconcile(uow, done.id, ReconcileRequest())
    number = done.items[0].document_number
    with w.uow(ANANYA, step_up=True) as uow:
        rec = accounting.export_read(uow, accounting.reconcile(uow, done.id, ReconcileRequest(
            lines=[AckLine(document_number=number, external_ref="TALLY-77", total=Decimal("2399.00"))])))
    assert rec.reconciliation_status == "mismatch" and rec.items[0].mismatch_reason == "total_differs"
    with w.uow(ANANYA, step_up=True) as uow:
        rec = accounting.export_read(uow, accounting.reconcile(uow, done.id, ReconcileRequest(
            lines=[AckLine(document_number=number, external_ref="TALLY-77", total=Decimal("2400"))])))
    assert rec.reconciliation_status == "matched" and rec.items[0].status == "acknowledged"


def test_demo_export_acknowledged_and_reconciled(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    w.issued_invoice("10")
    _map(w, receivable_account="1100-AR", sales_account="4000-SALES")
    with w.uow(ANANYA) as uow:
        st = accounting.status(uow)
    assert (st.mode, st.state, st.label) == ("demo", "not_connected", "Demo — not connected")
    assert st.mapping_complete and st.pending_documents == 1
    x = _export(w, "demo")
    assert x.status == "completed" and x.simulated and x.acknowledgement_ref.startswith("DEMO-ACK-")
    assert [(i.status, i.external_ref) for i in x.items] == [("acknowledged", f"DEMO-{x.items[0].document_number}")]
    with w.uow(ANANYA) as uow:
        _, content = accounting.export_content(uow, x.id)
    assert {r["Mode"] for r in _rows(content)} == {"Demo (simulated, not posted)"}
    with w.uow(ANANYA, step_up=True) as uow:
        rec = accounting.export_read(uow, accounting.reconcile(uow, x.id, ReconcileRequest()))
    assert rec.reconciliation_status == "matched"
    payloads = [e.payload for e in w.events("finance.accounting_export.reconciled")]
    assert payloads[-1]["reconciliation_status"] == "matched" and "total" not in payloads[-1]
    # the integration still says Demo / not connected after a Demo export
    with w.uow(ANANYA) as uow:
        assert accounting.status(uow).state == "not_connected"
