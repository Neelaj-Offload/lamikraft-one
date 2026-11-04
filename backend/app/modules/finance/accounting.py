"""The accounting handoff: export issued invoices and credit notes through the CSV or Demo adapter, then reconcile
what the accounting side acknowledged against what was exported. Integration status ``accounting`` stays Demo /
not connected until a live adapter exists (BUILD_STATE §5 #3); nothing here claims a connection.

A document is exported at most once by a completed batch (a failed batch exports nothing). A missing account code
blocks the documents that need it; a batch with nothing exportable fails with ``finance.accounting_export.failed``.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import Conflict, ValidationFailed
from app.core.http.pagination import MAX_LIMIT, Page
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.adapters import ADAPTERS
from app.modules.finance.adapters.base import AccountCodes, JournalDocument
from app.modules.finance.enums import (
    DocType,
    ExportStatus,
    InvoiceStatus,
    ReconciliationStatus,
    SyncStatus,
)
from app.modules.finance.models import AccountingExport, AccountingSyncItem, Invoice
from app.modules.finance.schemas import (
    AccountingStatus,
    ExportBlocked,
    ExportRead,
    ExportRequest,
    ReconcileRequest,
    SyncItemRead,
)
from app.platform.authz.stepup import require_step_up
from app.platform.uow import UnitOfWork


def accounting_integration(uow: UnitOfWork):  # type: ignore[no-untyped-def]
    from app.platform.system.service import effective_statuses

    return next(s for s in effective_statuses(uow) if s.key == "accounting")


def _mapping(uow: UnitOfWork) -> dict[str, str | None]:
    from app.platform.org.service import stored_or_default

    return stored_or_default(uow, "finance_account_mapping").model_dump()


def missing_mapping(mapping: dict[str, str | None]) -> list[str]:
    return [k for k in ("receivable_account", "sales_account") if not mapping.get(k)]


def _exported_ids(uow: UnitOfWork) -> select:  # type: ignore[valid-type]
    return (
        select(AccountingSyncItem.invoice_id)
        .join(AccountingExport, AccountingExport.id == AccountingSyncItem.export_id)
        .where(AccountingExport.company_id == uow.actor.company_id, AccountingExport.status == ExportStatus.COMPLETED.value)
    )


def _candidates(uow: UnitOfWork, data: ExportRequest | None = None) -> list[Invoice]:
    stmt = select(Invoice).where(
        Invoice.company_id == uow.actor.company_id, Invoice.status == InvoiceStatus.ISSUED.value,
        Invoice.id.not_in(_exported_ids(uow)),
    )
    if data is not None and data.period_from:
        stmt = stmt.where(Invoice.document_date >= data.period_from)
    if data is not None and data.period_to:
        stmt = stmt.where(Invoice.document_date <= data.period_to)
    return list(uow.session.scalars(stmt.order_by(Invoice.document_date, Invoice.doc_type, Invoice.document_number)))


def _blocked_reason(inv: Invoice, mapping: dict[str, str | None]) -> str | None:
    if missing_mapping(mapping):
        return "account_mapping_missing"
    if inv.tax_amount and not mapping.get("tax_account"):
        return "tax_account_missing"
    if inv.doc_type == DocType.CREDIT_NOTE.value and not (mapping.get("sales_returns_account") or mapping.get("sales_account")):
        return "sales_returns_account_missing"
    return None


def run_export(uow: UnitOfWork, data: ExportRequest) -> AccountingExport:
    from app.modules.parties.models import Party

    uow.actor.require(c.EXPORT_RUN)
    require_step_up(uow, c.EXPORT_RUN)
    uow.advisory_xact_lock("finance.accounting_export", str(uow.actor.company_id))
    adapter = ADAPTERS[data.adapter.value]
    mapping = _mapping(uow)
    candidates = _candidates(uow, data)
    blocked: list[dict[str, str]] = []
    ready: list[Invoice] = []
    for inv in candidates:
        reason = _blocked_reason(inv, mapping)
        if reason:
            blocked.append({"invoice_id": str(inv.id), "document_number": inv.document_number or "", "reason": reason})
        else:
            ready.append(inv)
    x = AccountingExport(
        id=uuid.uuid7(), company_id=uow.actor.company_id, export_number="pending", adapter=adapter.kind,
        status=ExportStatus.COMPLETED.value, period_from=data.period_from, period_to=data.period_to,
        document_count=len(ready), blocked_count=len(blocked), blocked_documents=blocked,
        actor_user_id=uow.actor.user_id, simulated=adapter.kind == "demo",
    )
    x.export_number = uow.allocate_number("finance.accounting_export", document_date=c.today(uow),
                                          resource_type="finance.accounting_export", resource_id=x.id)
    if not ready:
        x.status = ExportStatus.FAILED.value
        x.error_code = "account_mapping_missing" if blocked and missing_mapping(mapping) else ("documents_blocked" if blocked else "nothing_to_export")
        uow.add(x)
        uow.flush()
        uow.emit(ev.EXPORT_FAILED, aggregate_id=x.id, payload={"export_id": str(x.id), "adapter": x.adapter, "error_code": x.error_code})
        return x
    numbers = dict(uow.session.execute(select(Party.id, Party.party_number).where(Party.id.in_({i.party_id for i in ready}))).tuples().all())
    docs = [
        JournalDocument(
            invoice_id=str(i.id), doc_type=i.doc_type, document_number=i.document_number or "", document_date=i.document_date,  # type: ignore[arg-type]
            party_name=i.party_name, party_number=numbers.get(i.party_id), currency=i.currency,
            subtotal=Decimal(i.subtotal_amount), tax=Decimal(i.tax_amount) if i.tax_amount is not None else None,
            total=Decimal(i.total_amount), customer_reference=i.customer_reference,
        )
        for i in ready
    ]
    codes = AccountCodes(receivable=mapping["receivable_account"], sales=mapping["sales_account"],  # type: ignore[arg-type]
                         tax=mapping.get("tax_account"), sales_returns=mapping.get("sales_returns_account"))
    result = adapter.export(x.export_number, docs, codes)
    x.content = result.content.decode("utf-8")
    x.content_sha256 = hashlib.sha256(result.content).hexdigest()
    if result.acknowledgement_ref:
        x.acknowledgement_ref, x.acknowledged_at = result.acknowledgement_ref, uow.now()
    uow.add(x)
    uow.flush()
    for inv in ready:
        ack = result.acknowledgements.get(inv.document_number or "")
        uow.add(AccountingSyncItem(
            company_id=uow.actor.company_id, export_id=x.id, invoice_id=inv.id, doc_type=inv.doc_type,
            document_number=inv.document_number or "", currency=inv.currency, total_amount=inv.total_amount,
            status=SyncStatus.ACKNOWLEDGED.value if ack else SyncStatus.EXPORTED.value,
            external_ref=ack[0] if ack else None, acknowledged_total=ack[1] if ack else None,
        ))
    uow.flush()
    uow.emit(ev.EXPORT_COMPLETED, aggregate_id=x.id, payload={"export_id": str(x.id), "adapter": x.adapter, "error_code": None})
    uow.audit("finance.accounting_export.completed", resource_type="finance.accounting_export", resource_id=x.id,
              resource_label=x.export_number)
    return x


def reconcile(uow: UnitOfWork, export_id: uuid.UUID, data: ReconcileRequest) -> AccountingExport:
    """Compare exported documents with the accounting side's references and totals; list every mismatch."""
    uow.actor.require(c.EXPORT_RUN)
    x = uow.repo(AccountingExport).get(export_id, for_update=True)
    if x.status != ExportStatus.COMPLETED.value:
        raise Conflict("A failed export has nothing to reconcile", code="export_failed")
    items = list(uow.session.scalars(select(AccountingSyncItem).where(AccountingSyncItem.export_id == x.id)
                                     .order_by(AccountingSyncItem.document_number)))
    if data.lines is None:
        if not x.simulated:
            raise ValidationFailed("Enter the accounting side's references and totals to reconcile a CSV export",
                                   code="validation_failed", errors=[{"loc": ["lines"], "code": "required"}])
        acks = {i.document_number: (i.external_ref, i.acknowledged_total) for i in items}
    else:
        known = {i.document_number for i in items}
        unknown = sorted({ln.document_number for ln in data.lines} - known)
        if unknown:
            raise ValidationFailed("These documents are not in this export", code="validation_failed",
                                   errors=[{"loc": ["lines"], "code": "unknown_document", "document_number": n} for n in unknown])
        acks = {ln.document_number: (ln.external_ref, Decimal(ln.total)) for ln in data.lines}
    mismatches = 0
    for i in items:
        ref, total = acks.get(i.document_number, (None, None))
        if ref is None or total is None:
            i.status, i.mismatch_reason = SyncStatus.MISMATCH.value, "missing_in_accounting"
            mismatches += 1
        elif Decimal(total) != Decimal(i.total_amount):
            i.status, i.mismatch_reason, i.external_ref, i.acknowledged_total = SyncStatus.MISMATCH.value, "total_differs", ref, total
            mismatches += 1
        else:
            i.status, i.mismatch_reason, i.external_ref, i.acknowledged_total = SyncStatus.ACKNOWLEDGED.value, None, ref, total
    x.reconciliation_status = (ReconciliationStatus.MISMATCH if mismatches else ReconciliationStatus.MATCHED).value
    x.reconciled_at = uow.now()
    uow.flush()
    uow.emit(ev.EXPORT_RECONCILED, aggregate_id=x.id, payload={
        "export_id": str(x.id), "adapter": x.adapter, "reconciliation_status": x.reconciliation_status})
    return x


