"""Shared helpers for the finance module: company time, money arithmetic (line-level HALF_UP to the minor unit), user
and party references, outstanding/allocated figures and quantity bookkeeping over issued documents."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.clock import local_date
from app.core.money import Money, quantize_money
from app.modules.finance.enums import DocType, InvoiceStatus
from app.modules.finance.models import Allocation, Invoice, InvoiceLine
from app.modules.finance.schemas import FinancePartyRef, FinanceUserRef
from app.platform.identity.models import AppUser
from app.platform.org.models import Company
from app.platform.uow import UnitOfWork

ZERO = Decimal(0)
ISSUED = InvoiceStatus.ISSUED.value

INVOICE_READ = "finance.invoice.read"
INVOICE_CREATE = "finance.invoice.create"
INVOICE_UPDATE = "finance.invoice.update"
INVOICE_APPROVE = "finance.invoice.approve"
INVOICE_ISSUE = "finance.invoice.issue"
RECEIPT_READ = "finance.receipt.read"
RECEIPT_CREATE = "finance.receipt.create"
RECEIPT_REVERSE = "finance.receipt.reverse"
ALLOCATION_CREATE = "finance.allocation.create"
AGEING_READ = "finance.ageing.read"
EXPORT_RUN = "finance.accounting_export.run"
CONFIG_MANAGE = "finance.configuration.manage"
TAX_PROFILE_APPROVE = "finance.tax_profile.approve"

#: the label every draft carries while configuration blocks issue (BUILD_STATE §5 #4, #9)
DRAFT_LABEL = "Draft — not valid for trade"


def zone(uow: UnitOfWork) -> str:
    return (
        uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
        or "Asia/Kolkata"
    )


def today(uow: UnitOfWork) -> date:
    return local_date(uow.now(), zone(uow))


def money(amount: Decimal | None, currency: str) -> Money | None:
    return None if amount is None else Money(amount=Decimal(amount), currency=currency)  # type: ignore[arg-type]


def m(amount: Decimal, currency: str) -> Money:
    return Money(amount=Decimal(amount), currency=currency)  # type: ignore[arg-type]


def line_amount(quantity: Decimal, unit_price: Decimal, currency: str) -> Decimal:
    """Line-level HALF_UP to the currency's minor unit (conventions: rounding policy)."""
    return quantize_money(Decimal(quantity) * Decimal(unit_price), currency)


def tax_of(amount: Decimal, rate_percent: Decimal | None, currency: str) -> Decimal | None:
    if rate_percent is None:
        return None
    return quantize_money(Decimal(amount) * Decimal(rate_percent) / Decimal(100), currency)


def users(uow: UnitOfWork, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, FinanceUserRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = uow.session.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted))).all()
    return {r[0]: FinanceUserRef(id=r[0], display_name=r[1]) for r in rows}


def party_refs(uow: UnitOfWork, pairs: Sequence[tuple[uuid.UUID, str]]) -> dict[uuid.UUID, FinancePartyRef]:
    """Party references without a party-scope check (finance holds company-wide party read; names are snapshots)."""
    from app.modules.parties.models import Party

    ids = {p for p, _ in pairs}
    numbers: dict[uuid.UUID, str] = {}
    if ids:
        numbers = dict(
            uow.session.execute(select(Party.id, Party.party_number).where(Party.id.in_(ids))).tuples().all()
        )
    return {
        pid: FinancePartyRef(id=pid, party_number=numbers.get(pid), display_name=name) for pid, name in pairs
    }


# ---- allocations ----------------------------------------------------------------------------------------------------
def allocated_to_invoices(uow: UnitOfWork, invoice_ids: Sequence[uuid.UUID], *, as_of: date | None = None) -> dict[uuid.UUID, Decimal]:
    if not invoice_ids:
        return {}
    stmt = (
        select(Allocation.invoice_id, func.coalesce(func.sum(Allocation.amount), 0))
        .where(Allocation.company_id == uow.actor.company_id, Allocation.invoice_id.in_(list(invoice_ids)))
        .group_by(Allocation.invoice_id)
    )
    if as_of is not None:
        stmt = stmt.where(Allocation.allocated_on <= as_of)
    return {k: Decimal(v) for k, v in uow.session.execute(stmt).tuples().all()}


