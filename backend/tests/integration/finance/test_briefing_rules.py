"""Slice-5 briefing families through the real ``tasks.rules`` consumer: invoice suggestions (one per issued Outward
challan, replay-safe), approvals (never offered to the creator), overdue invoices and unallocated receipts (from the
scheduled sweeps, once each), and Ananya's briefing holding the fixture's unallocated Maison receipt — with nothing
finance-related in a sales briefing."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.modules.briefings import service as briefings
from app.modules.finance import jobs, suggestions
from app.modules.finance.models import InvoiceSuggestion
from app.modules.tasks.models import Issue, Task, TaskCandidate
from app.platform.events.models import DomainEvent
from app.seed.context import D0
from tests.integration.finance.world import ANANYA, MEERA, PRIYA, SAHIL, FinWorld
from tests.support import drain

pytestmark = pytest.mark.db


def _issues(w: FinWorld, family: str) -> list[Issue]:
    with w.system() as uow:
        return list(uow.session.scalars(select(Issue).where(Issue.company_id == w.company_id, Issue.family == family).order_by(Issue.created_at)))


def _open_tasks(w: FinWorld, issue: Issue) -> list[Task]:
    with w.system() as uow:
        return list(uow.session.scalars(select(Task).where(Task.issue_id == issue.id, Task.state.in_(["open", "in_progress"]))))


def _candidates(w: FinWorld, task: Task) -> set:
    with w.system() as uow:
        return set(uow.session.scalars(select(TaskCandidate.user_id).where(TaskCandidate.task_id == task.id)))


def test_issued_challan_suggests_once_and_drafting_closes_it(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("100")
    assert w.count(InvoiceSuggestion, InvoiceSuggestion.challan_id == ids["challan_id"]) == 1
    # re-deliver the challan event to the finance consumer: still one suggestion, one event
    with w.system() as uow:
        event = uow.session.scalars(select(DomainEvent).where(DomainEvent.event_type == "challans.challan.issued",
                                                              DomainEvent.aggregate_id == ids["challan_id"])).one()
        suggestions.on_challan_issued(uow, event)
        suggestions.on_challan_issued(uow, event)
    assert w.count(InvoiceSuggestion, InvoiceSuggestion.challan_id == ids["challan_id"]) == 1
    assert len(w.events("finance.invoice_suggestion.created")) == 1
    [issue] = _issues(w, "fin.invoice_suggestions")
    [task] = _open_tasks(w, issue)
    assert task.kind == "draft_invoice" and w.ref(ANANYA) in _candidates(w, task)
    assert w.ref(MEERA) not in _candidates(w, task)
    with w.uow(ANANYA) as uow:
        [s] = suggestions.list_suggestions(uow)
    d = w.draft(suggestion_id=s.id)
    drain()
    [issue] = _issues(w, "fin.invoice_suggestions")
    assert issue.state != "open" and _open_tasks(w, issue) == []
    assert d.related and {r.kind for r in d.related} == {"sales_order", "challan"}


def test_approval_task_is_never_offered_to_the_creator(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("10")
    d = w.draft(challan_id=ids["challan_id"])
    w.act(ANANYA, d.id, "submit")
    drain()
    [issue] = _issues(w, "fin.invoice_approvals")
    [task] = _open_tasks(w, issue)
    people = _candidates(w, task)
    assert task.kind == "approve_invoice" and w.ref(ANANYA) not in people and {w.ref(SAHIL), w.ref(PRIYA)} <= people
    w.act(SAHIL, d.id, "approve")
    w.act(ANANYA, d.id, "issue")  # blocked: configuration missing -> the creator is told
    drain()
    [issue] = _issues(w, "fin.invoice_approvals")
    [task] = _open_tasks(w, issue)
    assert task.kind == "resolve_issue_blockers" and task.owner_user_id == w.ref(ANANYA)


def test_overdue_and_unallocated_sweeps_emit_once_and_feed_ananyas_briefing(fin_world: FinWorld) -> None:
    from app.seed.world.finance import seed_finance

    w = fin_world
    # consumers read "today" from the shared test clock (D0), so the invoice is issued in the past: D-10, due D-5
    w.at(D0 - timedelta(days=10))
    w.configure_identity()
    inv = w.issued_invoice("10", payment_due_days=5)
    seed_finance(w.ctx)  # RCPT for Maison EUR 2,400 received D-4, unallocated (fixture); its sweep runs at D0 06:00
    w.at(D0)
    drain()
    with w.system() as uow:
        assert jobs.sweep_overdue(uow) == 1
        assert jobs.sweep_unallocated(uow) == 0  # the seed already flagged the Maison receipt
    with w.system() as uow:
        assert jobs.sweep_overdue(uow) == 0  # once per invoice
    drain()
    assert [e.payload["invoice_id"] for e in w.events("finance.invoice.became_overdue")] == [str(inv.id)]
    assert len(w.events("finance.receipt.unallocated_detected")) == 1
    [overdue] = _issues(w, "fin.overdue_invoices")
    [task] = _open_tasks(w, overdue)
    assert task.kind == "chase_overdue" and task.owner_user_id == w.ref(ANANYA)
    [unalloc] = _issues(w, "fin.unallocated_receipts")
    assert [t.kind for t in _open_tasks(w, unalloc)] == ["allocate_receipt"]

    with w.uow(ANANYA) as uow:
        view = briefings.get_today(uow)
    families = {i.family for i in view.items}
    assert {"fin.overdue_invoices", "fin.unallocated_receipts"} <= families
    receipt_item = next(i for i in view.items if i.family == "fin.unallocated_receipts")
    assert "Maison" in receipt_item.title
    with w.uow(MEERA) as uow:  # nothing finance-related reaches sales
        assert not {i.family for i in briefings.get_today(uow).items} & {f for f in families if f.startswith("fin.")}

    # paying the invoice closes the overdue issue
    r = w.receipt("240")
    w.allocate(r.id, inv.id, "240")
    drain()
    [overdue] = _issues(w, "fin.overdue_invoices")
    assert overdue.state != "open" and _open_tasks(w, overdue) == []