# ---- reads -----------------------------------------------------------------------------------------------------------
def export_read(uow: UnitOfWork, x: AccountingExport, *, with_items: bool = True) -> ExportRead:
    items = list(uow.session.scalars(select(AccountingSyncItem).where(AccountingSyncItem.export_id == x.id)
                                     .order_by(AccountingSyncItem.document_number))) if with_items else []
    people = c.users(uow, [x.actor_user_id])
    return ExportRead(
        id=x.id, export_number=x.export_number, adapter=x.adapter, status=x.status, error_code=x.error_code,  # type: ignore[arg-type]
        period_from=x.period_from, period_to=x.period_to, document_count=x.document_count, blocked_count=x.blocked_count,
        content_sha256=x.content_sha256, acknowledgement_ref=x.acknowledgement_ref, acknowledged_at=x.acknowledged_at,
        reconciliation_status=x.reconciliation_status, reconciled_at=x.reconciled_at, simulated=x.simulated,  # type: ignore[arg-type]
        actor=people.get(x.actor_user_id) if x.actor_user_id else None, created_at=x.created_at,
        items=[SyncItemRead(id=i.id, invoice_id=i.invoice_id, doc_type=i.doc_type, document_number=i.document_number,  # type: ignore[arg-type]
                            total=c.m(i.total_amount, i.currency), status=i.status, external_ref=i.external_ref,  # type: ignore[arg-type]
                            acknowledged_total=c.money(i.acknowledged_total, i.currency), mismatch_reason=i.mismatch_reason)
               for i in items],
        blocked=[ExportBlocked(invoice_id=uuid.UUID(b["invoice_id"]), document_number=b["document_number"], reason=b["reason"])
                 for b in (x.blocked_documents or [])],
    )


