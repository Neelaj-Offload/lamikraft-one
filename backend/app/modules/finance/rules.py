"""Slice-5 briefing rule families fed through the ``tasks.rules`` consumer (events.md §4):

- ``fin.invoice_suggestions``: one issue per open invoice suggestion (an issued Outward challan to a customer), a
  "draft the invoice" task offered to the members who can create invoices; closed when drafted or dismissed.
- ``fin.invoice_approvals``: a submitted draft asks the members who may approve it (never its creator); a refused
  issue tells the creator which blockers remain; closed when the document is issued or cancelled.
- ``fin.overdue_invoices``: an issued invoice past due with something outstanding: a follow-up task for its creator;
  closed when settled.
- ``fin.unallocated_receipts``: a receipt still (partly) unallocated: an "allocate" task for whoever recorded it;
  closed when fully allocated or reversed.
- ``fin.accounting_sync``: a failed accounting export or a reconciliation mismatch: a task for whoever ran it (or the
  members who can run exports); closed when a later reconciliation matches.
- ``mgmt.margin_exceptions``: an issued quote whose margin from costs of record is below the policy threshold: a
  review task for members who hold cost read (``costing`` sensitivity). Facts carry ids and names only — never the
  margin, revenue or cost.

Rules re-read the sources through the finance readers; events are only triggers (replays change nothing).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from app.modules.finance import common as c
from app.modules.tasks import completion, responsibility
from app.modules.tasks.models import DueKind, IssueResolution, MemberRole, Sensitivity, TaskState
from app.modules.tasks.rules.outcome import Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork

INVOICE = "finance.invoice"
RECEIPT = "finance.receipt"
SUGGESTION = "finance.invoice_suggestion"
MARGIN = "finance.margin_exception"
EXPORT = "finance.accounting_export"

#: event -> families it feeds (the tasks consumer wires every one to ``on_event``)
EVENT_FAMILIES: dict[str, tuple[str, ...]] = {
    "finance.invoice_suggestion.created": ("fin.invoice_suggestions",),
    "finance.invoice_suggestion.dismissed": ("fin.invoice_suggestions",),
    "finance.invoice.draft_created": ("fin.invoice_suggestions",),
    "finance.invoice.submitted": ("fin.invoice_approvals",),
    "finance.invoice.approved": ("fin.invoice_approvals",),
    "finance.invoice.rejected": ("fin.invoice_approvals",),
    "finance.invoice.cancelled": ("fin.invoice_approvals", "fin.invoice_suggestions"),
    "finance.invoice.issue_blocked": ("fin.invoice_approvals",),
    "finance.invoice.issued": ("fin.invoice_approvals",),
    "finance.credit_note.issued": ("fin.invoice_approvals", "fin.overdue_invoices"),
    "finance.invoice.became_overdue": ("fin.overdue_invoices",),
    "finance.allocation.created": ("fin.overdue_invoices", "fin.unallocated_receipts"),
    "finance.allocation.reversed": ("fin.overdue_invoices", "fin.unallocated_receipts"),
    "finance.receipt.unallocated_detected": ("fin.unallocated_receipts",),
    "finance.receipt.reversed": ("fin.unallocated_receipts",),
    "sales.quote.margin_below_threshold": ("mgmt.margin_exceptions",),
    "finance.accounting_export.completed": ("fin.accounting_sync",),
    "finance.accounting_export.failed": ("fin.accounting_sync",),
    "finance.accounting_export.reconciled": ("fin.accounting_sync",),
}


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def holders(uow: UnitOfWork, *keys: str, exclude: tuple[uuid.UUID | None, ...] = ()) -> tuple[uuid.UUID, ...]:
    """Active members holding every key (evaluated as each member), minus ``exclude``."""
    out = []
    for user_id in responsibility.active_member_ids(uow):
        if user_id in exclude:
            continue
        actor = responsibility.member_actor(uow, user_id)
        if actor is not None and all(actor.can(k) for k in keys):
            out.append(user_id)
    return tuple(out)


def _root(src: Any, permission: str) -> MemberSpec:
    return MemberSpec(
        key=f"{src.source_type}:{src.source_id}", ref_type=src.source_type, ref_id=src.source_id, ref_version=src.version,
        label=src.label, facts=dict(src.facts), required_permission=permission, role=MemberRole.ROOT.value,
        scope_owner_id=src.owner_user_id, scope_branch_id=src.branch_id,
    )


def _task(src: Any, *, key: str, kind: str, title: str, check: str, permission: str, owner: uuid.UUID | None = None,
          candidates: tuple[uuid.UUID, ...] = (), family: str, sensitivity: str = Sensitivity.FINANCE.value,
          uow: UnitOfWork) -> TaskSpec:
    queue = None
    if owner is None and not candidates:
        queue = responsibility.resolve(uow, family, []).queue_code
    return TaskSpec(
        dedup_key=key, kind=kind, title=title, completion_check=check, required_permission=permission,
        facts=dict(src.facts), primary_ref_type=src.source_type, primary_ref_id=src.source_id,
        primary_ref_version=src.version, owner_user_id=owner, assignee_user_id=owner, queue_code=queue,
        due_kind=DueKind.SOFT.value if kind in ("approve_invoice", "allocate_receipt", "chase_overdue") else DueKind.NONE.value,
        due_at=uow.now() if kind in ("approve_invoice", "allocate_receipt", "chase_overdue") else None,
        scope_owner_id=src.owner_user_id, scope_branch_id=src.branch_id, branch_id=src.branch_id,
        candidates=() if owner else candidates, sensitivity=sensitivity,
    )


def _outcome(src: Any, *, key: str, family: str, title: str, permission: str, tasks: list[TaskSpec],
             closed_reason: str, cancelled: bool = False) -> IssueOutcome:
    return IssueOutcome(
        issue_key=key, family=family, root_ref_type=src.source_type, root_ref_id=src.source_id, title=title,
        title_facts={"label": src.label}, required_permission=permission, scope_owner_id=src.owner_user_id,
        scope_branch_id=src.branch_id, members=[_root(src, permission)], tasks=tasks,
        closure=Closure(TaskState.CANCELLED.value if cancelled else TaskState.DONE.value, {"reason": closed_reason}),
        resolution=IssueResolution.COMPLETED.value, root_version=src.version,
    )


def _active(uow: UnitOfWork, user_id: uuid.UUID | None) -> uuid.UUID | None:
    return user_id if responsibility.is_active(uow, user_id) else None


# ---- fin.invoice_suggestions ----------------------------------------------------------------------------------------
def derive_suggestion(uow: UnitOfWork, suggestion_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    s = cache.read(uow, SUGGESTION, suggestion_id)
    if s is None:
        return None
    tasks = []
    if not s.is_closed:
        tasks.append(_task(
            s, key=f"suggestion:{s.source_id}:draft", kind="draft_invoice", check="suggestion_handled",
            title=f"Draft the invoice for {s.facts['challan_number']} ({s.facts['party_name']})",
            permission=c.INVOICE_CREATE, candidates=holders(uow, c.INVOICE_CREATE), family="fin.invoice_suggestions", uow=uow,
        ))
    return _outcome(s, key=f"suggestion:{s.source_id}", family="fin.invoice_suggestions",
                    title=f"Invoice {s.facts['challan_number']} for {s.facts['party_name']}", permission=c.INVOICE_READ,
                    tasks=tasks, closed_reason=f"suggestion_{s.status}")


# ---- fin.invoice_approvals ------------------------------------------------------------------------------------------
def derive_approval(uow: UnitOfWork, invoice_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    inv = cache.read(uow, INVOICE, invoice_id)
    if inv is None:
        return None
    number = inv.facts["number"]
    tasks: list[TaskSpec] = []
    if inv.status == "pending_approval":
        tasks.append(_task(
            inv, key=f"invoice:{inv.source_id}:approve", kind="approve_invoice", check="invoice_approval_decided",
            title=f"Approve {number} for {inv.facts['party_name']}", permission=c.INVOICE_APPROVE,
            candidates=holders(uow, c.INVOICE_APPROVE, exclude=(inv.owner_user_id,)), family="fin.invoice_approvals", uow=uow,
        ))
    elif inv.status in ("draft", "approved") and inv.facts.get("blockers"):
        tasks.append(_task(
            inv, key=f"invoice:{inv.source_id}:unblock", kind="resolve_issue_blockers", check="invoice_issued",
            title=f"{number} cannot be issued yet: {len(inv.facts['blockers'])} blocker(s)", permission=c.INVOICE_READ,
            owner=_active(uow, inv.owner_user_id), candidates=holders(uow, c.INVOICE_ISSUE),
            family="fin.invoice_approvals", uow=uow,
        ))
    elif inv.status == "approved":
        tasks.append(_task(
            inv, key=f"invoice:{inv.source_id}:issue", kind="issue_invoice", check="invoice_issued",
            title=f"Issue {number} for {inv.facts['party_name']}", permission=c.INVOICE_ISSUE,
            owner=_active(uow, inv.owner_user_id), candidates=holders(uow, c.INVOICE_ISSUE),
            family="fin.invoice_approvals", uow=uow,
        ))
    return _outcome(inv, key=f"invoice:{inv.source_id}:approval", family="fin.invoice_approvals",
                    title=f"{number} · {inv.facts['party_name']}", permission=c.INVOICE_READ, tasks=tasks,
                    closed_reason=f"invoice_{inv.status}", cancelled=inv.status == "cancelled")


# ---- fin.overdue_invoices -------------------------------------------------------------------------------------------
def derive_overdue(uow: UnitOfWork, invoice_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    inv = cache.read(uow, INVOICE, invoice_id)
    if inv is None or inv.facts.get("doc_type") != "invoice" or inv.status != "issued":
        return None
    tasks = []
    if inv.facts.get("overdue"):
        tasks.append(_task(
            inv, key=f"invoice:{inv.source_id}:chase", kind="chase_overdue", check="invoice_settled",
            title=f"Follow up overdue {inv.facts['number']} ({inv.facts['party_name']}, due {inv.facts['due_date']})",
            permission=c.INVOICE_READ, owner=_active(uow, inv.owner_user_id),
            candidates=holders(uow, c.RECEIPT_CREATE), family="fin.overdue_invoices", uow=uow,
        ))
    return _outcome(inv, key=f"invoice:{inv.source_id}:overdue", family="fin.overdue_invoices",
                    title=f"Overdue {inv.facts['number']} · {inv.facts['party_name']}", permission=c.INVOICE_READ,
                    tasks=tasks, closed_reason="invoice_settled" if not inv.facts.get("outstanding_positive") else "not_overdue")


# ---- fin.unallocated_receipts ---------------------------------------------------------------------------------------
def derive_receipt(uow: UnitOfWork, receipt_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    r = cache.read(uow, RECEIPT, receipt_id)
    if r is None:
        return None
    tasks = []
    if not r.is_closed and r.status == "recorded":
        tasks.append(_task(
            r, key=f"receipt:{r.source_id}:allocate", kind="allocate_receipt", check="receipt_allocated",
            title=f"Allocate {r.facts['receipt_number']} from {r.facts['party_name']}", permission=c.ALLOCATION_CREATE,
            owner=_active(uow, r.owner_user_id), candidates=holders(uow, c.ALLOCATION_CREATE),
            family="fin.unallocated_receipts", uow=uow,
        ))
    return _outcome(r, key=f"receipt:{r.source_id}:unallocated", family="fin.unallocated_receipts",
                    title=f"Unallocated {r.facts['receipt_number']} · {r.facts['party_name']}", permission=c.RECEIPT_READ,
                    tasks=tasks, closed_reason=f"receipt_{'reversed' if r.status == 'reversed' else 'allocated'}",
                    cancelled=r.status == "reversed")


# ---- mgmt.margin_exceptions -----------------------------------------------------------------------------------------
def derive_margin(uow: UnitOfWork, exception_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    m = cache.read(uow, MARGIN, exception_id)
    if m is None:
        return None
    tasks = []
    if not m.is_closed:
        tasks.append(_task(
            m, key=f"margin:{m.source_id}:review", kind="review_margin", check="margin_cleared",
            title=f"Review the margin on {m.facts['quote_number']} rev {m.facts['revision_no']} ({m.facts['party_name']})",
            permission=c.INVOICE_READ, candidates=holders(uow, c.INVOICE_READ, "pricing.cost.read"),
            family="mgmt.margin_exceptions", sensitivity=Sensitivity.COSTING.value, uow=uow,
        ))
    return _outcome(m, key=f"margin:{m.source_id}", family="mgmt.margin_exceptions",
                    title=f"Margin below policy: {m.facts['quote_number']} · {m.facts['party_name']}",
                    permission=c.INVOICE_READ, tasks=tasks, closed_reason="margin_cleared")


# ---- fin.accounting_sync -------------------------------------------------------------------------------------------
def derive_export(uow: UnitOfWork, export_id: uuid.UUID, *, cache: SourceCache) -> IssueOutcome | None:
    x = cache.read(uow, EXPORT, export_id)
    if x is None:
        return None
    tasks = []
    if not x.is_closed:
        failed = x.status == "failed"
        tasks.append(_task(
            x, key=f"export:{x.source_id}:attention", kind="fix_accounting_sync", check="export_settled",
            title=(f"Accounting export {x.facts['export_number']} failed ({x.facts['error_code']})" if failed
                   else f"Accounting export {x.facts['export_number']} does not reconcile"),
            permission=c.EXPORT_RUN, owner=_active(uow, x.owner_user_id), candidates=holders(uow, c.EXPORT_RUN),
            family="fin.accounting_sync", uow=uow,
        ))
    return _outcome(x, key=f"export:{x.source_id}", family="fin.accounting_sync",
                    title=f"Accounting sync {x.facts['export_number']}", permission=c.INVOICE_READ, tasks=tasks,
                    closed_reason="export_settled")


# ---- dispatch -------------------------------------------------------------------------------------------------------
def on_event(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    p = event.payload or {}
    name = event.event_type
    families = EVENT_FAMILIES.get(name, ())
    invoice_id = _uuid(p.get("invoice_id")) or _uuid(p.get("credit_note_id"))
    if "fin.invoice_suggestions" in families:
        sid = _uuid(p.get("suggestion_id"))
        if sid is None and name == "finance.invoice.cancelled" and invoice_id is not None:
            from app.modules.finance.models import Invoice

            inv = uow.session.get(Invoice, invoice_id)
            sid = inv.suggestion_id if inv is not None else None
        if sid is not None:
            yield derive_suggestion(uow, sid, cache=cache)
    if "fin.invoice_approvals" in families and invoice_id is not None:
        yield derive_approval(uow, invoice_id, cache=cache)
    if "fin.overdue_invoices" in families:
        target = _uuid(p.get("original_invoice_id")) if name == "finance.credit_note.issued" else _uuid(p.get("invoice_id"))
        if target is not None:
            yield derive_overdue(uow, target, cache=cache)
    if "fin.unallocated_receipts" in families:
        rid = _uuid(p.get("receipt_id"))
        if rid is not None:
            yield derive_receipt(uow, rid, cache=cache)
    if "fin.accounting_sync" in families:
        xid = _uuid(p.get("export_id"))
        if xid is not None:
            yield derive_export(uow, xid, cache=cache)
        if name == "finance.accounting_export.completed":
            from sqlalchemy import select

            from app.modules.finance.models import AccountingExport

            for fid in uow.session.scalars(select(AccountingExport.id).where(
                    AccountingExport.company_id == uow.actor.company_id, AccountingExport.status == "failed")):
                yield derive_export(uow, fid, cache=cache)
    if "mgmt.margin_exceptions" in families:
        eid = _uuid(p.get("exception_id"))
        if eid is not None:
            yield derive_margin(uow, eid, cache=cache)


# ---- completion checks ----------------------------------------------------------------------------------------------
def _read(uow: UnitOfWork, source_type: str, ref_id: Any) -> Any:
    from app.platform import sources

    return sources.read(uow, source_type, ref_id)


def _suggestion_handled(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    s = _read(uow, SUGGESTION, task.primary_ref_id)
    if s is None or s.is_closed:
        return completion.CompletionResult(True, evidence={"suggestion": s.status if s else "gone"})
    return completion.CompletionResult(False, remaining=["suggestion_open"])


def _approval_decided(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    inv = _read(uow, INVOICE, task.primary_ref_id)
    if inv is None or inv.status != "pending_approval":
        return completion.CompletionResult(True, evidence={"invoice": inv.status if inv else "gone"})
    return completion.CompletionResult(False, remaining=["pending_approval"])


def _issued(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    inv = _read(uow, INVOICE, task.primary_ref_id)
    if inv is None or inv.status in ("issued", "cancelled"):
        return completion.CompletionResult(True, evidence={"invoice": inv.status if inv else "gone"})
    return completion.CompletionResult(False, remaining=["not_issued"])


def _settled(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    inv = _read(uow, INVOICE, task.primary_ref_id)
    if inv is None or not inv.facts.get("outstanding_positive"):
        return completion.CompletionResult(True, evidence={"invoice": "settled"})
    return completion.CompletionResult(False, remaining=["outstanding"])


def _allocated(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    r = _read(uow, RECEIPT, task.primary_ref_id)
    if r is None or r.is_closed:
        return completion.CompletionResult(True, evidence={"receipt": r.status if r else "gone"})
    return completion.CompletionResult(False, remaining=["unallocated"])


def _margin_cleared(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    m = _read(uow, MARGIN, task.primary_ref_id)
    if m is None or m.is_closed:
        return completion.CompletionResult(True, evidence={"margin_exception": "cleared"})
    return completion.CompletionResult(False, remaining=["margin_exception_open"])


def _export_settled(uow: UnitOfWork, task: Any) -> completion.CompletionResult:
    x = _read(uow, EXPORT, task.primary_ref_id)
    if x is None or x.is_closed:
        return completion.CompletionResult(True, evidence={"export": "settled"})
    return completion.CompletionResult(False, remaining=["export_attention"])


CHECKS = {
    "export_settled": (_export_settled, EXPORT),
    "suggestion_handled": (_suggestion_handled, SUGGESTION),
    "invoice_approval_decided": (_approval_decided, INVOICE),
    "invoice_issued": (_issued, INVOICE),
    "invoice_settled": (_settled, INVOICE),
    "receipt_allocated": (_allocated, RECEIPT),
    "margin_cleared": (_margin_cleared, MARGIN),
}


def register_checks() -> None:
    for code, (fn, source_type) in CHECKS.items():
        completion.register(code)(fn)
        completion.CHECK_SOURCES.setdefault(code, source_type)
