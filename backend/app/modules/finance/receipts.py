"""Receipts (``RCPT-{fy}-NNNN``) and allocations.

Allocations are append-only. An allocation locks the source (receipt or credit note) and then the invoice
(``SELECT ... FOR UPDATE``, the module's lock order) and re-reads both sums inside the lock, so concurrent
allocations can never take a receipt past its amount or an invoice past its total: over-allocation is impossible,
not merely unlikely (proven by a barrier test). Same party and same currency only (cross-currency allocation is
future scope). A correction is a reversal row (negated amount, ``reverses_allocation_id`` UNIQUE: at most once).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http.capabilities import Capability
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import quantize_money
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.enums import AllocationSource, DocType, InvoiceStatus, ReceiptStatus
from app.modules.finance.invoices import allocation_reads
from app.modules.finance.models import Allocation, Invoice, Receipt
from app.modules.finance.schemas import (
    AllocationCreate,
    AllocationReverse,
    CreditAllocationCreate,
    OpenInvoiceRef,
    ReceiptCreate,
    ReceiptDetail,
    ReceiptFilters,
    ReceiptReverse,
    ReceiptSummary,
)
from app.platform.authz.stepup import require_step_up
from app.platform.uow import UnitOfWork


def _emit_alloc(uow: UnitOfWork, name: str, a: Allocation) -> None:
    uow.emit(
        name,
        aggregate_id=a.invoice_id,
        payload={
            "allocation_id": str(a.id),
            "invoice_id": str(a.invoice_id),
            "receipt_id": str(a.receipt_id) if a.receipt_id else None,
            "credit_note_id": str(a.credit_note_id) if a.credit_note_id else None,
            "reverses_allocation_id": str(a.reverses_allocation_id) if a.reverses_allocation_id else None,
        },
    )


def _emit_receipt(uow: UnitOfWork, name: str, r: Receipt, reason_code: str | None = None) -> None:
    uow.emit(name, aggregate_id=r.id, aggregate_version=r.version, payload={
        "receipt_id": str(r.id), "receipt_number": r.receipt_number, "party_id": str(r.party_id), "reason_code": reason_code})


# =====================================================================================================
# receipts
# =====================================================================================================
def record_receipt(uow: UnitOfWork, data: ReceiptCreate, *, origin: str = "user", origin_ref: str | None = None) -> Receipt:
    from app.modules.parties import service as parties

    uow.actor.require(c.RECEIPT_CREATE)
    if uow.actor.user_id is None:
        raise ValidationFailed(code="validation_failed", errors=[{"loc": ["actor"], "code": "user_required"}])
    party = parties.get_party_ref(uow, data.party_id)  # 404 outside the actor's party scope
    if data.received_on > c.today(uow):
        raise ValidationFailed(code="validation_failed", errors=[{"loc": ["received_on"], "code": "in_the_future"}])
    r = Receipt(
        id=uuid.uuid7(), company_id=uow.actor.company_id, receipt_number="pending", party_id=party.id,
        party_name=party.display_name, amount=quantize_money(Decimal(data.amount), data.currency),
        currency=data.currency, received_on=data.received_on, method=data.method.value, reference=data.reference,
        bank_account_label=data.bank_account_label, status=ReceiptStatus.RECORDED.value,
        owner_user_id=uow.actor.user_id, branch_id=c.branch_for(uow),
        notes=data.notes, origin=origin, origin_ref=origin_ref,
    )
    r.receipt_number = uow.allocate_number("finance.receipt", document_date=data.received_on, resource_type="finance.receipt", resource_id=r.id)
    r.search_text = " ".join(x for x in (r.receipt_number, r.party_name, r.reference) if x).lower()
    uow.add(r)
    uow.flush()
    _emit_receipt(uow, ev.RECEIPT_RECORDED, r)
    uow.audit("finance.receipt.recorded", resource_type="finance.receipt", resource_id=r.id, resource_label=r.receipt_number)
    return r


def reverse_receipt(uow: UnitOfWork, receipt_id: uuid.UUID, data: ReceiptReverse) -> Receipt:
    """A void is a reversal: the receipt is kept (status reversed) and its live allocations are reversed with it."""
    uow.actor.require(c.RECEIPT_REVERSE)
    require_step_up(uow, c.RECEIPT_REVERSE)
    r = uow.repo(Receipt).get(receipt_id, "reverse", for_update=True)
    uow.expect_version(r, data.expected_version)
    live = _live_allocations(uow, Allocation.receipt_id == r.id)
    for a in live:
        uow.lock(Invoice, [a.invoice_id])
        _reverse_row(uow, a, data.reason_code)
    r.status, r.reversed_by, r.reversed_at = ReceiptStatus.REVERSED.value, uow.actor.user_id, uow.now()
    r.reverse_reason_code, r.reverse_reason = data.reason_code, data.reason
    uow.flush()
    _emit_receipt(uow, ev.RECEIPT_REVERSED, r, data.reason_code)
    uow.audit("finance.receipt.reversed", resource_type="finance.receipt", resource_id=r.id, resource_label=r.receipt_number)
    return r


# =====================================================================================================
# allocations
# =====================================================================================================
def _live_allocations(uow: UnitOfWork, cond: ColumnElement[bool]) -> list[Allocation]:
    reversed_ids = select(Allocation.reverses_allocation_id).where(Allocation.reverses_allocation_id.is_not(None))
    return list(uow.session.scalars(
        select(Allocation).where(Allocation.company_id == uow.actor.company_id, cond,
                                 Allocation.reverses_allocation_id.is_(None), Allocation.id.not_in(reversed_ids))
        .order_by(Allocation.id)))


def _target(uow: UnitOfWork, invoice_id: uuid.UUID, party_id: uuid.UUID, currency: str) -> Invoice:
    """The invoice row, locked (after the source row), checked for kind, state, party and currency."""
    inv = uow.session.scalars(
        select(Invoice).where(Invoice.id == invoice_id, uow.repo(Invoice).clause("read")).with_for_update()
    ).first()
    if inv is None:
        raise NotFound(code="not_found", resource_type="finance.invoice")
    if inv.doc_type != DocType.INVOICE.value or inv.status != InvoiceStatus.ISSUED.value:
        raise Conflict("Only an issued invoice can receive an allocation", code="invoice_not_issued")
    if inv.party_id != party_id:
        raise Conflict("The receipt and the invoice belong to different parties", code="party_mismatch")
    if inv.currency != currency:
        raise Conflict("Cross-currency allocation is not supported", code="currency_mismatch")
    return inv


def _check_room(source_available: Decimal, invoice_outstanding: Decimal, amount: Decimal, currency: str) -> None:
    if amount > source_available:
        raise Conflict("That is more than is left to allocate", code="over_allocation", side="source",
                       available={"amount": format(source_available, "f"), "currency": currency})
    if amount > invoice_outstanding:
        raise Conflict("That is more than the invoice still has outstanding", code="over_allocation", side="invoice",
                       available={"amount": format(invoice_outstanding, "f"), "currency": currency})


def allocate_receipt(uow: UnitOfWork, receipt_id: uuid.UUID, data: AllocationCreate) -> Allocation:
    uow.actor.require(c.ALLOCATION_CREATE)
    r = uow.repo(Receipt).get(receipt_id, for_update=True)  # lock 1: the source
    if r.status != ReceiptStatus.RECORDED.value:
        raise Conflict("A reversed receipt cannot be allocated", code="receipt_reversed")
    inv = _target(uow, data.invoice_id, r.party_id, r.currency)  # lock 2: the invoice
    amount = quantize_money(Decimal(data.amount), r.currency)
    available = Decimal(r.amount) - c.allocated_from_receipts(uow, [r.id]).get(r.id, c.ZERO)
    _check_room(available, c.outstanding(uow, inv), amount, r.currency)
    a = Allocation(company_id=uow.actor.company_id, source_type=AllocationSource.RECEIPT.value, receipt_id=r.id,
                   invoice_id=inv.id, amount=amount, currency=r.currency, allocated_on=c.today(uow),
                   actor_user_id=uow.actor.user_id, created_at=uow.now())
    uow.add(a)
    uow.flush()
    _emit_alloc(uow, ev.ALLOCATION_CREATED, a)
    return a


def allocate_credit_note(uow: UnitOfWork, credit_note_id: uuid.UUID, data: CreditAllocationCreate) -> Allocation:
    uow.actor.require(c.ALLOCATION_CREATE)
    cn = uow.repo(Invoice).get(credit_note_id, for_update=True)
    if cn.doc_type != DocType.CREDIT_NOTE.value or cn.status != InvoiceStatus.ISSUED.value:
        raise Conflict("Only an issued credit note can be allocated", code="credit_note_not_issued")
    return _allocate_cn(uow, cn, data.invoice_id, quantize_money(Decimal(data.amount), cn.currency))


def _allocate_cn(uow: UnitOfWork, cn: Invoice, invoice_id: uuid.UUID, amount: Decimal) -> Allocation:
    inv = _target(uow, invoice_id, cn.party_id, cn.currency)
    available = Decimal(cn.total_amount) - c.allocated_from_credit_notes(uow, [cn.id]).get(cn.id, c.ZERO)
    _check_room(available, c.outstanding(uow, inv), amount, cn.currency)
    a = Allocation(company_id=uow.actor.company_id, source_type=AllocationSource.CREDIT_NOTE.value, credit_note_id=cn.id,
                   invoice_id=inv.id, amount=amount, currency=cn.currency, allocated_on=c.today(uow),
                   actor_user_id=uow.actor.user_id, created_at=uow.now())
    uow.add(a)
    uow.flush()
    _emit_alloc(uow, ev.ALLOCATION_CREATED, a)
    return a


def auto_allocate_credit_note(uow: UnitOfWork, cn: Invoice) -> Allocation | None:
    """On issue a credit note settles its original invoice first, up to what that invoice still has outstanding."""
    if cn.original_invoice_id is None:
        return None
    original = uow.session.scalars(select(Invoice).where(Invoice.id == cn.original_invoice_id).with_for_update()).first()
    if original is None or original.status != InvoiceStatus.ISSUED.value:
        return None
    amount = min(Decimal(cn.total_amount), c.outstanding(uow, original))
    if amount <= 0:
        return None
    return _allocate_cn(uow, cn, original.id, amount)


def _reverse_row(uow: UnitOfWork, a: Allocation, reason_code: str) -> Allocation:
    rev = Allocation(company_id=uow.actor.company_id, source_type=a.source_type, receipt_id=a.receipt_id,
                     credit_note_id=a.credit_note_id, invoice_id=a.invoice_id, amount=-Decimal(a.amount),
                     currency=a.currency, reverses_allocation_id=a.id, allocated_on=c.today(uow),
                     actor_user_id=uow.actor.user_id, reason_code=reason_code, created_at=uow.now())
    uow.add(rev)
    uow.flush()
    _emit_alloc(uow, ev.ALLOCATION_REVERSED, rev)
    return rev


def reverse_allocation(uow: UnitOfWork, allocation_id: uuid.UUID, data: AllocationReverse) -> Allocation:
    uow.actor.require(c.ALLOCATION_CREATE)
    a = uow.repo(Allocation).get(allocation_id)
    if a.reverses_allocation_id is not None:
        raise Conflict("A reversal cannot be reversed", code="allocation_is_reversal")
    if a.receipt_id:
        uow.repo(Receipt).get(a.receipt_id, for_update=True)
    else:
        uow.lock(Invoice, [a.credit_note_id])  # type: ignore[list-item]
    uow.lock(Invoice, [a.invoice_id])
    already = uow.session.scalar(select(Allocation.id).where(Allocation.reverses_allocation_id == a.id))
    if already:
        raise Conflict("This allocation is already reversed", code="allocation_reversed")
    return _reverse_row(uow, a, data.reason_code)


# =====================================================================================================
# reads
# =====================================================================================================
def _summary(r: Receipt, allocated: Decimal, parties: dict, people: dict) -> ReceiptSummary:
    live = allocated if r.status == ReceiptStatus.RECORDED.value else c.ZERO
    return ReceiptSummary(
        id=r.id, receipt_number=r.receipt_number, party=parties[r.party_id], amount=c.m(r.amount, r.currency),
        allocated=c.m(live, r.currency),
        unallocated=c.m(Decimal(r.amount) - live if r.status == ReceiptStatus.RECORDED.value else c.ZERO, r.currency),
        received_on=r.received_on, method=r.method, reference=r.reference,  # type: ignore[arg-type]
        status=ReceiptStatus(r.status), owner=people.get(r.owner_user_id),
    )


def open_invoices(uow: UnitOfWork, party_id: uuid.UUID, currency: str) -> list[OpenInvoiceRef]:
    rows = list(uow.session.scalars(
        select(Invoice).where(uow.repo(Invoice).clause("read"), Invoice.party_id == party_id, Invoice.currency == currency,
                              Invoice.doc_type == DocType.INVOICE.value, Invoice.status == InvoiceStatus.ISSUED.value)
        .order_by(Invoice.due_date.nulls_last(), Invoice.document_number)))
    alloc = c.allocated_to_invoices(uow, [r.id for r in rows])
    out = []
    for inv in rows:
        left = Decimal(inv.total_amount) - alloc.get(inv.id, c.ZERO)
        if left > 0:
            out.append(OpenInvoiceRef(id=inv.id, document_number=inv.document_number or inv.draft_ref, due_date=inv.due_date,
                                      outstanding=c.m(left, inv.currency)))
    return out


def receipt_detail(uow: UnitOfWork, r: Receipt) -> ReceiptDetail:
    allocated = c.allocated_from_receipts(uow, [r.id]).get(r.id, c.ZERO)
    rows = list(uow.session.scalars(select(Allocation).where(Allocation.company_id == uow.actor.company_id, Allocation.receipt_id == r.id)
                                    .order_by(Allocation.created_at, Allocation.id)))
    people = c.users(uow, [r.owner_user_id])
    parties = c.party_refs(uow, [(r.party_id, r.party_name)])
    base = _summary(r, allocated, parties, people)
    recorded = r.status == ReceiptStatus.RECORDED.value
    can_alloc = recorded and uow.actor.can(c.ALLOCATION_CREATE) and Decimal(r.amount) - allocated > 0
    caps = {k: Capability(**v) for k, v in uow.repo(Receipt).capabilities(r, ["reverse"]).items()}
    caps["allocate"] = Capability(allowed=can_alloc, reason_code=None if can_alloc else (
        "receipt_reversed" if not recorded else "permission_denied" if not uow.actor.can(c.ALLOCATION_CREATE) else "fully_allocated"))
    return ReceiptDetail(
        **base.model_dump(), bank_account_label=r.bank_account_label, notes=r.notes,
        allocations=allocation_reads(uow, rows),
        open_invoices=open_invoices(uow, r.party_id, r.currency) if recorded else [],
        reversed_at=r.reversed_at, reverse_reason_code=r.reverse_reason_code, version=r.version, capabilities=caps,
    )


def get_receipt(uow: UnitOfWork, receipt_id: uuid.UUID) -> ReceiptDetail:
    uow.actor.require(c.RECEIPT_READ)
    return receipt_detail(uow, uow.repo(Receipt).get(receipt_id))


def unallocated_amounts(uow: UnitOfWork, rows: list[Receipt]) -> dict[uuid.UUID, Decimal]:
    alloc = c.allocated_from_receipts(uow, [r.id for r in rows])
    return {r.id: Decimal(r.amount) - alloc.get(r.id, c.ZERO) for r in rows if r.status == ReceiptStatus.RECORDED.value}


def list_receipts(uow: UnitOfWork, f: ReceiptFilters, *, limit: int = 50, offset: int = 0) -> Page[ReceiptSummary]:
    uow.actor.require(c.RECEIPT_READ)
    conds: list[ColumnElement[bool]] = [uow.repo(Receipt).clause("read")]
    if f.party_id:
        conds.append(Receipt.party_id == f.party_id)
    if f.status:
        conds.append(Receipt.status.in_([s.value for s in f.status]))
    if f.q:
        for t in tokens(f.q):
            conds.append(Receipt.search_text.ilike(contains_pattern(t.lower()), escape=LIKE_ESCAPE))
    if f.unallocated_only:
        alloc = select(func.coalesce(func.sum(Allocation.amount), 0)).where(Allocation.receipt_id == Receipt.id).correlate(Receipt).scalar_subquery()
        conds += [Receipt.status == ReceiptStatus.RECORDED.value, Receipt.amount - alloc > 0]
    total = uow.session.scalar(select(func.count(Receipt.id)).where(*conds)) or 0
    limit, offset = max(1, min(limit, MAX_LIMIT)), max(0, offset)
    rows = list(uow.session.scalars(select(Receipt).where(*conds).order_by(Receipt.received_on.desc(), Receipt.receipt_number.desc())
                                    .limit(limit).offset(offset)))
    alloc_map = c.allocated_from_receipts(uow, [r.id for r in rows])
    people = c.users(uow, [r.owner_user_id for r in rows])
    parties = c.party_refs(uow, [(r.party_id, r.party_name) for r in rows])
    return Page[ReceiptSummary](items=[_summary(r, alloc_map.get(r.id, c.ZERO), parties, people) for r in rows],
                                total=int(total), limit=limit, offset=offset)
