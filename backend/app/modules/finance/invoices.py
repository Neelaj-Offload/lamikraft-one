"""Invoices and credit notes: drafts (from an issued delivery challan, from an order's delivered quantity, or manual),
edits while a draft, credit notes against an issued invoice, the approval and issue transitions, reads.

Totals are always server-computed (line-level HALF_UP to the minor unit; tax only from the chosen tax profile). The
number is assigned only in the issue transaction (``INV-{fy}-NNNN`` / ``CN-{fy}-NNNN``); a blocked issue is recorded
(history, ``finance.invoice.issue_blocked``) and answered 409 ``issue_blocked`` with the blockers.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import ColumnElement, exists, func, or_, select

from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.core.http.capabilities import Capability, TransitionRead
from app.core.http.pagination import MAX_LIMIT, Page
from app.core.money import quantize_unit_price
from app.core.text import LIKE_ESCAPE, contains_pattern, tokens
from app.modules.finance import common as c
from app.modules.finance import events as ev
from app.modules.finance import gate
from app.modules.finance.enums import (
    DocType,
    InvoiceAction,
    InvoiceStatus,
    SuggestionStatus,
    TaxProfileStatus,
    TaxStatus,
)
from app.modules.finance.models import (
    Allocation,
    Invoice,
    InvoiceLine,
    InvoiceStatusHistory,
    InvoiceSuggestion,
    Receipt,
    TaxProfile,
)
from app.modules.finance.schemas import (
    AllocationRead,
    CreditNoteCreate,
    FinanceDocRef,
    GateBlocker,
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilters,
    InvoiceHistoryRead,
    InvoiceLineIn,
    InvoiceLineRead,
    InvoiceSummary,
    InvoiceTransition,
    InvoiceUpdate,
)
from app.platform.authz.stepup import require_step_up
from app.platform.uow import UnitOfWork

S = InvoiceStatus
#: (from status, action) -> to status (anything else: 409 invalid_transition with allowed_transitions)
TRANSITIONS: dict[tuple[str, str], str] = {
    (S.DRAFT.value, "submit"): S.PENDING_APPROVAL.value,
    (S.PENDING_APPROVAL.value, "approve"): S.APPROVED.value,
    (S.PENDING_APPROVAL.value, "reject"): S.DRAFT.value,
    (S.APPROVED.value, "reject"): S.DRAFT.value,
    (S.APPROVED.value, "issue"): S.ISSUED.value,
    (S.DRAFT.value, "cancel"): S.CANCELLED.value,
    (S.PENDING_APPROVAL.value, "cancel"): S.CANCELLED.value,
    (S.APPROVED.value, "cancel"): S.CANCELLED.value,
}
REASON_REQUIRED = frozenset({"reject", "cancel"})
#: the permission action each transition needs on the record
ACTION_PERMISSION = {"submit": "update", "approve": "approve", "reject": "approve", "issue": "issue", "cancel": "update"}
TRANSITION_EVENTS = {"submit": ev.SUBMITTED, "approve": ev.APPROVED, "reject": ev.REJECTED, "cancel": ev.CANCELLED}


class IssueResult(BaseModel):
    issued: bool
    blockers: list[GateBlocker]
    detail: InvoiceDetail


# =====================================================================================================
# helpers
# =====================================================================================================
def _history(uow: UnitOfWork, inv: Invoice, action: InvoiceAction, frm: str, to: str, *, reason_code: str | None = None,
             reason: str | None = None, blockers: list[str] | None = None) -> None:
    uow.add(
        InvoiceStatusHistory(
            company_id=uow.actor.company_id,
            invoice_id=inv.id,
            action=action.value,
            from_status=frm,
            to_status=to,
            actor_user_id=uow.actor.user_id,
            reason_code=reason_code,
            reason=reason,
            blocker_codes=list(blockers or []),
            occurred_at=uow.now(),
            invoice_version=inv.version,
        )
    )
    uow.flush()


def _emit(uow: UnitOfWork, name: str, inv: Invoice, **payload: Any) -> None:
    base: dict[str, Any] = {"invoice_id": str(inv.id)}
    if name != ev.BECAME_OVERDUE:
        base["doc_type"] = inv.doc_type
    uow.emit(name, aggregate_id=inv.id, aggregate_version=inv.version, payload={**base, **payload})


def _search_text(inv: Invoice) -> str:
    return " ".join(x for x in (inv.draft_ref, inv.document_number, inv.party_name, inv.customer_reference) if x).lower()


def _profile(uow: UnitOfWork, profile_id: uuid.UUID | None) -> TaxProfile | None:
    if profile_id is None:
        return None
    p = uow.session.get(TaxProfile, profile_id)
    if p is None or p.company_id != uow.actor.company_id:
        raise ValidationFailed(code="validation_failed", errors=[{"loc": ["tax_profile_id"], "code": "not_found"}])
    return p


def _apply_tax(inv: Invoice, lines: list[InvoiceLine], profile: TaxProfile | None) -> None:
    rate = Decimal(profile.rate_percent) if profile else None
    for ln in lines:
        ln.amount = c.line_amount(ln.quantity, ln.unit_price, inv.currency)
        ln.tax_rate_percent = rate
        ln.tax_amount = c.tax_of(ln.amount, rate, inv.currency)
    subtotal, tax, total = c.recompute(lines, inv.currency, rate)
    inv.subtotal_amount, inv.tax_amount, inv.total_amount = subtotal, tax, total
    inv.tax_profile_id = profile.id if profile else None
    inv.tax_status = (
        TaxStatus.NOT_CONFIGURED.value
        if profile is None
        else TaxStatus.VERIFIED.value
        if profile.status == TaxProfileStatus.VERIFIED.value
        else TaxStatus.UNVERIFIED.value
    )


def _new(uow: UnitOfWork, doc_type: DocType, *, party_id: uuid.UUID, party_name: str, currency: str,
         branch_id: uuid.UUID | None = None, **fields: Any) -> Invoice:
    if uow.actor.user_id is None:
        raise Forbidden("A finance document needs a user as its creator", code="permission_denied")
    inv = Invoice(
        id=uuid.uuid7(),
        company_id=uow.actor.company_id,
        doc_type=doc_type.value,
        draft_ref="pending",
        status=S.DRAFT.value,
        party_id=party_id,
        party_name=party_name,
        currency=currency,
        owner_user_id=uow.actor.user_id,
        branch_id=branch_id or c.branch_for(uow),
        billing_snapshot=gate.billing_snapshot(uow, party_id),
        **fields,
    )
    inv.draft_ref = uow.allocate_number("finance.draft", document_date=c.today(uow), resource_type="finance.invoice", resource_id=inv.id)
    inv.search_text = _search_text(inv)
    uow.add(inv)
    return inv


def _line(uow: UnitOfWork, inv: Invoice, no: int, **fields: Any) -> InvoiceLine:
    ln = InvoiceLine(company_id=uow.actor.company_id, invoice_id=inv.id, line_no=no, **fields)
    ln.unit_price = quantize_unit_price(Decimal(ln.unit_price))
    ln.amount = c.line_amount(ln.quantity, ln.unit_price, inv.currency)
    uow.add(ln)
    return ln


def _manual_lines(uow: UnitOfWork, inv: Invoice, lines: list[InvoiceLineIn]) -> list[InvoiceLine]:
    from app.modules.orders.models import SalesOrderLine

    out = []
    for i, data in enumerate(lines, start=1):
        so_line = None
        if data.so_line_id is not None:
            so_line = uow.session.get(SalesOrderLine, data.so_line_id)
            if so_line is None or so_line.company_id != uow.actor.company_id or (
                inv.sales_order_id is not None and so_line.order_id != inv.sales_order_id
            ):
                raise ValidationFailed(code="validation_failed", errors=[{"loc": ["lines", i - 1, "so_line_id"], "code": "not_found"}])
        out.append(
            _line(
                uow, inv, i, description=data.description, quantity=data.quantity, uom_code=data.uom_code,
                unit_price=data.unit_price, hsn_sac=data.hsn_sac, product_id=data.product_id,
                so_line_id=data.so_line_id,
            )
        )
    return out


def _challan_for_invoice(uow: UnitOfWork, challan_id: uuid.UUID) -> Any:
    """An issued Outward challan to a customer of this company (finance holds company-level invoice creation; the
    challan itself is read without the challan record scope, by company only)."""
    from app.modules.challans.models import Challan

    ch = uow.session.get(Challan, challan_id)
    if ch is None or ch.company_id != uow.actor.company_id:
        raise NotFound(code="not_found", resource_type="challans.challan")
    if ch.status not in ("issued", "closed") or ch.challan_type != "outward" or ch.destination_type != "customer" or ch.party_id is None:
        raise Conflict("Only an issued Outward challan to a customer can be invoiced", code="challan_not_invoiceable")
    return ch


def _lines_from_challan(uow: UnitOfWork, inv: Invoice, ch: Any) -> list[InvoiceLine]:
    from app.modules.challans.models import ChallanLine
    from app.modules.orders.models import SalesOrderLine

    rows = list(uow.session.scalars(select(ChallanLine).where(ChallanLine.challan_id == ch.id).order_by(ChallanLine.line_no)))
    invoiced = c.invoiced_by_challan_line(uow, [r.id for r in rows])
    so_ids = [r.sales_order_line_id for r in rows if r.sales_order_line_id]
    so_lines = {s.id: s for s in uow.session.scalars(select(SalesOrderLine).where(SalesOrderLine.id.in_(so_ids)))} if so_ids else {}
    out: list[InvoiceLine] = []
    for r in rows:
        remaining = Decimal(r.quantity) - invoiced.get(r.id, c.ZERO)
        if remaining <= 0:
            continue
        so = so_lines.get(r.sales_order_line_id) if r.sales_order_line_id else None
        price = Decimal(so.unit_price) if so is not None and so.unit_price is not None and so.currency == inv.currency else c.ZERO
        uom = so.uom_code if so is not None else r.uom_code
        out.append(
            _line(
                uow, inv, len(out) + 1, description=r.item_name, item_code=r.item_code, hsn_sac=r.hsn_sac,
                quantity=remaining, uom_code=uom if uom == r.uom_code else r.uom_code, unit_price=price,
                product_id=r.product_id, challan_id=ch.id, challan_line_id=r.id, so_line_id=r.sales_order_line_id,
            )
        )
    if not out:
        raise Conflict("Everything on this challan is already invoiced", code="nothing_to_invoice")
    return out


def _lines_from_order(uow: UnitOfWork, inv: Invoice, order: Any) -> list[InvoiceLine]:
    from app.modules.orders.models import SalesOrderLine

    rows = list(uow.session.scalars(select(SalesOrderLine).where(SalesOrderLine.order_id == order.id).order_by(SalesOrderLine.line_no)))
    invoiced = c.invoiced_by_so_line(uow, [r.id for r in rows])
    out: list[InvoiceLine] = []
    for r in rows:
        remaining = Decimal(r.qty_delivered) - invoiced.get(r.id, c.ZERO)
        if remaining <= 0 or r.unit_price is None:
            continue
        out.append(
            _line(
                uow, inv, len(out) + 1, description=r.description, item_code=r.product_key, quantity=remaining,
                uom_code=r.uom_code, unit_price=Decimal(r.unit_price), product_id=r.product_id, so_line_id=r.id,
            )
        )
    if not out:
        raise Conflict("Nothing delivered on this order is waiting to be invoiced", code="nothing_to_invoice")
    return out


def _mark_suggestion(uow: UnitOfWork, inv: Invoice, challan_id: uuid.UUID | None, suggestion_id: uuid.UUID | None) -> uuid.UUID | None:
    stmt = select(InvoiceSuggestion).where(InvoiceSuggestion.company_id == uow.actor.company_id)
    if suggestion_id is not None:
        stmt = stmt.where(InvoiceSuggestion.id == suggestion_id)
    elif challan_id is not None:
        stmt = stmt.where(InvoiceSuggestion.challan_id == challan_id)
    else:
        return None
    s = uow.session.scalars(stmt.with_for_update()).first()
    if s is None:
        if suggestion_id is not None:
            raise NotFound(code="not_found", resource_type="finance.invoice_suggestion")
        return None
    if s.status == SuggestionStatus.OPEN.value:
        s.status = SuggestionStatus.DRAFTED.value
        s.invoice_id = inv.id
    return s.id


# =====================================================================================================
# commands
# =====================================================================================================
def create_invoice(uow: UnitOfWork, data: InvoiceCreate) -> Invoice:
    from app.modules.orders.models import SalesOrder

    uow.actor.require(c.INVOICE_CREATE)
    profile = _profile(uow, data.tax_profile_id)
    challan = None
    order = None
    if data.suggestion_id is not None and data.challan_id is None:
        s = uow.session.get(InvoiceSuggestion, data.suggestion_id)
        if s is None or s.company_id != uow.actor.company_id:
            raise NotFound(code="not_found", resource_type="finance.invoice_suggestion")
        data = data.model_copy(update={"challan_id": s.challan_id})
    if data.challan_id is not None:
        challan = _challan_for_invoice(uow, data.challan_id)
        if challan.sales_order_id is not None:
            order = uow.session.get(SalesOrder, challan.sales_order_id)
        party_id, party_name = challan.party_id, challan.destination_party
        currency = order.currency if order is not None else (data.currency or None)
        if currency is None:
            from app.modules.parties.models import Party

            currency = uow.session.get(Party, party_id).default_currency  # type: ignore[union-attr]
    elif data.sales_order_id is not None:
        order = uow.repo(SalesOrder).get(data.sales_order_id)  # 404 outside the actor's order read scope
        party_id, party_name, currency = order.party_id, order.party_name, order.currency
    else:
        if data.party_id is None or data.currency is None or not data.lines:
            raise ValidationFailed(
                "A manual draft needs a party, a currency and at least one line",
                code="validation_failed",
                errors=[{"loc": [f], "code": "required"} for f, v in (("party_id", data.party_id), ("currency", data.currency), ("lines", data.lines)) if not v],
            )
        from app.modules.parties import service as parties

        ref = parties.get_party_ref(uow, data.party_id)  # 404 outside the actor's party scope
        party_id, party_name, currency = ref.id, ref.display_name, data.currency
    policy = _policy(uow)
    inv = _new(
        uow, DocType.INVOICE, party_id=party_id, party_name=party_name, currency=currency,
        branch_id=(order.branch_id if order is not None else None) or (challan.source_branch_id if challan is not None else None),
        sales_order_id=order.id if order is not None else data.sales_order_id,
        payment_due_days=data.payment_due_days if data.payment_due_days is not None else policy.default_payment_due_days,
        customer_reference=data.customer_reference or (order.customer_reference if order is not None else None),
        notes=data.notes, origin="suggestion" if (challan is not None or data.suggestion_id) else "user",
    )
    uow.flush()
    if challan is not None:
        lines = _lines_from_challan(uow, inv, challan)
    elif order is not None and not data.lines:
        lines = _lines_from_order(uow, inv, order)
    else:
        lines = _manual_lines(uow, inv, data.lines)
    _apply_tax(inv, lines, profile)
    inv.suggestion_id = _mark_suggestion(uow, inv, data.challan_id, data.suggestion_id)
    uow.flush()
    _history(uow, inv, InvoiceAction.CREATE, S.DRAFT.value, S.DRAFT.value)
    _emit(uow, ev.DRAFT_CREATED, inv, party_id=str(inv.party_id),
          sales_order_id=str(inv.sales_order_id) if inv.sales_order_id else None,
          suggestion_id=str(inv.suggestion_id) if inv.suggestion_id else None, original_invoice_id=None)
    uow.audit("finance.invoice.created", resource_type="finance.invoice", resource_id=inv.id, resource_label=inv.draft_ref)
    return inv


def _policy(uow: UnitOfWork) -> Any:
    from app.platform.org.service import stored_or_default

    return stored_or_default(uow, "finance_policy")


def _locked(uow: UnitOfWork, invoice_id: uuid.UUID) -> Invoice:
    return uow.repo(Invoice).get(invoice_id, for_update=True)


def update_invoice(uow: UnitOfWork, invoice_id: uuid.UUID, data: InvoiceUpdate) -> Invoice:
    inv = _locked(uow, invoice_id)
    if inv.status != S.DRAFT.value:
        raise Conflict("Only a draft can be changed; reject it back to draft first", code="invoice_not_draft")
    require_in_scope(uow, inv, "update")
    uow.expect_version(inv, data.expected_version)
    lines = c.lines_of(uow, inv)
    if data.lines is not None:
        if inv.doc_type == DocType.CREDIT_NOTE.value:
            raise Conflict("Credit-note lines follow the credited invoice lines; create a new credit note", code="credit_note_lines_fixed")
        for ln in lines:
            uow.session.delete(ln)
        uow.flush()
        lines = _manual_lines(uow, inv, data.lines)
    if data.payment_due_days is not None:
        inv.payment_due_days = data.payment_due_days
    if data.customer_reference is not None:
        inv.customer_reference = data.customer_reference or None
    if data.notes is not None:
        inv.notes = data.notes or None
    profile = None if data.clear_tax_profile else _profile(uow, data.tax_profile_id or inv.tax_profile_id)
    inv.billing_snapshot = gate.billing_snapshot(uow, inv.party_id)
    _apply_tax(inv, lines, profile)
    inv.search_text = _search_text(inv)
    uow.flush()
    _history(uow, inv, InvoiceAction.EDIT, inv.status, inv.status)
    return inv


def create_credit_note(uow: UnitOfWork, data: CreditNoteCreate) -> Invoice:
    uow.actor.require(c.INVOICE_CREATE)
    original = uow.repo(Invoice).get(data.original_invoice_id)
    if original.doc_type != DocType.INVOICE.value or original.status != S.ISSUED.value:
        raise Conflict("A credit note needs an issued invoice", code="invoice_not_issued")
    orig_lines = {ln.id: ln for ln in c.lines_of(uow, original)}
    credited = c.credited_by_invoice_line(uow, list(orig_lines))
    errors = []
    for i, cl in enumerate(data.lines):
        ol = orig_lines.get(cl.invoice_line_id)
        if ol is None:
            errors.append({"loc": ["lines", i, "invoice_line_id"], "code": "not_on_invoice"})
        elif Decimal(cl.quantity) > Decimal(ol.quantity) - credited.get(ol.id, c.ZERO):
            errors.append({"loc": ["lines", i, "quantity"], "code": "exceeds_creditable",
                           "creditable": format((Decimal(ol.quantity) - credited.get(ol.id, c.ZERO)).normalize(), "f")})
    if errors:
        raise ValidationFailed("Credit more than is still creditable is not possible", code="validation_failed", errors=errors)
    cn = _new(
        uow, DocType.CREDIT_NOTE, party_id=original.party_id, party_name=original.party_name, currency=original.currency,
        branch_id=original.branch_id,
        sales_order_id=original.sales_order_id, original_invoice_id=original.id, payment_due_days=None,
        reason_code=data.reason_code, notes=data.notes, customer_reference=original.customer_reference,
    )
    uow.flush()
    lines = []
    for i, cl in enumerate(data.lines, start=1):
        ol = orig_lines[cl.invoice_line_id]
        lines.append(
            _line(
                uow, cn, i, description=ol.description, item_code=ol.item_code, hsn_sac=ol.hsn_sac, quantity=cl.quantity,
                uom_code=ol.uom_code, unit_price=ol.unit_price, product_id=ol.product_id, so_line_id=ol.so_line_id,
                challan_id=ol.challan_id, challan_line_id=ol.challan_line_id, credited_line_id=ol.id,
            )
        )
    profile = uow.session.get(TaxProfile, original.tax_profile_id) if original.tax_profile_id else None
    _apply_tax(cn, lines, profile)
    uow.flush()
    _history(uow, cn, InvoiceAction.CREATE, S.DRAFT.value, S.DRAFT.value, reason_code=data.reason_code)
    _emit(uow, ev.DRAFT_CREATED, cn, party_id=str(cn.party_id), sales_order_id=None, suggestion_id=None,
          original_invoice_id=str(original.id))
    return cn


def in_scope(uow: UnitOfWork, inv: Invoice, action: str) -> bool:
    """The actor's scope for ``finance.invoice.<action>`` covers the record (state rules are checked separately)."""
    return bool(uow.session.scalar(select(exists().where(Invoice.id == inv.id, uow.repo(Invoice).clause(action)))))


