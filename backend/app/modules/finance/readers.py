"""Source readers for tasks, briefings and the agent: ids, numbers, names, states and dates. Money facts appear only
on finance records whose read permission is a finance key (``MoneyFact``, rendered to permitted users); margin
exceptions never carry margin figures. Visibility follows the resource policies (an invisible record reads as None).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.errors import NotFound
from app.modules.finance import common as c
from app.modules.finance.enums import (
    DocType,
    InvoiceStatus,
    MarginExceptionStatus,
    ReceiptStatus,
    SuggestionStatus,
)
from app.modules.finance.models import AccountingExport, Invoice, InvoiceSuggestion, MarginException, Receipt
from app.modules.finance.policies import invoice_label, invoice_path
from app.platform.sources import MoneyFact, SourceFacts
from app.platform.uow import UnitOfWork


def _get(uow: UnitOfWork, model: type, record_id: uuid.UUID):  # type: ignore[no-untyped-def]
    try:
        return uow.repo(model).get(record_id)
    except NotFound:
        return None


def read_invoice(uow: UnitOfWork, invoice_id: uuid.UUID) -> SourceFacts | None:
    inv = _get(uow, Invoice, invoice_id)
    if inv is None:
        return None
    left = c.outstanding(uow, inv) if inv.status == InvoiceStatus.ISSUED.value else None
    today = c.today(uow)
    overdue = bool(inv.doc_type == DocType.INVOICE.value and inv.status == InvoiceStatus.ISSUED.value and inv.due_date
                   and inv.due_date < today and left and left > 0)
    money = [MoneyFact(amount=format(Decimal(inv.total_amount), "f"), currency=inv.currency)]
    if left is not None:
        money.append(MoneyFact(amount=format(left, "f"), currency=inv.currency))
    return SourceFacts(
        source_type="finance.invoice", source_id=inv.id, version=inv.version, label=invoice_label(inv),
        status=inv.status, owner_user_id=inv.owner_user_id, branch_id=inv.branch_id, required_permission=c.INVOICE_READ,
        canonical_path=invoice_path(inv),
        is_closed=inv.status == InvoiceStatus.CANCELLED.value or (inv.status == InvoiceStatus.ISSUED.value and (left is None or left <= 0)),
        updated_at=inv.updated_at,
        facts={
            "number": inv.document_number or inv.draft_ref, "draft_ref": inv.draft_ref, "doc_type": inv.doc_type,
            "party_name": inv.party_name, "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "overdue": overdue, "blockers": list(inv.last_blockers or []), "approved": inv.approved_by is not None,
            "approved_by": str(inv.approved_by) if inv.approved_by else None,
            "outstanding_positive": bool(left and left > 0),
        },
        money=money,
    )


def read_receipt(uow: UnitOfWork, receipt_id: uuid.UUID) -> SourceFacts | None:
    r = _get(uow, Receipt, receipt_id)
    if r is None:
        return None
    left = Decimal(r.amount) - c.allocated_from_receipts(uow, [r.id]).get(r.id, c.ZERO) if r.status == ReceiptStatus.RECORDED.value else c.ZERO
    return SourceFacts(
        source_type="finance.receipt", source_id=r.id, version=r.version, label=f"{r.receipt_number} · {r.party_name}",
        status=r.status, owner_user_id=r.owner_user_id, branch_id=r.branch_id, required_permission=c.RECEIPT_READ,
        canonical_path=f"/finance/receipts/{r.id}", is_closed=left <= 0, updated_at=r.updated_at,
        facts={"receipt_number": r.receipt_number, "party_name": r.party_name, "received_on": r.received_on.isoformat(),
               "unallocated_positive": left > 0},
        money=[MoneyFact(amount=format(left, "f"), currency=r.currency)],
    )


def read_suggestion(uow: UnitOfWork, suggestion_id: uuid.UUID) -> SourceFacts | None:
    s = _get(uow, InvoiceSuggestion, suggestion_id)
    if s is None:
        return None
    return SourceFacts(
        source_type="finance.invoice_suggestion", source_id=s.id, version=s.version,
        label=f"{s.challan_number} · {s.party_name}", status=s.status, owner_user_id=None, branch_id=s.branch_id,
        required_permission=c.INVOICE_READ, canonical_path=f"/finance/invoices?view=suggestions&challan={s.challan_id}",
        is_closed=s.status != SuggestionStatus.OPEN.value, updated_at=s.updated_at,
        facts={"challan_number": s.challan_number, "party_name": s.party_name, "challan_id": str(s.challan_id)},
    )


def read_margin_exception(uow: UnitOfWork, exception_id: uuid.UUID) -> SourceFacts | None:
    m = _get(uow, MarginException, exception_id)
    if m is None:
        return None
    return SourceFacts(
        source_type="finance.margin_exception", source_id=m.id, version=m.version,
        label=f"{m.quote_number} · {m.party_name}", status=m.status, owner_user_id=None, branch_id=None,
        required_permission=c.INVOICE_READ, canonical_path=f"/sales/quotes/{m.quote_id}",
        is_closed=m.status != MarginExceptionStatus.OPEN.value, updated_at=m.updated_at,
        # ids and names only: never revenue, cost or the margin percentage
        facts={"quote_number": m.quote_number, "party_name": m.party_name, "revision_no": m.revision_no,
               "quote_owner_id": str(m.owner_user_id)},
    )


def read_export(uow: UnitOfWork, export_id: uuid.UUID) -> SourceFacts | None:
    x = _get(uow, AccountingExport, export_id)
    if x is None:
        return None
    attention = x.status == "failed" or x.reconciliation_status == "mismatch"
    if x.status == "failed":
        # a failed batch exported nothing; it stops needing attention once a later batch completed
        from sqlalchemy import select

        later = uow.session.scalar(select(AccountingExport.id).where(
            AccountingExport.company_id == x.company_id, AccountingExport.status == "completed",
            AccountingExport.id > x.id).limit(1))  # uuid7: later ids sort after
        attention = later is None
    return SourceFacts(
        source_type="finance.accounting_export", source_id=x.id, version=None, label=x.export_number,
        status=x.status, owner_user_id=x.actor_user_id, branch_id=None, required_permission=c.INVOICE_READ,
        canonical_path=f"/finance/accounting-sync?export={x.id}", is_closed=not attention, updated_at=x.updated_at,
        facts={"export_number": x.export_number, "adapter": x.adapter, "error_code": x.error_code,
               "reconciliation_status": x.reconciliation_status, "simulated": x.simulated},
    )


READERS = {
    "finance.invoice": read_invoice,
    "finance.receipt": read_receipt,
    "finance.invoice_suggestion": read_suggestion,
    "finance.margin_exception": read_margin_exception,
    "finance.accounting_export": read_export,
}
