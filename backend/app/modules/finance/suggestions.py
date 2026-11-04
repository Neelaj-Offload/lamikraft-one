"""Invoice suggestions: the ``finance.invoice_suggestion`` consumer of ``challans.challan.issued`` (events.md §2).

An issued **Outward** challan to a **customer** party suggests a draft invoice, once per challan (UNIQUE challan;
replays and duplicate deliveries change nothing). Nothing is drafted automatically: finance drafts from the
suggestion (``POST /finance/invoices`` with ``suggestion_id``) or dismisses it with a reason. Legacy/imported
challans (``origin=migration|import``) are not suggested.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Conflict
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance.enums import SuggestionStatus
from app.modules.finance.models import InvoiceSuggestion
from app.modules.finance.schemas import SuggestionDismiss, SuggestionRead
from app.platform.uow import UnitOfWork


def _emit(uow: UnitOfWork, name: str, s: InvoiceSuggestion) -> None:
    uow.emit(name, aggregate_id=s.id, aggregate_version=s.version, payload={
        "suggestion_id": str(s.id), "challan_id": str(s.challan_id),
        "sales_order_id": str(s.sales_order_id) if s.sales_order_id else None, "party_id": str(s.party_id)})


def on_challan_issued(uow: UnitOfWork, event: Any) -> None:
    from app.modules.challans.models import Challan

    payload = event.payload or {}
    if payload.get("origin") in ("migration", "import"):
        return
    challan_id = uuid.UUID(str(payload.get("challan_id") or event.aggregate_id))
    ch = uow.session.get(Challan, challan_id)
    if ch is None or ch.company_id != uow.actor.company_id:
        return
    if ch.challan_type != "outward" or ch.destination_type != "customer" or ch.party_id is None or ch.status not in ("issued", "closed"):
        return
    row_id = uuid.uuid7()
    now = uow.now()
    inserted = uow.session.execute(
        pg_insert(InvoiceSuggestion)
        .values(id=row_id, company_id=uow.actor.company_id, challan_id=ch.id, challan_number=ch.challan_number,
                sales_order_id=ch.sales_order_id, party_id=ch.party_id, party_name=ch.destination_party,
                status=SuggestionStatus.OPEN.value, branch_id=ch.branch_id if hasattr(ch, "branch_id") else None,
                source_event_id=event.id, version=1, created_at=now, updated_at=now)
        .on_conflict_do_nothing(constraint="uq_finance_invoice_suggestion_challan")
        .returning(InvoiceSuggestion.id)
    ).first()
    if inserted is None:
        return
    s = uow.session.get(InvoiceSuggestion, row_id)
    assert s is not None
    _emit(uow, ev.SUGGESTION_CREATED, s)


def _read(s: InvoiceSuggestion, parties: dict) -> SuggestionRead:
    return SuggestionRead(id=s.id, challan_id=s.challan_id, challan_number=s.challan_number, sales_order_id=s.sales_order_id,
                          party=parties[s.party_id], status=SuggestionStatus(s.status), invoice_id=s.invoice_id,
                          created_at=s.created_at, version=s.version)


def list_suggestions(uow: UnitOfWork, *, status: SuggestionStatus | None = SuggestionStatus.OPEN) -> list[SuggestionRead]:
    uow.actor.require(c.INVOICE_READ)
    conds = [uow.repo(InvoiceSuggestion).clause("read")]
    if status is not None:
        conds.append(InvoiceSuggestion.status == status.value)
    rows = list(uow.session.scalars(select(InvoiceSuggestion).where(*conds).order_by(InvoiceSuggestion.created_at.desc()).limit(200)))
    parties = c.party_refs(uow, [(r.party_id, r.party_name) for r in rows])
    return [_read(r, parties) for r in rows]


def dismiss(uow: UnitOfWork, suggestion_id: uuid.UUID, data: SuggestionDismiss) -> SuggestionRead:
    uow.actor.require(c.INVOICE_CREATE)
    s = uow.repo(InvoiceSuggestion).get(suggestion_id, for_update=True)
    uow.expect_version(s, data.expected_version)
    if s.status != SuggestionStatus.OPEN.value:
        raise Conflict("Only an open suggestion can be dismissed", code="suggestion_not_open")
    s.status, s.dismissed_by, s.dismiss_reason_code = SuggestionStatus.DISMISSED.value, uow.actor.user_id, data.reason_code
    uow.flush()
    _emit(uow, ev.SUGGESTION_DISMISSED, s)
    return _read(s, c.party_refs(uow, [(s.party_id, s.party_name)]))