def require_in_scope(uow: UnitOfWork, inv: Invoice, action: str) -> None:
    if not in_scope(uow, inv, action):
        raise Forbidden(code="permission_denied", permission=f"finance.invoice.{action}")


def _allowed(inv: Invoice) -> list[str]:
    return [a for (frm, a) in TRANSITIONS if frm == inv.status]


def transition(uow: UnitOfWork, invoice_id: uuid.UUID, data: InvoiceTransition) -> IssueResult | Invoice:
    inv = _locked(uow, invoice_id)
    to = TRANSITIONS.get((inv.status, data.action))
    if to is None:
        raise InvalidTransition(
            f"Cannot {data.action} a document that is {inv.status}", allowed_transitions=_allowed(inv)
        )
    require_in_scope(uow, inv, ACTION_PERMISSION[data.action])
    uow.expect_version(inv, data.expected_version)
    if data.action in REASON_REQUIRED and not data.reason_code:
        raise ValidationFailed(code="validation_failed", errors=[{"loc": ["reason_code"], "code": "required"}])
    frm = inv.status
    if data.action == "issue":
        return _issue(uow, inv)
    if data.action == "approve":
        if inv.owner_user_id == uow.actor.user_id:  # also a CHECK constraint
            raise Forbidden("The creator of a document cannot approve it", code="creator_cannot_approve")
        inv.approved_by, inv.approved_at, inv.approved_version = uow.actor.user_id, uow.now(), inv.version
    elif data.action == "submit":
        inv.submitted_at = uow.now()
    elif data.action == "reject":
        inv.approved_by = inv.approved_at = inv.approved_version = None
    elif data.action == "cancel":
        inv.cancelled_at, inv.cancel_reason_code = uow.now(), data.reason_code
        _release_suggestion(uow, inv)
    inv.status = to
    uow.flush()
    _history(uow, inv, InvoiceAction(data.action), frm, to, reason_code=data.reason_code, reason=data.reason)
    _emit(uow, TRANSITION_EVENTS[data.action], inv, version=inv.version, reason_code=data.reason_code)
    return inv


