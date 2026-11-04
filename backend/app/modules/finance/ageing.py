"""Receivables ageing, the finance hub summary and the exceptions list (all server-computed, company time).

Ageing is per (party, currency) as of a date: outstanding = total − allocations dated on or before that date, for
invoices issued on or before it. Buckets by days past due: current (not yet due), 1–30, 31–60, 61–90, over 90.
Amounts are never summed across currencies; an invoice without a due date is counted under current and flagged.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.core.http.capabilities import Capability
from app.core.money import Money
from app.modules.finance import common as c
from app.modules.finance.enums import (
    DocType,
    InvoiceStatus,
    MarginExceptionStatus,
    ReceiptStatus,
    SuggestionStatus,
    SyncStatus,
    TaxProfileStatus,
)
from app.modules.finance.models import (
    AccountingExport,
    AccountingSyncItem,
    Invoice,
    InvoiceSuggestion,
    MarginException,
    Receipt,
    TaxProfile,
)
from app.modules.finance.schemas import (
    AgeingBuckets,
    AgeingReport,
    AgeingRow,
    CurrencyFigure,
    FinanceDocRef,
    FinanceException,
    FinanceSummary,
    OpenInvoiceRef,
)
from app.platform.uow import UnitOfWork

BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_over_90")


def bucket_of(as_of: date, due: date | None) -> str:
    if due is None:
        return "current"
    days = (as_of - due).days
    if days <= 0:
        return "current"
    if days <= 30:
        return "days_1_30"
    if days <= 60:
        return "days_31_60"
    if days <= 90:
        return "days_61_90"
    return "days_over_90"


def _buckets(values: dict[str, Decimal], currency: str) -> AgeingBuckets:
    figures = {b: Money(amount=values.get(b, c.ZERO), currency=currency) for b in BUCKETS}  # type: ignore[arg-type]
    return AgeingBuckets(**figures, total=c.m(sum(values.values(), c.ZERO), currency))


def _open_issued(uow: UnitOfWork, as_of: date) -> list[tuple[Invoice, Decimal]]:
    rows = list(uow.session.scalars(
        select(Invoice).where(uow.repo(Invoice).clause("read"), Invoice.doc_type == DocType.INVOICE.value,
                              Invoice.status == InvoiceStatus.ISSUED.value, Invoice.document_date <= as_of)
        .order_by(Invoice.party_name, Invoice.currency, Invoice.due_date.nulls_last(), Invoice.document_number)))
    alloc = c.allocated_to_invoices(uow, [r.id for r in rows], as_of=as_of)
    out = []
    for inv in rows:
        left = Decimal(inv.total_amount) - alloc.get(inv.id, c.ZERO)
        if left > 0:
            out.append((inv, left))
    return out


def _unallocated(uow: UnitOfWork) -> dict[tuple, Decimal]:
    from app.modules.finance.receipts import unallocated_amounts

    rows = list(uow.session.scalars(select(Receipt).where(uow.repo(Receipt).clause("read"),
                                                          Receipt.status == ReceiptStatus.RECORDED.value)))
    amounts = unallocated_amounts(uow, rows)
    out: dict[tuple, Decimal] = defaultdict(lambda: c.ZERO)
    for r in rows:
        if amounts.get(r.id, c.ZERO) > 0:
            out[(r.party_id, r.currency)] += amounts[r.id]
    return out


def ageing(uow: UnitOfWork, as_of: date | None = None) -> AgeingReport:
    uow.actor.require(c.AGEING_READ)
    as_of = as_of or c.today(uow)
    grouped: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: c.ZERO))
    counts: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    names: dict = {}
    no_due: list[OpenInvoiceRef] = []
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: c.ZERO))
    for inv, left in _open_issued(uow, as_of):
        key = (inv.party_id, inv.currency)
        b = bucket_of(as_of, inv.due_date)
        grouped[key][b] += left
        totals[inv.currency][b] += left
        counts[key][0] += 1
        names[inv.party_id] = inv.party_name
        if inv.due_date is None:
            counts[key][1] += 1
            no_due.append(OpenInvoiceRef(id=inv.id, document_number=inv.document_number or inv.draft_ref, due_date=None,
                                         outstanding=c.m(left, inv.currency)))
    unalloc = _unallocated(uow)
    parties = c.party_refs(uow, list(names.items()))
    rows = [
        AgeingRow(party=parties[pid], currency=cur, buckets=_buckets(dict(vals), cur), invoice_count=counts[(pid, cur)][0],
                  no_due_date_count=counts[(pid, cur)][1], unallocated_receipts=c.m(unalloc.get((pid, cur), c.ZERO), cur))
        for (pid, cur), vals in grouped.items()
    ]
    rows.sort(key=lambda r: (r.party.display_name.lower(), r.currency))
    return AgeingReport(as_of=as_of, time_zone=c.zone(uow), rows=rows,
                        totals=[_buckets(dict(v), cur) for cur, v in sorted(totals.items())], no_due_date_invoices=no_due)


def _count(uow: UnitOfWork, model: type, *conds: object) -> int:
    return int(uow.session.scalar(select(func.count()).select_from(model).where(*conds)) or 0)  # type: ignore[arg-type]


def summary(uow: UnitOfWork) -> FinanceSummary:
    from app.modules.finance.accounting import accounting_integration
    from app.modules.finance.gate import e_invoice_verified

    uow.actor.require(c.INVOICE_READ)
    today = c.today(uow)
    inv_scope = uow.repo(Invoice).clause("read")
    by_status = dict(uow.session.execute(
        select(Invoice.status, func.count()).where(inv_scope).group_by(Invoice.status)).all())
    blocked = _count(uow, Invoice, inv_scope, Invoice.status != InvoiceStatus.ISSUED.value,
                     Invoice.status != InvoiceStatus.CANCELLED.value, func.jsonb_array_length(Invoice.last_blockers) > 0)
    figures: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: c.ZERO))
    overdue_n = open_n = 0
    for inv, left in _open_issued(uow, today):
        open_n += 1
        figures[inv.currency]["receivable"] += left
        if inv.due_date is not None and inv.due_date < today:
            overdue_n += 1
            figures[inv.currency]["overdue"] += left
    unalloc_n = 0
    can_receipts = uow.actor.can(c.RECEIPT_READ)
    if can_receipts:
        for (_pid, cur), amount in _unallocated(uow).items():
            figures[cur]["unallocated"] += amount
        from app.modules.finance.receipts import unallocated_amounts

        rows = list(uow.session.scalars(select(Receipt).where(uow.repo(Receipt).clause("read"), Receipt.status == ReceiptStatus.RECORDED.value)))
        unalloc_n = sum(1 for v in unallocated_amounts(uow, rows).values() if v > 0)
    integ = accounting_integration(uow)
    sync_attention = _count(uow, AccountingSyncItem, AccountingSyncItem.company_id == uow.actor.company_id,
                            AccountingSyncItem.status.in_([SyncStatus.MISMATCH.value, SyncStatus.REJECTED.value]))
    sync_attention += _count(uow, AccountingExport, AccountingExport.company_id == uow.actor.company_id,
                             AccountingExport.status == "failed")
    return FinanceSummary(
        as_of=today,
        drafts=int(by_status.get(InvoiceStatus.DRAFT.value, 0)),
        pending_approval=int(by_status.get(InvoiceStatus.PENDING_APPROVAL.value, 0)),
        issue_blocked=blocked,
        issued_open=open_n,
        overdue=overdue_n,
        open_suggestions=_count(uow, InvoiceSuggestion, uow.repo(InvoiceSuggestion).clause("read"),
                                InvoiceSuggestion.status == SuggestionStatus.OPEN.value),
        unallocated_receipts=unalloc_n,
        margin_exceptions=_count(uow, MarginException, uow.repo(MarginException).clause("read"),
                                 MarginException.status == MarginExceptionStatus.OPEN.value),
        sync_attention=sync_attention,
        by_currency=[
            CurrencyFigure(currency=cur, receivable=c.m(v["receivable"], cur), overdue=c.m(v["overdue"], cur),  # type: ignore[arg-type]
                           unallocated=c.m(v["unallocated"], cur))
            for cur, v in sorted(figures.items())
        ],
        accounting_mode=integ.mode, accounting_state=integ.state,
        e_invoice_state="connected" if e_invoice_verified(uow) else "not_connected",
        tax_profiles_verified=_count(uow, TaxProfile, TaxProfile.company_id == uow.actor.company_id,
                                     TaxProfile.status == TaxProfileStatus.VERIFIED.value),
        capabilities=hub_capabilities(uow),
    )


def hub_capabilities(uow: UnitOfWork) -> dict[str, Capability]:
    keys = {
        "create_invoice": c.INVOICE_CREATE,
        "record_receipt": c.RECEIPT_CREATE,
        "allocate": c.ALLOCATION_CREATE,
        "read_receipts": c.RECEIPT_READ,
        "read_ageing": c.AGEING_READ,
        "run_export": c.EXPORT_RUN,
        "manage_configuration": c.CONFIG_MANAGE,
        "verify_tax_profile": c.TAX_PROFILE_APPROVE,
        "read_costs": "pricing.cost.read",
    }
    return {
        name: Capability(allowed=uow.actor.can(key), reason_code=None if uow.actor.can(key) else "permission_denied")
        for name, key in keys.items()
    }


def exception_items(uow: UnitOfWork) -> list[FinanceException]:
    """Blocked issues, overdue invoices, unallocated receipts, failed exports and reconciliation mismatches."""
    uow.actor.require(c.INVOICE_READ)
    out: list[FinanceException] = []
    today = c.today(uow)
    for inv in uow.session.scalars(select(Invoice).where(
            uow.repo(Invoice).clause("read"), Invoice.status.in_([InvoiceStatus.DRAFT.value, InvoiceStatus.PENDING_APPROVAL.value, InvoiceStatus.APPROVED.value]),
            func.jsonb_array_length(Invoice.last_blockers) > 0).order_by(Invoice.updated_at.desc()).limit(100)):
        out.append(FinanceException(kind="issue_blocked", ref=_ref(inv), party_name=inv.party_name,
                                    codes=list(inv.last_blockers), since=inv.updated_at))
    for inv, _left in _open_issued(uow, today):
        if inv.due_date is not None and inv.due_date < today:
            out.append(FinanceException(kind="overdue", ref=_ref(inv), party_name=inv.party_name,
                                        codes=[bucket_of(today, inv.due_date)], since=inv.due_date))
    if uow.actor.can(c.RECEIPT_READ):
        from app.modules.finance.receipts import unallocated_amounts

        rows = list(uow.session.scalars(select(Receipt).where(uow.repo(Receipt).clause("read"), Receipt.status == ReceiptStatus.RECORDED.value)
                                        .order_by(Receipt.received_on)))
        left = unallocated_amounts(uow, rows)
        for r in rows:
            if left.get(r.id, c.ZERO) > 0:
                out.append(FinanceException(kind="unallocated_receipt", party_name=r.party_name, codes=["unallocated"], since=r.received_on,
                                            ref=FinanceDocRef(id=r.id, kind="receipt", number=r.receipt_number, path=f"/finance/receipts/{r.id}")))
    for x in uow.session.scalars(select(AccountingExport).where(uow.repo(AccountingExport).clause("read"), AccountingExport.status == "failed")
                                 .order_by(AccountingExport.created_at.desc()).limit(20)):
        out.append(FinanceException(kind="sync_failed", party_name=None, codes=[x.error_code or "failed"], since=x.created_at,
                                    ref=FinanceDocRef(id=x.id, kind="accounting_export", number=x.export_number, path=f"/finance/accounting-sync?export={x.id}")))
    for item in uow.session.scalars(select(AccountingSyncItem).where(uow.repo(AccountingSyncItem).clause("read"),
                                                                     AccountingSyncItem.status.in_([SyncStatus.MISMATCH.value, SyncStatus.REJECTED.value]))):
        out.append(FinanceException(kind="sync_mismatch", party_name=None, codes=[item.mismatch_reason or item.status], since=item.updated_at,
                                    ref=FinanceDocRef(id=item.invoice_id, kind=item.doc_type, number=item.document_number,
                                                      path=f"/finance/{'credit-notes' if item.doc_type == 'credit_note' else 'invoices'}/{item.invoice_id}")))
    return out


def _ref(inv: Invoice) -> FinanceDocRef:
    base = "credit-notes" if inv.doc_type == DocType.CREDIT_NOTE.value else "invoices"
    return FinanceDocRef(id=inv.id, kind=inv.doc_type, number=inv.document_number or inv.draft_ref, path=f"/finance/{base}/{inv.id}")