def allocated_from_receipts(uow: UnitOfWork, receipt_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not receipt_ids:
        return {}
    stmt = (
        select(Allocation.receipt_id, func.coalesce(func.sum(Allocation.amount), 0))
        .where(Allocation.company_id == uow.actor.company_id, Allocation.receipt_id.in_(list(receipt_ids)))
        .group_by(Allocation.receipt_id)
    )
    return {k: Decimal(v) for k, v in uow.session.execute(stmt).tuples().all() if k is not None}


def allocated_from_credit_notes(uow: UnitOfWork, cn_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not cn_ids:
        return {}
    stmt = (
        select(Allocation.credit_note_id, func.coalesce(func.sum(Allocation.amount), 0))
        .where(Allocation.company_id == uow.actor.company_id, Allocation.credit_note_id.in_(list(cn_ids)))
        .group_by(Allocation.credit_note_id)
    )
    return {k: Decimal(v) for k, v in uow.session.execute(stmt).tuples().all() if k is not None}


def outstanding(uow: UnitOfWork, inv: Invoice) -> Decimal:
    return Decimal(inv.total_amount) - allocated_to_invoices(uow, [inv.id]).get(inv.id, ZERO)


# ---- quantities over issued documents ----------------------------------------------------------------------------
def _net_issued_qty(uow: UnitOfWork, column: Any, ids: Sequence[uuid.UUID], *, exclude_invoice: uuid.UUID | None) -> dict[uuid.UUID, Decimal]:
    """Σ issued invoice quantity − Σ issued credit-note quantity per ``column`` value (an SO line or challan line).
    Credit-note lines carry the credited invoice line's links."""
    if not ids:
        return {}
    rows = uow.session.execute(
        select(column, Invoice.doc_type, func.sum(InvoiceLine.quantity))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            InvoiceLine.company_id == uow.actor.company_id,
            column.in_(list(ids)),
            Invoice.status == ISSUED,
            *((Invoice.id != exclude_invoice,) if exclude_invoice else ()),
        )
        .group_by(column, Invoice.doc_type)
    ).all()
    out: dict[uuid.UUID, Decimal] = {}
    for key, doc_type, qty in rows:
        delta = Decimal(qty) if doc_type == DocType.INVOICE.value else -Decimal(qty)
        out[key] = out.get(key, ZERO) + delta
    return out


def invoiced_by_so_line(uow: UnitOfWork, ids: Sequence[uuid.UUID], *, exclude_invoice: uuid.UUID | None = None) -> dict[uuid.UUID, Decimal]:
    return _net_issued_qty(uow, InvoiceLine.so_line_id, ids, exclude_invoice=exclude_invoice)


def invoiced_by_challan_line(uow: UnitOfWork, ids: Sequence[uuid.UUID], *, exclude_invoice: uuid.UUID | None = None) -> dict[uuid.UUID, Decimal]:
    return _net_issued_qty(uow, InvoiceLine.challan_line_id, ids, exclude_invoice=exclude_invoice)


def credited_by_invoice_line(uow: UnitOfWork, line_ids: Sequence[uuid.UUID], *, exclude_invoice: uuid.UUID | None = None) -> dict[uuid.UUID, Decimal]:
    """Issued credit-note quantity per credited invoice line."""
    if not line_ids:
        return {}
    rows = uow.session.execute(
        select(InvoiceLine.credited_line_id, func.sum(InvoiceLine.quantity))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            InvoiceLine.company_id == uow.actor.company_id,
            InvoiceLine.credited_line_id.in_(list(line_ids)),
            Invoice.status == ISSUED,
            *((Invoice.id != exclude_invoice,) if exclude_invoice else ()),
        )
        .group_by(InvoiceLine.credited_line_id)
    ).all()
    return {k: Decimal(v) for k, v in rows if k is not None}


def lines_of(uow: UnitOfWork, inv: Invoice) -> list[InvoiceLine]:
    return list(
        uow.session.scalars(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)
        )
    )


def recompute(lines: Sequence[InvoiceLine], currency: str, rate_percent: Decimal | None) -> tuple[Decimal, Decimal | None, Decimal]:
    """(subtotal, tax or None, total) from the lines (each line rounded first)."""
    subtotal = sum((line_amount(ln.quantity, ln.unit_price, currency) for ln in lines), ZERO)
    if rate_percent is None:
        return subtotal, None, subtotal
    tax = sum(
        (tax_of(line_amount(ln.quantity, ln.unit_price, currency), rate_percent, currency) or ZERO for ln in lines),
        ZERO,
    )
    return subtotal, tax, subtotal + tax