def _release_suggestion(uow: UnitOfWork, inv: Invoice) -> None:
    if inv.suggestion_id is None:
        return
    s = uow.session.get(InvoiceSuggestion, inv.suggestion_id)
    if s is not None and s.invoice_id == inv.id and s.status == SuggestionStatus.DRAFTED.value:
        s.status, s.invoice_id = SuggestionStatus.OPEN.value, None


def _issue(uow: UnitOfWork, inv: Invoice) -> IssueResult:
    require_step_up(uow, c.INVOICE_ISSUE)
    lines = c.lines_of(uow, inv)
    _lock_quantity_sources(uow, lines)
    result = gate.check(uow, inv, lines)
    frm = inv.status
    if not result.can_issue:
        codes = [b.code for b in result.blockers]
        inv.last_blockers = codes
        uow.flush()
        _history(uow, inv, InvoiceAction.ISSUE_BLOCKED, frm, frm, blockers=codes)
        _emit(uow, ev.ISSUE_BLOCKED, inv, version=inv.version, blocker_codes=codes)
        return IssueResult(issued=False, blockers=list(result.blockers), detail=detail(uow, inv))
    day = c.today(uow)
    key = "finance.credit_note" if inv.doc_type == DocType.CREDIT_NOTE.value else "finance.invoice"
    inv.document_number = uow.allocate_number(key, document_date=day, resource_type="finance.invoice", resource_id=inv.id)
    inv.document_date = day
    if inv.doc_type == DocType.INVOICE.value:
        inv.due_date = day + timedelta(days=inv.payment_due_days) if inv.payment_due_days is not None else None
    inv.billing_snapshot = gate.billing_snapshot(uow, inv.party_id)
    inv.status, inv.issued_by, inv.issued_at, inv.last_blockers = S.ISSUED.value, uow.actor.user_id, uow.now(), []
    inv.search_text = _search_text(inv)
    uow.flush()
    _history(uow, inv, InvoiceAction.ISSUE, frm, S.ISSUED.value)
    if inv.doc_type == DocType.CREDIT_NOTE.value:
        uow.emit(ev.CREDIT_NOTE_ISSUED, aggregate_id=inv.id, aggregate_version=inv.version,
                 payload={"credit_note_id": str(inv.id), "document_number": inv.document_number,
                          "original_invoice_id": str(inv.original_invoice_id)})
        from app.modules.finance import receipts

        receipts.auto_allocate_credit_note(uow, inv)
    else:
        _emit(uow, ev.ISSUED, inv, document_number=inv.document_number, party_id=str(inv.party_id),
              due_date=inv.due_date.isoformat() if inv.due_date else None)
    uow.audit("finance.invoice.issued", resource_type="finance.invoice", resource_id=inv.id, resource_label=inv.document_number)
    return IssueResult(issued=True, blockers=[], detail=detail(uow, inv))