def get_export(uow: UnitOfWork, export_id: uuid.UUID) -> ExportRead:
    uow.actor.require(c.INVOICE_READ)
    return export_read(uow, uow.repo(AccountingExport).get(export_id))


def export_content(uow: UnitOfWork, export_id: uuid.UUID) -> tuple[str, bytes]:
    uow.actor.require(c.EXPORT_RUN)
    x = uow.repo(AccountingExport).get(export_id)
    if x.content is None:
        raise Conflict("This export produced no file", code="export_failed")
    uow.audit("finance.accounting_export.downloaded", resource_type="finance.accounting_export", resource_id=x.id,
              resource_label=x.export_number)
    return f"{x.export_number}-journal.csv", x.content.encode("utf-8")


def list_exports(uow: UnitOfWork, *, limit: int = 20, offset: int = 0) -> Page[ExportRead]:
    uow.actor.require(c.INVOICE_READ)
    conds = [uow.repo(AccountingExport).clause("read")]
    from sqlalchemy import func

    total = uow.session.scalar(select(func.count(AccountingExport.id)).where(*conds)) or 0
    limit, offset = max(1, min(limit, MAX_LIMIT)), max(0, offset)
    rows = list(uow.session.scalars(select(AccountingExport).where(*conds).order_by(AccountingExport.created_at.desc(), AccountingExport.id.desc())
                                    .limit(limit).offset(offset)))
    return Page[ExportRead](items=[export_read(uow, r, with_items=False) for r in rows], total=int(total), limit=limit, offset=offset)


def status(uow: UnitOfWork) -> AccountingStatus:
    uow.actor.require(c.INVOICE_READ)
    integ = accounting_integration(uow)
    mapping = _mapping(uow)
    last = uow.session.scalars(select(AccountingExport).where(uow.repo(AccountingExport).clause("read"))
                               .order_by(AccountingExport.created_at.desc(), AccountingExport.id.desc()).limit(1)).first()
    return AccountingStatus(
        integration_key="accounting", mode=integ.mode, state=integ.state,
        label="Demo — not connected" if integ.mode == "demo" else integ.label_text,
        adapters=sorted(ADAPTERS), mapping_complete=not missing_mapping(mapping), missing_mapping=missing_mapping(mapping),
        last_export=export_read(uow, last) if last else None, pending_documents=len(_candidates(uow)),
    )
