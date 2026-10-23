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

TRIGGERS: dict[str, Trigger] = {
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
}

#: event aggregate type -> issue-member ref type compared for staleness
_STALENESS_REF = {QUOTE: QUOTE, MESSAGE: MESSAGE, PROPOSAL: PROPOSAL, "sales.enquiry": "sales.enquiry", "parties.party": "parties.party"}


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


def rederive_open(uow: UnitOfWork, *, families_only: tuple[str, ...] | None = None) -> int:
    """Re-derive every live issue of the derivable families (visibility consistency, after access changes)."""
    derive_by_family: dict[str, Callable[[uuid.UUID, SourceCache], IssueOutcome | None]] = {
        "common.approvals": lambda rid, c: families.derive_approval(uow, rid, cache=c),
        "sales.customer_replies": lambda rid, c: families.derive_message(uow, rid, cache=c),
        "sales.quote_review": lambda rid, c: families.derive_quote_review(uow, rid, cache=c),
        "sales.quote_expiry": lambda rid, c: families.derive_quote_expiry(uow, rid, cache=c),
        "sales.enquiries": lambda rid, c: families.derive_enquiry(uow, rid, cache=c),
    }
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