def _lock_quantity_sources(uow: UnitOfWork, lines: list[InvoiceLine]) -> None:
    """Serialise concurrent issues that bill the same order or challan lines (lock order: document -> lines)."""
    from app.modules.challans.models import ChallanLine
    from app.modules.orders.models import SalesOrderLine

    so_ids = sorted({ln.so_line_id for ln in lines if ln.so_line_id})
    ch_ids = sorted({ln.challan_line_id for ln in lines if ln.challan_line_id})
    cr_ids = sorted({ln.credited_line_id for ln in lines if ln.credited_line_id})
    if so_ids:
        uow.lock(SalesOrderLine, so_ids)
    if ch_ids:
        uow.lock(ChallanLine, ch_ids)
    if cr_ids:
        uow.lock(InvoiceLine, cr_ids)


# =====================================================================================================
# reads
# =====================================================================================================
def _line_read(ln: InvoiceLine, currency: str, creditable: Decimal | None = None) -> InvoiceLineRead:
    return InvoiceLineRead(
        id=ln.id, line_no=ln.line_no, description=ln.description, item_code=ln.item_code, hsn_sac=ln.hsn_sac,
        quantity=Decimal(ln.quantity), uom_code=ln.uom_code, unit_price=c.m(ln.unit_price, currency),
        amount=c.m(ln.amount, currency), tax_rate_percent=ln.tax_rate_percent,
        tax_amount=c.money(ln.tax_amount, currency), so_line_id=ln.so_line_id, challan_id=ln.challan_id,
        challan_line_id=ln.challan_line_id, credited_line_id=ln.credited_line_id, product_id=ln.product_id,
        creditable_quantity=creditable,
    )


