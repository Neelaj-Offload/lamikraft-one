"""The issue gate (operations.md §9): drafts are always allowed and labelled; issue is blocked with reasons until the
configuration is complete and a second person approved the current version; the number is assigned only at issue;
quantities never exceed what was delivered; issued documents are frozen; credit notes never exceed what is
creditable and settle the original first."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.finance import invoices
from app.modules.finance.models import Invoice, InvoiceLine, InvoiceStatusHistory
from app.modules.finance.schemas import CreditNoteCreate, CreditNoteLineIn
from app.platform.numbering.models import DocumentSequence
from tests.integration.finance.world import ANANYA, MEERA, SAHIL, FinWorld

pytestmark = pytest.mark.db


def _codes(gate: object) -> set[str]:
    return {b.code for b in gate.blockers}  # type: ignore[attr-defined]


def test_draft_allowed_issue_blocked_without_verified_tax_profile_and_number_assigned_only_at_issue(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("100")
    d = w.draft(challan_id=ids["challan_id"])
    # a draft: server-computed totals at the order price (100 × EUR 24), labelled, no number consumed
    assert (d.status.value, d.document_number, d.label) == ("draft", None, "Draft — not valid for trade")
    assert d.draft_ref.startswith("FD-") and d.total.amount == Decimal("2400.0000") and d.tax is None
    assert [ln.quantity for ln in d.lines] == [Decimal(100)] and d.lines[0].challan_line_id is not None
    assert {"not_approved", "company_identity_incomplete", "tax_profile_missing"} <= _codes(d.gate)
    assert not d.gate.can_issue and d.tax_status.value == "not_configured"

    w.act(ANANYA, d.id, "submit")
    w.act(SAHIL, d.id, "approve")
    blocked = w.act(ANANYA, d.id, "issue")
    assert blocked.issued is False
    assert {"company_identity_incomplete", "tax_profile_missing"} <= {b.code for b in blocked.blockers}
    assert blocked.detail.document_number is None and blocked.detail.status.value == "approved"
    assert blocked.detail.last_blockers and blocked.detail.history[-1].action == "issue_blocked"
    ev = w.events("finance.invoice.issue_blocked")[-1]
    assert set(ev.payload) - {"origin"} == {"invoice_id", "doc_type", "version", "blocker_codes"}  # ids and codes only
    fix = {b.code: b.fix_path for b in blocked.blockers}
    assert fix["company_identity_incomplete"] == "/settings/company"
    with w.system() as uow:  # no invoice number was consumed by the refused attempt
        assert uow.session.scalar(select(DocumentSequence.id).where(DocumentSequence.company_id == w.company_id,
                                                                    DocumentSequence.sequence_key == "finance.invoice")) is None

    # an unverified profile still blocks; an e-invoicing profile blocks until a verified provider exists (Demo: never)
    w.configure_identity()
    e_inv = w.verified_profile(requires_e_invoice=True, rate="18", code="GST-18")
    w.act(ANANYA, d.id, "reject", reason_code="change_tax")
    w.set_profile(d.id, e_inv)
    got = w.get(d.id)
    assert got.tax is not None and got.tax.amount == Decimal("432.0000") and got.total.amount == Decimal("2832.0000")
    w.act(ANANYA, d.id, "submit")
    w.act(SAHIL, d.id, "approve")
    blocked = w.act(ANANYA, d.id, "issue")
    assert blocked.issued is False and {b.code for b in blocked.blockers} == {"e_invoice_provider_not_verified"}

    # a verified profile without e-invoicing: issue assigns INV-2026-27-0001, the date and the due date
    plain = w.verified_profile()
    w.act(ANANYA, d.id, "reject", reason_code="change_tax")
    w.set_profile(d.id, plain)
    w.act(ANANYA, d.id, "submit")
    w.act(SAHIL, d.id, "approve")
    issued = w.act(ANANYA, d.id, "issue")
    assert issued.issued is True and issued.blockers == []
    inv = issued.detail
    assert inv.document_number == "INV-2026-27-0001" and inv.status.value == "issued" and inv.label is None
    assert inv.document_date == w.ctx.clock.now().date() and inv.due_date is not None
    assert (inv.due_date - inv.document_date).days == 30
    assert w.events("finance.invoice.issued")[-1].payload["document_number"] == "INV-2026-27-0001"


def test_approval_is_never_by_the_creator(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("10")
    d = w.draft(challan_id=ids["challan_id"])
    w.act(ANANYA, d.id, "submit")
    with pytest.raises(Forbidden) as exc:
        w.act(ANANYA, d.id, "approve")
    assert exc.value.code in ("creator_cannot_approve", "permission_denied")
    assert w.get(d.id).capabilities["approve"].allowed is False
    assert w.get(d.id, SAHIL).capabilities["approve"].allowed is True
    # the database refuses it too
    with w.system() as uow, pytest.raises(DBAPIError):
        with uow.session.begin_nested():
            uow.session.execute(update(Invoice).where(Invoice.id == d.id).values(approved_by=Invoice.owner_user_id))
    # sales hold no finance keys: the record is not found
    from app.core.errors import NotFound

    with pytest.raises((NotFound, Forbidden)):
        w.act(MEERA, d.id, "approve")


def test_invoiced_quantity_never_exceeds_delivered(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("100")
    w.configure_identity()
    profile = w.verified_profile()
    first = w.draft(challan_id=ids["challan_id"], tax_profile_id=profile)
    second = w.draft(challan_id=ids["challan_id"], tax_profile_id=profile)  # a second draft is allowed ...
    for d in (first, second):
        w.act(ANANYA, d.id, "submit")
        w.act(SAHIL, d.id, "approve")
    assert w.act(ANANYA, first.id, "issue").issued is True
    refused = w.act(ANANYA, second.id, "issue")  # ... but only one can be issued for the delivered 100
    assert refused.issued is False and {b.code for b in refused.blockers} == {"quantity_exceeds_delivered"}
    # and the challan has nothing left to draft
    with pytest.raises(Conflict) as exc:
        w.draft(challan_id=ids["challan_id"])
    assert exc.value.code == "nothing_to_invoice"
    # an order draft takes only delivered-but-not-invoiced quantities: none left
    with pytest.raises(Conflict):
        w.draft(sales_order_id=ids["order_id"])


def test_issued_documents_and_their_lines_are_frozen(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    inv = w.issued_invoice("50")
    with w.system() as uow:
        for stmt in (
            update(Invoice).where(Invoice.id == inv.id).values(total_amount=Decimal(1)),
            update(Invoice).where(Invoice.id == inv.id).values(document_number="INV-X"),
            update(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).values(quantity=Decimal(1)),
            text("DELETE FROM finance_invoice_line WHERE invoice_id = :i").bindparams(i=inv.id),
            text("UPDATE finance_invoice_status_history SET reason = 'x' WHERE invoice_id = :i").bindparams(i=inv.id),
        ):
            with pytest.raises(DBAPIError), uow.session.begin_nested():
                uow.session.execute(stmt)
    with pytest.raises(Conflict):
        with w.uow(ANANYA) as uow:
            from app.modules.finance.schemas import InvoiceUpdate

            invoices.update_invoice(uow, inv.id, InvoiceUpdate(expected_version=inv.version, notes="changed"))
    with w.system() as uow:
        history = list(uow.session.scalars(select(InvoiceStatusHistory.action).where(InvoiceStatusHistory.invoice_id == inv.id)))
    assert history == ["create", "submit", "approve", "issue"]


def test_credit_note_bounded_by_creditable_and_settles_the_original(fin_world: FinWorld) -> None:
    w = fin_world
    w.configure_identity()
    inv = w.issued_invoice("100")
    line = inv.lines[0]
    assert line.creditable_quantity == Decimal(100)
    with w.uow(ANANYA) as uow, pytest.raises(ValidationFailed):
        invoices.create_credit_note(uow, CreditNoteCreate(original_invoice_id=inv.id, reason_code="damaged",
                                                          lines=[CreditNoteLineIn(invoice_line_id=line.id, quantity=Decimal(101))]))
    with w.uow(ANANYA) as uow:
        cn = invoices.create_credit_note(uow, CreditNoteCreate(original_invoice_id=inv.id, reason_code="damaged",
                                                               lines=[CreditNoteLineIn(invoice_line_id=line.id, quantity=Decimal(10))]))
        cn_id = cn.id
    w.act(ANANYA, cn_id, "submit")
    w.act(SAHIL, cn_id, "approve")
    out = w.act(ANANYA, cn_id, "issue")
    assert out.issued is True and out.detail.document_number == "CN-2026-27-0001"
    assert out.detail.total.amount == Decimal("240.0000") and out.detail.allocated.amount == Decimal("240.0000")
    original = w.get(inv.id)
    assert original.outstanding is not None and original.outstanding.amount == Decimal("2160.0000")
    assert original.credited.amount == Decimal("240.0000") and original.lines[0].creditable_quantity == Decimal(90)
    assert any(r.kind == "credit_note" for r in original.related)
    # a second credit note beyond what is left is refused at drafting
    with w.uow(ANANYA) as uow, pytest.raises(ValidationFailed):
        invoices.create_credit_note(uow, CreditNoteCreate(original_invoice_id=inv.id, reason_code="damaged",
                                                          lines=[CreditNoteLineIn(invoice_line_id=line.id, quantity=Decimal(91))]))
    assert w.events("finance.credit_note.issued")[-1].payload["original_invoice_id"] == str(inv.id)


def test_cancel_and_invalid_transitions(fin_world: FinWorld) -> None:
    w = fin_world
    ids = w.delivered("5")
    d = w.draft(challan_id=ids["challan_id"])
    from app.core.errors import InvalidTransition

    with pytest.raises(InvalidTransition):
        w.act(ANANYA, d.id, "issue")
    with pytest.raises(ValidationFailed):
        w.act(ANANYA, d.id, "cancel")  # reason required
    out = w.act(ANANYA, d.id, "cancel", reason_code="duplicate")
    assert out.status.value == "cancelled"
    # the suggestion is open again (the draft no longer covers the challan)
    from app.modules.finance import suggestions

    with w.uow(ANANYA) as uow:
        assert [s.challan_id for s in suggestions.list_suggestions(uow)] == [ids["challan_id"]]

