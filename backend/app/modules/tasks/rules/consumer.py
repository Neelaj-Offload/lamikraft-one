"""The ``tasks.rules`` consumer: domain events trigger re-derivation of the issues they affect.

Algorithm (briefing design §4): exactly-once per event (``consumers.once``), migration-origin events
skipped, stale aggregate versions ignored, then every affected issue key is re-derived from current
source state and reconciled. Replays and out-of-order deliveries therefore produce no new facts.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import func, select

from app.modules.tasks.issues import apply_outcome
from app.modules.tasks.models import Issue, IssueMember, IssueState
from app.modules.tasks.rules import families
from app.modules.tasks.rules.families import MESSAGE, PROPOSAL, QUOTE
from app.modules.tasks.rules.outcome import IssueOutcome
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.events.service import once
from app.platform.uow import UnitOfWork

CONSUMER = "tasks.rules"
Trigger = Callable[[UnitOfWork, DomainEvent, SourceCache], Iterator[IssueOutcome | None]]


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


# ---- triggers (generators: each outcome is derived after the previous one was applied) ---------------
def _quote_cluster(
    uow: UnitOfWork, quote_id: uuid.UUID, event: DomainEvent | None, cache: SourceCache, *, origin_hint: uuid.UUID | None = None
) -> Iterator[IssueOutcome | None]:
    """Everything a quote change can affect: its review, its expiry and the messages it answers."""
    quote = cache.read(uow, QUOTE, quote_id)
    message_ids = set(families.messages_linked_to(uow, QUOTE, quote_id))
    origin = _uuid(quote.facts.get("origin_message_id")) if quote is not None else None
    origin = origin or origin_hint
    if origin is not None:
        message_ids.add(origin)
    yield families.derive_quote_review(uow, quote_id, event=event, cache=cache)
    yield families.derive_quote_expiry(uow, quote_id, event=event, cache=cache)
    for message_id in sorted(message_ids):
        extra = (quote_id,) if message_id == origin else ()
        yield families.derive_message(uow, message_id, event=event, extra_quote_ids=extra, cache=cache)


def _on_quote(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    quote_id = _uuid(event.payload.get("quote_id")) or event.aggregate_id
    if quote_id is None:
        return
    yield from _quote_cluster(uow, quote_id, event, cache, origin_hint=_uuid(event.payload.get("origin_message_id")))


def _on_message(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    message_id = _uuid(event.payload.get("message_id")) or event.aggregate_id
    if message_id is None:
        return
    extra = tuple(q for q in [_uuid(event.payload.get("quote_id"))] if q is not None)
    yield families.derive_message(uow, message_id, event=event, extra_quote_ids=extra, cache=cache)


def _on_enquiry(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    enquiry_id = _uuid(event.payload.get("enquiry_id")) or event.aggregate_id
    if enquiry_id is not None:
        yield families.derive_enquiry(uow, enquiry_id, event=event, cache=cache)


def _on_party_updated(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    party_id = _uuid(event.payload.get("party_id")) or event.aggregate_id
    if party_id is not None:
        yield families.derive_party_change(uow, party_id, event, cache=cache)


def _on_proposal(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    from app.core.errors import NotFound
    from app.modules.approvals import service as approvals

    proposal_id = _uuid(event.payload.get("proposal_id")) or event.aggregate_id
    if proposal_id is None:
        return
    yield families.derive_approval(uow, proposal_id, event=event, cache=cache)
    try:
        targets = approvals.targets_of(uow, approvals.get(uow, proposal_id))
    except NotFound:
        targets = []
    # then the replies whose blocked state depends on this decision
    for target in targets:
        if target.target_type != QUOTE:
            continue
        quote = cache.read(uow, QUOTE, target.target_id)
        message_ids = set(families.messages_linked_to(uow, QUOTE, target.target_id))
        origin = _uuid(quote.facts.get("origin_message_id")) if quote is not None else None
        if origin is not None:
            message_ids.add(origin)
        for mid in sorted(message_ids):
            extra = (target.target_id,) if mid == origin else ()
            yield families.derive_message(uow, mid, event=event, extra_quote_ids=extra, cache=cache)


def _on_activated(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    from app.modules.tasks import responsibility

    user_id = _uuid(event.payload.get("user_id"))
    if user_id is None:
        return
    manager = responsibility.membership_user(uow, _uuid(event.payload.get("manager_membership_id")))
    if manager is None:
        manager = responsibility.manager_of(uow, user_id)
    yield from families.derive_onboarding(
        uow, user_id, membership_id=_uuid(event.payload.get("membership_id")), manager_user_id=manager,
        activated_at=event.occurred_at, cache=cache,
    )


def _on_deactivated(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    """Offboarding (events.md §3.1): cancel private reminders, cancel onboarding about the member,
    re-resolve every rule issue they were responsible for (named person → manager → queue), then
    "Reassign N open tasks" for what remains."""
    from app.modules.tasks import responsibility
    from app.modules.tasks.rules import admin

    payload = event.payload or {}
    user_id = _uuid(payload.get("user_id"))
    if user_id is None:
        user_id = responsibility.membership_user(uow, _uuid(payload.get("membership_id")) or event.aggregate_id)
    if user_id is None or responsibility.is_active(uow, user_id):
        return  # nothing to do, or reactivated before this event was processed
    admin.cancel_member_reminders(uow, user_id)
    for key in admin.member_onboarding_keys(uow, user_id):
        yield admin.close_onboarding(uow, key, event)
    derivers = derivers_for(uow)
    for family, root_id in admin.member_rule_issues(uow, user_id, tuple(derivers)):
        yield derivers[family](root_id, cache)
    yield admin.derive_offboarding(
        uow, user_id, reassign_to_user_id=responsibility.membership_user(uow, _uuid(payload.get("reassign_to_membership_id"))),
        event=event,
    )


def _on_dead_lettered(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    from app.modules.tasks.rules import admin

    handler = str((event.payload or {}).get("handler_key") or "")
    prefix, _, source_event = handler.partition(":")
    families = EVENT_FAMILIES.get(source_event, ()) if prefix == CONSUMER else ()
    yield admin.derive_failed_job(uow, event, families)


def _on_generation_failed(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
    from app.modules.tasks.rules import admin

    yield admin.derive_briefing_failures(uow, event)


QUOTE_EVENTS = (
    "sales.quote.created",
    "sales.quote.updated",
    "sales.quote.review_requested",
    "sales.quote.review_withdrawn",
    "sales.quote.issued",
    "sales.quote.marked_sent",
    "sales.quote.won",
    "sales.quote.lost",
    "sales.quote.cancelled",
    "sales.quote.deleted",
    "sales.quote.status_changed",
    "sales.quote.revised",
    "sales.quote.validity_extended",
)
PROPOSAL_EVENTS = (
    "approvals.proposal.submitted",
    "approvals.proposal.approved",
    "approvals.proposal.rejected",
    "approvals.proposal.expired",
    "approvals.proposal.invalidated",
    "approvals.proposal.superseded",
    "approvals.proposal.cancelled",
    "approvals.proposal.executed",
    "approvals.proposal.execution_failed",
)

def _module_trigger(path: str) -> Trigger:
    """A rule family that lives in its owning module (Slice 4: ``app.modules.inventory.rules``), imported lazily."""

    def run(uow: UnitOfWork, event: DomainEvent, cache: SourceCache) -> Iterator[IssueOutcome | None]:
        import importlib

        module, _, name = path.rpartition(".")
        yield from getattr(importlib.import_module(module), name)(uow, event, cache)

    return run


#: Slice-4 families (events.md §4): ops.shortages (root-cause grouping by caused_by), ops.picking, admin.stock_integrity
SLICE4_TRIGGERS: dict[str, tuple[str, str]] = {
    "inventory.shortage.detected": ("app.modules.inventory.rules.on_shortage", "ops.shortages"),
    "inventory.shortage.changed": ("app.modules.inventory.rules.on_shortage", "ops.shortages"),
    "inventory.shortage.resolved": ("app.modules.inventory.rules.on_shortage", "ops.shortages"),
    "inventory.pick_list.released": ("app.modules.inventory.rules.on_pick_list", "ops.picking"),
    "inventory.pick_list.picked": ("app.modules.inventory.rules.on_pick_list", "ops.picking"),
    "inventory.projection.mismatch_detected": ("app.modules.inventory.rules.on_mismatch", "admin.stock_integrity"),
    # production lane: ops.production_dependencies (blocked work orders grouped by their shortage, capacity overloads,
    # incomplete cost rollups)
    **{f"production.work_order.{verb}": ("app.modules.production.rules.on_work_order", "ops.production_dependencies")
       for verb in ("released", "blocked", "unblocked", "completed", "closed", "cancelled")},
    "production.capacity.overloaded": ("app.modules.production.rules.on_overload", "ops.production_dependencies"),
    "production.cost_rollup.computed": ("app.modules.production.rules.on_rollup", "ops.production_dependencies"),
    # procurement / quality / logistics lane: ops.receipts (incl. PO overdue), ops.qc, ops.dispatch_cutoffs
    **{name: ("app.modules.procurement.rules.on_po_event", "ops.receipts") for name in (
        "procurement.purchase_order.approved", "procurement.purchase_order.issued", "procurement.purchase_order.closed",
        "procurement.purchase_order.cancelled", "procurement.purchase_order.became_overdue",
        "procurement.purchase_order_line.expected_date_changed", "procurement.goods_receipt.posted")},
    **{name: ("app.modules.quality.rules.on_inspection", "ops.qc") for name in (
        "quality.inspection.requested", "quality.inspection.passed", "quality.inspection.failed")},
    **{name: ("app.modules.logistics.rules.on_shipment", "ops.dispatch_cutoffs") for name in (
        "logistics.shipment.scheduled", "logistics.shipment.dispatched", "logistics.shipment.delivered",
        "logistics.shipment.exception_recorded")},
}

#: Slice-5 families (events.md §4): fin.invoice_suggestions, fin.invoice_approvals, fin.overdue_invoices,
#: fin.unallocated_receipts, mgmt.margin_exceptions — one dispatcher in the finance module per event
def _slice5_families() -> dict[str, tuple[str, ...]]:
    from app.modules.finance.rules import EVENT_FAMILIES as FINANCE_FAMILIES

    return FINANCE_FAMILIES


SLICE5_TRIGGERS: dict[str, tuple[str, tuple[str, ...]]] = {
    name: ("app.modules.finance.rules.on_event", families) for name, families in _slice5_families().items()
}

TRIGGERS: dict[str, Trigger] = {
    **{name: _module_trigger(path) for name, (path, _family) in SLICE4_TRIGGERS.items()},
    **{name: _module_trigger(path) for name, (path, _families) in SLICE5_TRIGGERS.items()},
    **{name: _on_quote for name in QUOTE_EVENTS},
    **{name: _on_proposal for name in PROPOSAL_EVENTS},
    "sales.customer_message.received": _on_message,
    "sales.customer_message.replied": _on_message,
    "sales.enquiry.received": _on_enquiry,
    "sales.enquiry.assigned": _on_enquiry,
    "sales.enquiry.quoted": _on_enquiry,
    "sales.enquiry.closed": _on_enquiry,
    "parties.party.updated": _on_party_updated,
    "identity.membership.activated": _on_activated,
    "identity.membership.deactivated": _on_deactivated,
    "system.job.dead_lettered": _on_dead_lettered,
    "briefings.briefing.generation_failed": _on_generation_failed,
}

_REPLY_FAMILIES = ("sales.quote_review", "sales.quote_expiry", "sales.customer_replies")
#: rule families each trigger feeds (a dead-lettered delivery marks these partial in briefings)
EVENT_FAMILIES: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(QUOTE_EVENTS, _REPLY_FAMILIES),
    **dict.fromkeys(PROPOSAL_EVENTS, ("common.approvals", "sales.customer_replies")),
    "sales.customer_message.received": ("sales.customer_replies",),
    "sales.customer_message.replied": ("sales.customer_replies",),
    **dict.fromkeys(("sales.enquiry.received", "sales.enquiry.assigned", "sales.enquiry.quoted", "sales.enquiry.closed"),
                    ("sales.enquiries",)),
    "parties.party.updated": ("sales.customer_changes",),
    "identity.membership.activated": ("common.onboarding",),
    "identity.membership.deactivated": ("common.offboarding",),
    **{name: (family,) for name, (_path, family) in SLICE4_TRIGGERS.items()},
    **{name: families for name, (_path, families) in SLICE5_TRIGGERS.items()},
}

#: event aggregate type -> issue-member ref type compared for staleness
_STALENESS_REF = {QUOTE: QUOTE, MESSAGE: MESSAGE, PROPOSAL: PROPOSAL, "sales.enquiry": "sales.enquiry", "parties.party": "parties.party",
                  "inventory.shortage": "inventory.shortage", "inventory.pick_list": "inventory.pick_list",
                  "production.work_order": "production.work_order"}


def is_stale(uow: UnitOfWork, event: DomainEvent) -> bool:
    """An event older than the facts already recorded for its aggregate changes nothing."""
    ref_type = _STALENESS_REF.get(event.aggregate_type)
    if ref_type is None or event.aggregate_id is None or event.aggregate_version is None:
        return False
    stored = uow.session.scalar(
        select(func.max(IssueMember.ref_version))
        .join(Issue, Issue.id == IssueMember.issue_id)
        .where(
            Issue.company_id == uow.actor.company_id,
            Issue.state.in_((IssueState.OPEN.value, IssueState.INFO.value)),
            IssueMember.ref_type == ref_type,
            IssueMember.ref_id == event.aggregate_id,
        )
    )
    return stored is not None and stored > event.aggregate_version


def handle(uow: UnitOfWork, event: DomainEvent) -> int:
    """Process one event. Returns the number of issues reconciled."""
    if (event.payload or {}).get("origin") == "migration":
        return 0
    if not once(uow, CONSUMER, event.id):
        return 0  # replayed delivery
    trigger = TRIGGERS.get(event.event_type)
    if trigger is None or is_stale(uow, event):
        return 0
    cache = SourceCache()
    count = 0
    for outcome in trigger(uow, event, cache):
        if outcome is None:
            continue
        if apply_outcome(uow, outcome, event) is not None:
            count += 1
    return count


def derivers_for(uow: UnitOfWork) -> dict[str, Callable[[uuid.UUID, SourceCache], IssueOutcome | None]]:
    """Families whose issues can be re-derived from the root record alone (current source state)."""
    return {
        "common.approvals": lambda rid, c: families.derive_approval(uow, rid, cache=c),
        "sales.customer_replies": lambda rid, c: families.derive_message(uow, rid, cache=c),
        "sales.quote_review": lambda rid, c: families.derive_quote_review(uow, rid, cache=c),
        "sales.quote_expiry": lambda rid, c: families.derive_quote_expiry(uow, rid, cache=c),
        "sales.enquiries": lambda rid, c: families.derive_enquiry(uow, rid, cache=c),
    }


def rederive_open(uow: UnitOfWork, *, families_only: tuple[str, ...] | None = None) -> int:
    """Re-derive every live issue of the derivable families (visibility consistency, after access changes).
    Manual (re)assignments survive it (``issues.assignment_holds``)."""
    derive_by_family = derivers_for(uow)
    wanted = families_only or tuple(derive_by_family)
    rows = uow.session.execute(
        select(Issue.family, Issue.root_ref_id)
        .where(
            Issue.company_id == uow.actor.company_id,
            Issue.state == IssueState.OPEN.value,
            Issue.family.in_(wanted),
        )
        .order_by(Issue.family, Issue.root_ref_id)
    ).all()
    cache = SourceCache()
    count = 0
    for family, root_id in rows:
        outcome = derive_by_family[family](root_id, cache)
        if outcome is not None and apply_outcome(uow, outcome, None) is not None:
            count += 1
    return count