def _summary(uow: UnitOfWork, inv: Invoice, allocated: Decimal, today: Any, parties: dict, people: dict) -> InvoiceSummary:
    issued = inv.status == S.ISSUED.value
    out = Decimal(inv.total_amount) - allocated if issued else None
    return InvoiceSummary(
        id=inv.id, doc_type=DocType(inv.doc_type), draft_ref=inv.draft_ref, document_number=inv.document_number,
        status=S(inv.status), party=parties[inv.party_id], currency=inv.currency,  # type: ignore[arg-type]
        document_date=inv.document_date, due_date=inv.due_date, total=c.m(inv.total_amount, inv.currency),
        outstanding=c.money(out, inv.currency),
        is_overdue=bool(issued and inv.doc_type == DocType.INVOICE.value and inv.due_date and inv.due_date < today and out and out > 0),
        tax_status=TaxStatus(inv.tax_status), label=None if issued else c.DRAFT_LABEL,
        owner=people.get(inv.owner_user_id), sales_order_id=inv.sales_order_id,
        original_invoice_id=inv.original_invoice_id, created_at=inv.created_at,
    )


def allocation_reads(uow: UnitOfWork, rows: list[Allocation]) -> list[AllocationRead]:
    receipt_ids = {r.receipt_id for r in rows if r.receipt_id}
    doc_ids = {r.invoice_id for r in rows} | {r.credit_note_id for r in rows if r.credit_note_id}
    rnums = dict(uow.session.execute(select(Receipt.id, Receipt.receipt_number).where(Receipt.id.in_(receipt_ids))).all()) if receipt_ids else {}
    dnums = dict(uow.session.execute(select(Invoice.id, Invoice.document_number).where(Invoice.id.in_(doc_ids))).all()) if doc_ids else {}
    reversed_ids = {r.reverses_allocation_id for r in rows if r.reverses_allocation_id}
    people = c.users(uow, [r.actor_user_id for r in rows])
    return [
        AllocationRead(
            id=r.id, source_type=r.source_type, receipt_id=r.receipt_id, receipt_number=rnums.get(r.receipt_id) if r.receipt_id else None,
            credit_note_id=r.credit_note_id, credit_note_number=dnums.get(r.credit_note_id) if r.credit_note_id else None,
            invoice_id=r.invoice_id, invoice_number=dnums.get(r.invoice_id), amount=c.m(r.amount, r.currency),
            allocated_on=r.allocated_on, reverses_allocation_id=r.reverses_allocation_id, reversed=r.id in reversed_ids,
            actor=people.get(r.actor_user_id) if r.actor_user_id else None, created_at=r.created_at,
        )
        for r in rows
    ]


