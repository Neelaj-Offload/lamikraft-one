"""Quality inspections and supply in the shortage state:

- ``ops.qc``: a receipt of a QC-required product requests an inspection (task for operations, soft-due at the end of
  the shift); deciding it closes the task; the result rule (accepted + rejected = inspected) and the reason rules;
- late supply: an open PO line for a short product appears in the shortage's ``caused_by`` and the shortage resolves
  when the goods are received;
- replay safety: re-delivering the procurement / quality events to every consumer changes nothing."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import ValidationFailed
from app.modules.inventory.models import ShortageState, StockPosting
from app.modules.quality import service as quality
from app.modules.quality.schemas import InspectionDecision
from app.modules.tasks.models import Issue, Task
from app.platform.events.models import DomainEvent
from tests.integration.inventory.world import assert_ledger_consistent
from tests.integration.procurement.world import MEERA, RAVI, PqlWorld

pytestmark = pytest.mark.db


def test_qc_family_and_decision_rules(pql_world: PqlWorld) -> None:
    w = pql_world
    po_id = w.ref("PO_KAVERI")
    grn = w.receive(po_id, (1, "20", "WB-2612-C"))
    [insp] = w.inspections(grn.id)
    w.drain()
    [issue] = w.issues("ops.qc")
    [task] = w.open_tasks(issue)
    assert task.kind == "inspect" and task.queue_code == "operations" and task.due_kind == "soft"
    assert task.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)  # end of today's shift, 18:30 IST
    assert task.title == f"Inspect LK-WB-1800 from {grn.grn_number} line 1"
    with w.uow(RAVI) as uow:
        detail = quality.get_inspection(uow, insp.id)
        assert detail.capabilities["decide"].allowed and len(detail.suggested_checklist) == 4
        with pytest.raises(ValidationFailed) as sums:
            quality.decide_inspection(uow, insp.id, InspectionDecision(
                expected_version=insp.version, qty_accepted=Decimal(15), qty_rejected=Decimal(4)))
        assert sums.value.extra["errors"][0]["code"] == "results_do_not_add_up"
    with w.uow(RAVI) as uow, pytest.raises(ValidationFailed) as reason:
        quality.decide_inspection(uow, insp.id, InspectionDecision(
            expected_version=insp.version, qty_accepted=Decimal(15), qty_rejected=Decimal(5)))
    assert reason.value.extra["errors"][0]["code"] == "reason_required"
    decided = w.decide(insp.id, "20")
    assert decided.status == "passed" and decided.posting_id is not None
    assert w.postings("qc_inspection", insp.id) == 1
    w.drain()
    [issue] = w.issues("ops.qc")
    assert w.open_tasks(issue) == [] and issue.state != "open"
    assert_ledger_consistent(w)


def test_open_po_line_is_a_cause_of_the_shortage_until_received(pql_world: PqlWorld) -> None:
    w = pql_world
    order_id = w.order(MEERA, w.won_quote(MEERA, "NORDHAUS", ("OAK_TRAY", "700")))
    w.reserve(MEERA, order_id)  # 600 granted, 100 short
    w.drain()
    with w.system() as uow:
        s = uow.session.scalars(select(ShortageState).where(ShortageState.company_id == w.company_id,
                                                            ShortageState.product_id == w.ref("OAK_TRAY"))).one()
        assert s.status == "open" and Decimal(s.shortfall_qty) == 100
        assert all(c["type"] == "orders.sales_order_line" for c in s.caused_by)
    po_id = w.issued_po(("OAK_TRAY", "120", "300"), expected=date(2026, 10, 14))
    [line] = w.po_lines(po_id)
    w.drain()
    with w.system() as uow:
        s = uow.session.get(ShortageState, s.id)
        assert {"type": "procurement.purchase_order_line", "id": str(line.id)} in s.caused_by  # type: ignore[union-attr]
    w.receive(po_id, (1, "120", None))  # trays need no QC: available at once
    w.drain()
    with w.system() as uow:
        s = uow.session.get(ShortageState, s.id)
        assert s.status == "resolved" and s.caused_by == []  # type: ignore[union-attr]
    assert_ledger_consistent(w)


def test_replayed_procurement_events_have_single_effect(pql_world: PqlWorld) -> None:
    w = pql_world
    grn = w.receive(w.ref("PO_KAVERI"), (1, "10", "WB-2612-D"))
    w.decide(w.inspections(grn.id)[0].id, "8", "2")
    w.drain()

    def counts() -> tuple[int, int, int, int]:
        with w.system() as uow:
            return (
                int(uow.session.scalar(select(func.count()).select_from(Issue).where(Issue.company_id == w.company_id)) or 0),
                int(uow.session.scalar(select(func.count()).select_from(Task).where(Task.company_id == w.company_id)) or 0),
                int(uow.session.scalar(select(func.count()).select_from(StockPosting)
                                       .where(StockPosting.company_id == w.company_id)) or 0),
                int(uow.session.scalar(select(func.coalesce(func.sum(ShortageState.version), 0))
                                       .where(ShortageState.company_id == w.company_id)) or 0),
            )

    before = counts()
    from app.modules.inventory.shortages import handle_refresh
    from app.modules.logistics.packing_lists import handle_staleness
    from app.modules.tasks.rules.consumer import handle

    with w.system() as uow:
        events = list(uow.session.scalars(select(DomainEvent).where(
            DomainEvent.company_id == w.company_id,
            DomainEvent.event_type.like("procurement.%") | DomainEvent.event_type.like("quality.%"))))
    assert {e.event_type for e in events} >= {"procurement.goods_receipt.posted", "quality.inspection.failed"}
    for _ in range(2):
        for e in events:
            with w.system() as uow:
                handle(uow, e)
                handle_refresh(uow, e)
                handle_staleness(uow, e)
    assert counts() == before
    assert_ledger_consistent(w)
