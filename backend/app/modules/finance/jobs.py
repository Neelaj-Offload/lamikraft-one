"""Scheduled finance sweeps (per active company, system actor, company time; idempotent through the ``*_notified_on``
stamps, so a rerun emits nothing new):

- ``finance.overdue_sweep``: an issued invoice past its due date with something outstanding emits
  ``finance.invoice.became_overdue`` once.
- ``finance.unallocated_sweep``: a recorded receipt still (partly) unallocated ``unallocated_after_days`` after it
  was received emits ``finance.receipt.unallocated_detected`` once.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.enums import DocType, InvoiceStatus, ReceiptStatus
from app.modules.finance.models import Invoice, Receipt
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork

OVERDUE_JOB = "finance.overdue_sweep"
UNALLOCATED_JOB = "finance.unallocated_sweep"


def sweep_overdue(uow: UnitOfWork) -> int:
    today = c.today(uow)
    rows = list(uow.session.scalars(
        select(Invoice).where(Invoice.company_id == uow.actor.company_id, Invoice.doc_type == DocType.INVOICE.value,
                              Invoice.status == InvoiceStatus.ISSUED.value, Invoice.due_date.is_not(None),
                              Invoice.due_date < today, Invoice.overdue_notified_on.is_(None))
        .order_by(Invoice.due_date, Invoice.document_number).with_for_update(skip_locked=True)))
    alloc = c.allocated_to_invoices(uow, [r.id for r in rows])
    emitted = 0
    for inv in rows:
        if Decimal(inv.total_amount) - alloc.get(inv.id, c.ZERO) <= 0:
            continue
        inv.overdue_notified_on = today
        uow.flush()
        uow.emit(ev.BECAME_OVERDUE, aggregate_id=inv.id, aggregate_version=inv.version, payload={
            "invoice_id": str(inv.id), "document_number": inv.document_number,
            "due_date": inv.due_date.isoformat() if inv.due_date else None})
        emitted += 1
    return emitted


def sweep_unallocated(uow: UnitOfWork) -> int:
    from app.platform.org.service import stored_or_default

    days = int(stored_or_default(uow, "finance_policy").unallocated_after_days)  # type: ignore[attr-defined]
    cutoff = c.today(uow) - timedelta(days=days)
    rows = list(uow.session.scalars(
        select(Receipt).where(Receipt.company_id == uow.actor.company_id, Receipt.status == ReceiptStatus.RECORDED.value,
                              Receipt.received_on <= cutoff, Receipt.unallocated_notified_on.is_(None))
        .order_by(Receipt.received_on, Receipt.receipt_number).with_for_update(skip_locked=True)))
    alloc = c.allocated_from_receipts(uow, [r.id for r in rows])
    emitted = 0
    for r in rows:
        if Decimal(r.amount) - alloc.get(r.id, c.ZERO) <= 0:
            continue
        r.unallocated_notified_on = c.today(uow)
        uow.flush()
        uow.emit(ev.RECEIPT_UNALLOCATED, aggregate_id=r.id, aggregate_version=r.version,
                 payload={"receipt_id": str(r.id), "receipt_number": r.receipt_number})
        emitted += 1
    return emitted


def overdue_sweep(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks.jobs import for_each_company

    return for_each_company(ctx, OVERDUE_JOB, sweep_overdue)


def unallocated_sweep(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.tasks.jobs import for_each_company

    return for_each_company(ctx, UNALLOCATED_JOB, sweep_unallocated)


JOBS = [
    JobDef(OVERDUE_JOB, overdue_sweep, queue="default", max_attempts=3),
    JobDef(UNALLOCATED_JOB, unallocated_sweep, queue="default", max_attempts=3),
]
SCHEDULES = [
    ScheduleDef(OVERDUE_JOB, OVERDUE_JOB, "interval", interval_seconds=900),
    ScheduleDef(UNALLOCATED_JOB, UNALLOCATED_JOB, "interval", interval_seconds=900),
]