def detail(uow: UnitOfWork, inv: Invoice) -> InvoiceDetail:
    repo = uow.repo(Invoice)
    lines = c.lines_of(uow, inv)
    hist = list(uow.session.scalars(select(InvoiceStatusHistory).where(InvoiceStatusHistory.invoice_id == inv.id)
                                    .order_by(InvoiceStatusHistory.occurred_at, InvoiceStatusHistory.id)))
    alloc_rows = list(uow.session.scalars(select(Allocation).where(
        Allocation.company_id == uow.actor.company_id,
        or_(Allocation.invoice_id == inv.id, Allocation.credit_note_id == inv.id)).order_by(Allocation.created_at, Allocation.id)))
    people = c.users(uow, [inv.owner_user_id, inv.approved_by, inv.issued_by, *[h.actor_user_id for h in hist]])
    parties = c.party_refs(uow, [(inv.party_id, inv.party_name)])
    today = c.today(uow)
    to_inv = sum((Decimal(a.amount) for a in alloc_rows if a.invoice_id == inv.id), c.ZERO)
    from_cn = sum((Decimal(a.amount) for a in alloc_rows if a.credit_note_id == inv.id), c.ZERO)
    credited_qty = c.credited_by_invoice_line(uow, [ln.id for ln in lines]) if inv.doc_type == DocType.INVOICE.value else {}
    credit_notes = list(uow.session.scalars(select(Invoice).where(Invoice.company_id == uow.actor.company_id, Invoice.original_invoice_id == inv.id)))
    credited_total = sum((Decimal(x.total_amount) for x in credit_notes if x.status == S.ISSUED.value), c.ZERO)
    profile = uow.session.get(TaxProfile, inv.tax_profile_id) if inv.tax_profile_id else None
    from app.modules.finance.config import tax_profile_read

    related: list[FinanceDocRef] = []
    if inv.sales_order_id:
        from app.modules.orders.models import SalesOrder

        so = uow.session.get(SalesOrder, inv.sales_order_id)
        if so is not None:
            related.append(FinanceDocRef(id=so.id, kind="sales_order", number=so.order_number, path=f"/sales/orders/{so.id}"))
    challan_ids = sorted({ln.challan_id for ln in lines if ln.challan_id})
    if challan_ids:
        from app.modules.challans.models import Challan

        for ch in uow.session.scalars(select(Challan).where(Challan.id.in_(challan_ids))):
            related.append(FinanceDocRef(id=ch.id, kind="challan", number=ch.challan_number, path=f"/operations/challans/{ch.id}"))
    if inv.original_invoice_id:
        o = uow.session.get(Invoice, inv.original_invoice_id)
        if o is not None:
            related.append(FinanceDocRef(id=o.id, kind="invoice", number=o.document_number or o.draft_ref, path=f"/finance/invoices/{o.id}"))
    for x in credit_notes:
        related.append(FinanceDocRef(id=x.id, kind="credit_note", number=x.document_number or x.draft_ref, path=f"/finance/credit-notes/{x.id}"))
    caps = {k: Capability(**v) for k, v in repo.capabilities(inv, ["update", "approve", "issue"]).items()}
    for action in ("submit", "reject", "cancel"):
        state_ok = (inv.status, action) in TRANSITIONS
        ok = state_ok and in_scope(uow, inv, ACTION_PERMISSION[action])
        caps[action] = Capability(allowed=ok, reason_code=None if ok else ("invalid_state" if not state_ok else "permission_denied"))
    is_open_invoice = inv.doc_type == DocType.INVOICE.value and inv.status == S.ISSUED.value
    caps["create_credit_note"] = Capability(
        allowed=is_open_invoice and uow.actor.can(c.INVOICE_CREATE),
        reason_code=None if is_open_invoice and uow.actor.can(c.INVOICE_CREATE) else ("invoice_not_issued" if not is_open_invoice else "permission_denied"),
    )
    gate_now = gate.check(uow, inv, lines)
    allowed = [
        TransitionRead(action=a, to_status=to, requires_reason=a in REASON_REQUIRED)
        for (frm, a), to in TRANSITIONS.items()
        if frm == inv.status and caps[a].allowed
    ]
    base = _summary(uow, inv, to_inv, today, parties, people)
    return InvoiceDetail(
        **base.model_dump(),
        billing=dict(inv.billing_snapshot or {}),
        payment_due_days=inv.payment_due_days,
        tax_profile=tax_profile_read(uow, profile) if profile else None,
        subtotal=c.m(inv.subtotal_amount, inv.currency),
        tax=c.money(inv.tax_amount, inv.currency),
        allocated=c.m(to_inv if inv.doc_type == DocType.INVOICE.value else from_cn, inv.currency),
        credited=c.m(credited_total, inv.currency),
        customer_reference=inv.customer_reference, notes=inv.notes, reason_code=inv.reason_code,
        lines=[
            _line_read(ln, inv.currency, (Decimal(ln.quantity) - credited_qty.get(ln.id, c.ZERO)) if is_open_invoice else None)
            for ln in lines
        ],
        history=[
            InvoiceHistoryRead(action=h.action, from_status=h.from_status, to_status=h.to_status,
                               actor=people.get(h.actor_user_id) if h.actor_user_id else None, reason_code=h.reason_code,
                               reason=h.reason, blocker_codes=list(h.blocker_codes or []), occurred_at=h.occurred_at)
            for h in hist
        ],
        allocations=allocation_reads(uow, alloc_rows),
        related=related,
        approved_by=people.get(inv.approved_by) if inv.approved_by else None,
        approved_at=inv.approved_at, approved_version=inv.approved_version,
        issued_by=people.get(inv.issued_by) if inv.issued_by else None, issued_at=inv.issued_at,
        last_blockers=list(inv.last_blockers or []), gate=gate_now, version=inv.version,
        capabilities=caps, allowed_transitions=allowed,
    )


