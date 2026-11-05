"""Scenario M (finance part), end to end through the services and the consumers:

draft from an issued challan's suggestion → issue blocked with reasons (Demo defaults) → configuration (company
identity, a business-entered tax profile verified by a second person) → approval by someone other than the creator →
issue with ``INV-{fy}-NNNN`` → receipts and allocations that never over-allocate → ageing per currency → CSV journal
with inert formulas (blocked until account codes exist) → Demo handoff acknowledged and reconciled → integration
still "Demo — not connected"."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.errors import Conflict, Forbidden
from app.modules.finance import accounting, ageing, suggestions
from app.modules.finance.schemas import ExportRequest, ReconcileRequest
from app.platform.org import service as org
from tests.integration.finance.world import ANANYA, SAHIL, FinWorld, fin_world  # noqa: F401

pytestmark = pytest.mark.db


def test_scenario_m_finance(fin_world: FinWorld) -> None:  # noqa: F811
    w = fin_world
    # 1. an issued Outward challan suggests a draft invoice; the draft is labelled and blocked with reasons
    ids = w.delivered("100")
    with w.uow(ANANYA) as uow:
        [s] = suggestions.list_suggestions(uow)
    assert s.challan_id == ids["challan_id"]
    d = w.draft(suggestion_id=s.id)
    assert d.label == "Draft — not valid for trade" and d.total.amount == Decimal("2400.0000")
    w.act(ANANYA, d.id, "submit")
    with pytest.raises(Forbidden):
        w.act(ANANYA, d.id, "approve")  # separation of duties
    w.act(SAHIL, d.id, "approve")
    blocked = w.act(ANANYA, d.id, "issue")
    assert blocked.issued is False
    assert {"company_identity_incomplete", "tax_profile_missing"} <= {b.code for b in blocked.blockers}
    assert blocked.detail.document_number is None

    # 2. configuration by the business, then a fresh approval and issue
    w.configure_identity()
    profile = w.verified_profile()
    w.act(ANANYA, d.id, "reject", reason_code="configure_tax")
    w.set_profile(d.id, profile)
    w.act(ANANYA, d.id, "submit")
    w.act(SAHIL, d.id, "approve")
    issued = w.act(ANANYA, d.id, "issue")
    assert issued.issued and issued.detail.document_number == "INV-2026-27-0001"
    inv = issued.detail

    # 3. receipts and allocations never over-allocate
    r1 = w.receipt("1500")
    w.allocate(r1.id, inv.id, "1500")
    r2 = w.receipt("1500")
    with pytest.raises(Conflict) as exc:
        w.allocate(r2.id, inv.id, "1000")  # only 900 outstanding
    assert exc.value.code == "over_allocation"
    w.allocate(r2.id, inv.id, "500")
    assert w.get(inv.id).outstanding.amount == Decimal("400.0000")

    # 4. ageing in company time: 40 days after issue the 400 is 10 days past due
    with w.uow(ANANYA) as uow:
        report = ageing.ageing(uow, inv.document_date + timedelta(days=40))
    [row] = [x for x in report.rows if x.currency == "EUR"]
    assert row.buckets.days_1_30.amount == Decimal("400.0000") and row.unallocated_receipts.amount == Decimal("1000.0000")
    assert report.time_zone == "Asia/Kolkata"

    # 5. the CSV journal: blocked without account codes, then balanced and formula-inert
    with w.uow(ANANYA, step_up=True) as uow:
        failed = accounting.run_export(uow, ExportRequest(adapter="csv"))  # type: ignore[arg-type]
        assert failed.status == "failed" and failed.error_code == "account_mapping_missing"
    with w.uow(ANANYA, step_up=True) as uow:
        current = org.get_setting(uow, "finance_account_mapping")
        org.update_setting(uow, "finance_account_mapping", expected_version=current.version or 0,
                           value={"receivable_account": "=1100", "sales_account": "4000"})
    with w.uow(ANANYA, step_up=True) as uow:
        x = accounting.run_export(uow, ExportRequest(adapter="demo"))  # type: ignore[arg-type]
        export_id = x.id
        assert x.status == "completed" and x.simulated
    with w.uow(ANANYA) as uow:
        _, content = accounting.export_content(uow, export_id)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert "'=1100" in {r["Account"] for r in rows}  # an account code that looks like a formula stays inert
    assert sum(Decimal(r["Debit"] or 0) for r in rows) == sum(Decimal(r["Credit"] or 0) for r in rows)

    # 6. the Demo handoff is acknowledged and reconciled; the integration still says Demo — not connected
    with w.uow(ANANYA, step_up=True) as uow:
        rec = accounting.export_read(uow, accounting.reconcile(uow, export_id, ReconcileRequest()))
    assert rec.reconciliation_status == "matched" and [i.status for i in rec.items] == ["acknowledged"]
    with w.uow(ANANYA) as uow:
        st = accounting.status(uow)
    assert st.label == "Demo — not connected" and st.pending_documents == 0
    assert [e.payload["export_id"] for e in w.events("finance.accounting_export.completed")] == [str(export_id)]