def get_invoice(uow: UnitOfWork, invoice_id: uuid.UUID, *, doc_type: DocType | None = None) -> InvoiceDetail:
    uow.actor.require(c.INVOICE_READ)
    inv = uow.repo(Invoice).get(invoice_id)
    if doc_type is not None and inv.doc_type != doc_type.value:
        raise NotFound(code="not_found", resource_type="finance.invoice")
    return detail(uow, inv)


def _conditions(uow: UnitOfWork, f: InvoiceFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [Invoice.doc_type == f.doc_type.value]
    if f.status:
        conds.append(Invoice.status.in_([s.value for s in f.status]))
    if f.party_id:
        conds.append(Invoice.party_id == f.party_id)
    if f.q:
        for t in tokens(f.q):
            conds.append(Invoice.search_text.ilike(contains_pattern(t.lower()), escape=LIKE_ESCAPE))
    today = c.today(uow)
    if f.overdue_only or f.open_only:
        conds.append(Invoice.status == S.ISSUED.value)
        alloc = (
            select(func.coalesce(func.sum(Allocation.amount), 0))
            .where(Allocation.invoice_id == Invoice.id)
            .correlate(Invoice)
            .scalar_subquery()
        )
        conds.append(Invoice.total_amount - alloc > 0)
        if f.overdue_only:
            conds.append(Invoice.due_date < today)
    return conds


def list_invoices(uow: UnitOfWork, f: InvoiceFilters, *, limit: int = 50, offset: int = 0) -> Page[InvoiceSummary]:
    uow.actor.require(c.INVOICE_READ)
    repo = uow.repo(Invoice)
    conds = [repo.clause("read"), *_conditions(uow, f)]
    total = uow.session.scalar(select(func.count(Invoice.id)).where(*conds)) or 0
    limit, offset = max(1, min(limit, MAX_LIMIT)), max(0, offset)
    rows = list(uow.session.scalars(
        select(Invoice).where(*conds)
        .order_by(Invoice.document_date.desc().nulls_first(), Invoice.created_at.desc(), Invoice.id.desc())
        .limit(limit).offset(offset)))
    alloc = c.allocated_to_invoices(uow, [r.id for r in rows])
    people = c.users(uow, [r.owner_user_id for r in rows])
    parties = c.party_refs(uow, [(r.party_id, r.party_name) for r in rows])
    today = c.today(uow)
    return Page[InvoiceSummary](
        items=[_summary(uow, r, alloc.get(r.id, c.ZERO), today, parties, people) for r in rows],
        total=int(total), limit=limit, offset=offset,
    )
