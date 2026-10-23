"""Slice-1 rule families. Each derive function re-reads authoritative source state through SourceReaders
(the triggering event is only a hint) and returns the desired state of one issue key.

Families: common.approvals, sales.customer_replies (with draft-quote review grouped under the
originating message), sales.quote_review, sales.quote_expiry, sales.enquiries, sales.customer_changes,
common.onboarding. Business deadlines use the company calendar; display happens in each viewer's zone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select

from app.modules.tasks import issue_keys as keys
from app.modules.tasks import responsibility
from app.modules.tasks.completion import QUOTE_CLOSED_STATUSES, as_uuid, reply_state
from app.modules.tasks.models import (
    DueKind,
    Issue,
    IssueMember,
    IssueResolution,
    IssueState,
    MemberRole,
    OnboardingTemplate,
    TaskState,
)
from app.modules.tasks.rules.outcome import ChangeSpec, Closure, IssueOutcome, MemberSpec, TaskSpec
from app.modules.tasks.visibility import SourceCache
from app.platform.events.models import DomainEvent
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

QUOTE = "sales.quote"
MESSAGE = "sales.customer_message"
ENQUIRY = "sales.enquiry"
PARTY = "parties.party"
PROPOSAL = "approvals.proposal"

OPEN_QUOTE_FOR_EXPIRY = frozenset({"sent", "revised"})
ENQUIRY_OPEN = frozenset({"received", "open", "assigned", "new"})
SLA_WORKDAYS = 1

_CHANGED_FIELD_LABELS = {
    "addresses.shipping": "shipping address",
    "addresses.billing": "billing address",
    "contacts": "contacts",
    "name": "name",
    "owner_user_id": "account owner",
    "payment_terms": "payment terms",
    "currency": "currency",
}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _d(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _closer(event: DomainEvent | None) -> uuid.UUID | None:
    if event is None or event.actor_type not in ("user", "agent"):
        return None
    return event.actor_user_id


def sla_due(uow: UnitOfWork, received_at: datetime, workdays: int = SLA_WORKDAYS) -> datetime:
    """Shift end of the n-th working day after the receipt's work date (company calendar)."""
    cal = responsibility.company_calendar(uow)
    return cal.shift_bounds(cal.next_working_day(cal.work_date(received_at), workdays))[1]


def end_of_work_date_due(uow: UnitOfWork, at: datetime) -> datetime:
    cal = responsibility.company_calendar(uow)
    return cal.end_of_day_due(cal.work_date(at))


def _closing_outcome(
    uow: UnitOfWork, issue_key: str, closure: Closure, resolution: str
) -> IssueOutcome | None:
    """Close whatever is open under ``issue_key`` (source deleted or no longer readable)."""
    from app.modules.tasks.issues import live_issue

    issue = live_issue(uow, issue_key, for_update=False)
    if issue is None:
        return None
    members = uow.session.scalars(
        select(IssueMember).where(IssueMember.issue_id == issue.id, IssueMember.active.is_(True))
    ).all()
    return IssueOutcome(
        issue_key=issue_key,
        family=issue.family,
        root_ref_type=issue.root_ref_type,
        root_ref_id=issue.root_ref_id,
        title=issue.title,
        title_facts=issue.title_facts,
        required_permission=issue.required_permission,
        scope_owner_id=issue.scope_owner_id,
        scope_branch_id=issue.scope_branch_id,
        info=False,
        members=[
            MemberSpec(m.member_key, m.ref_type, m.ref_id, m.ref_version, m.label, m.facts, m.required_permission,
                       m.role, m.scope_owner_id, m.scope_branch_id)
            for m in members
        ],
        tasks=[],
        closure=closure,
        resolution=resolution,
    )


def _quote_member(q: SourceFacts, role: str = MemberRole.EVIDENCE.value) -> MemberSpec:
    facts = {
        "quote_number": q.facts.get("quote_number"),
        "party_name": q.facts.get("party_name"),
        "status": q.status,
        "valid_until": q.facts.get("valid_until"),
        "revision_no": q.facts.get("revision_no"),
        "money": [{"amount": m.amount, "currency": m.currency} for m in q.money],
    }
    return MemberSpec(
        key=f"quote:{q.source_id}", ref_type=QUOTE, ref_id=q.source_id, ref_version=q.version, label=q.label,
        facts=facts, required_permission=q.required_permission or "sales.quote.read", role=role,
        scope_owner_id=q.owner_user_id, scope_branch_id=q.branch_id,
    )


def open_approval_keys_for(uow: UnitOfWork, ref_type: str, ref_id: uuid.UUID) -> list[str]:
    rows = uow.session.scalars(
        select(Issue.issue_key)
        .join(IssueMember, IssueMember.issue_id == Issue.id)
        .where(
            Issue.company_id == uow.actor.company_id,
            Issue.family == "common.approvals",
            Issue.state == IssueState.OPEN.value,
            IssueMember.ref_type == ref_type,
            IssueMember.ref_id == ref_id,
            IssueMember.active.is_(True),
        )
        .order_by(Issue.issue_key)
    )
    return list(dict.fromkeys(rows))


def messages_linked_to(uow: UnitOfWork, ref_type: str, ref_id: uuid.UUID) -> list[uuid.UUID]:
    rows = uow.session.scalars(
        select(Issue.root_ref_id)
        .join(IssueMember, IssueMember.issue_id == Issue.id)
        .where(
            Issue.company_id == uow.actor.company_id,
            Issue.family == "sales.customer_replies",
            Issue.state.in_((IssueState.OPEN.value, IssueState.INFO.value)),
            IssueMember.ref_type == ref_type,
            IssueMember.ref_id == ref_id,
        )
        .order_by(Issue.root_ref_id)
    )
    return list(dict.fromkeys(rows))


def _review_task(uow: UnitOfWork, q: SourceFacts, first_seen: datetime) -> TaskSpec:
    created_at = _dt(q.facts.get("created_at")) or first_seen
    named = responsibility.resolve(uow, "sales.quote_review", [q.owner_user_id])
    return TaskSpec(
        dedup_key=f"review:{q.source_id}",
        kind="review_draft",
        title=f"Review draft {q.facts.get('quote_number') or q.label}",
        completion_check="quote_left_draft",
        required_permission=q.required_permission or "sales.quote.read",
        facts={"quote_number": q.facts.get("quote_number"), "party_name": q.facts.get("party_name"),
               "origin": q.facts.get("origin")},
        primary_ref_type=QUOTE, primary_ref_id=q.source_id, primary_ref_version=q.version,
        owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
        due_kind=DueKind.SOFT.value, due_at=end_of_work_date_due(uow, created_at),
        scope_owner_id=q.owner_user_id, scope_branch_id=q.branch_id, branch_id=q.branch_id,
    )


def _review_closure(q: SourceFacts | None, event: DomainEvent | None) -> Closure:
    if q is None or q.status in ("deleted", "cancelled"):
        return Closure(TaskState.CANCELLED.value, {"reason": "quote_withdrawn"}, _closer(event))
    return Closure(TaskState.DONE.value, {"reason": "quote_left_draft", "status": q.status}, _closer(event))


# ---- sales.customer_replies (msg:{id}) --------------------------------------------------------------
def derive_message(
    uow: UnitOfWork,
    message_id: uuid.UUID,
    *,
    event: DomainEvent | None = None,
    extra_quote_ids: tuple[uuid.UUID, ...] = (),
    cache: SourceCache | None = None,
) -> IssueOutcome | None:
    cache = cache or SourceCache()
    key = keys.message_key(message_id)
    m = cache.read(uow, MESSAGE, message_id)
    if m is None:
        return _closing_outcome(uow, key, Closure(TaskState.CANCELLED.value, {"reason": "message_removed"}, _closer(event)),
                                IssueResolution.SOURCE_CLOSED.value)
    received_at = _dt(m.facts.get("received_at")) or (event.occurred_at if event else uow.now())
    party_id = m.facts.get("party_id")
    party = cache.read(uow, PARTY, as_uuid(party_id)) if party_id else None
    party_name = m.facts.get("party_name") or (party.label if party else m.label)
    named = responsibility.resolve(
        uow, "sales.customer_replies", [m.owner_user_id, party.owner_user_id if party else None]
    )
    quote_ids: list[uuid.UUID] = [as_uuid(q) for q in (m.facts.get("linked_quote_ids") or [])]
    quote_ids += list(extra_quote_ids)
    from app.modules.tasks.issues import live_issue

    existing = live_issue(uow, key, for_update=False)
    if existing is not None:
        quote_ids += list(
            uow.session.scalars(
                select(IssueMember.ref_id).where(
                    IssueMember.issue_id == existing.id, IssueMember.ref_type == QUOTE, IssueMember.active.is_(True)
                )
            )
        )
    quote_ids = list(dict.fromkeys(quote_ids))
    members = [
        MemberSpec(
            key=f"message:{message_id}", ref_type=MESSAGE, ref_id=message_id, ref_version=m.version, label=m.label,
            facts={"status": m.status, "party_name": party_name, "contact_name": m.facts.get("contact_name"),
                   "channel": m.facts.get("channel"), "replied_at": m.facts.get("replied_at")},
            required_permission=m.required_permission or "sales.customer_message.read", role=MemberRole.ROOT.value,
            scope_owner_id=m.owner_user_id, scope_branch_id=m.branch_id,
        )
    ]
    tasks: list[TaskSpec] = []
    closures: dict[str, Closure] = {}
    depends: list[tuple[str, str]] = []
    first_seen = existing.first_seen_at if existing is not None else received_at
    quote_numbers: list[str] = []
    for qid in quote_ids:
        q = cache.read(uow, QUOTE, qid)
        if q is None:
            closures[f"review:{qid}"] = _review_closure(None, event)
            continue
        members.append(_quote_member(q))
        if q.facts.get("quote_number"):
            quote_numbers.append(str(q.facts["quote_number"]))
        if q.status == "draft":
            tasks.append(_review_task(uow, q, first_seen))
        else:
            closures[f"review:{qid}"] = _review_closure(q, event)
        for approval in open_approval_keys_for(uow, QUOTE, qid):
            depends.append((approval, "approval_decided"))

    state = reply_state(uow, message_id, read=lambda t, i: cache.read(uow, t, i))
    if not state.complete:
        tasks.insert(
            0,
            TaskSpec(
                dedup_key=f"reply:{message_id}",
                kind="reply_needed",
                title=f"Reply to {party_name}",
                completion_check="reply_sent",
                required_permission=m.required_permission or "sales.customer_message.read",
                facts={"party_name": party_name, "contact_name": m.facts.get("contact_name"),
                       "channel": m.facts.get("channel"), "received_at": received_at.isoformat(),
                       "quote_numbers": quote_numbers},
                primary_ref_type=MESSAGE, primary_ref_id=message_id, primary_ref_version=m.version,
                owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value, due_at=sla_due(uow, received_at),
                scope_owner_id=m.owner_user_id, scope_branch_id=m.branch_id, branch_id=m.branch_id,
                depends_on=tuple(dict.fromkeys(depends)),
            ),
        )
    else:
        closures[f"reply:{message_id}"] = Closure(TaskState.DONE.value, dict(state.evidence), _closer(event))
    return IssueOutcome(
        issue_key=key,
        family="sales.customer_replies",
        root_ref_type=MESSAGE,
        root_ref_id=message_id,
        title=f"Reply to {party_name}",
        title_facts={"party_name": party_name, "contact_name": m.facts.get("contact_name"), "channel": m.facts.get("channel")},
        required_permission=m.required_permission or "sales.customer_message.read",
        scope_owner_id=named.owner_user_id or m.owner_user_id,
        scope_branch_id=m.branch_id,
        members=members,
        tasks=tasks,
        closure=Closure(TaskState.CANCELLED.value, {"reason": "no_longer_needed"}, _closer(event)),
        closures=closures,
        resolution=IssueResolution.COMPLETED.value,
        first_seen_at=received_at,
        root_version=m.version,
    )


# ---- sales.quote_review (quote:{id}:review; only when no originating message) -------------------------
def derive_quote_review(
    uow: UnitOfWork, quote_id: uuid.UUID, *, event: DomainEvent | None = None, cache: SourceCache | None = None
) -> IssueOutcome | None:
    cache = cache or SourceCache()
    key = keys.quote_review_key(quote_id)
    q = cache.read(uow, QUOTE, quote_id)
    if q is None:
        return _closing_outcome(uow, key, _review_closure(None, event), IssueResolution.SOURCE_CLOSED.value)
    if q.facts.get("origin_message_id"):
        return None  # grouped under the originating message (msg:{id})
    from app.modules.tasks.issues import live_issue

    existing = live_issue(uow, key, for_update=False)
    first_seen = existing.first_seen_at if existing else (_dt(q.facts.get("created_at")) or (event.occurred_at if event else uow.now()))
    tasks = [_review_task(uow, q, first_seen)] if q.status == "draft" else []
    return IssueOutcome(
        issue_key=key,
        family="sales.quote_review",
        root_ref_type=QUOTE,
        root_ref_id=quote_id,
        title=f"Review draft {q.facts.get('quote_number') or q.label}",
        title_facts={"quote_number": q.facts.get("quote_number"), "party_name": q.facts.get("party_name")},
        required_permission=q.required_permission or "sales.quote.read",
        scope_owner_id=q.owner_user_id,
        scope_branch_id=q.branch_id,
        members=[_quote_member(q, MemberRole.ROOT.value)],
        tasks=tasks,
        closure=_review_closure(q, event),
        resolution=IssueResolution.COMPLETED.value if q.status != "deleted" else IssueResolution.SOURCE_CLOSED.value,
        first_seen_at=first_seen,
        root_version=q.version,
    )


# ---- sales.quote_expiry (quote:{id}:expiry) ------------------------------------------------------------
def quote_valid_until_end(uow: UnitOfWork, q: SourceFacts) -> datetime | None:
    if q.deadlines.get("valid_until_end") is not None:
        return q.deadlines["valid_until_end"]
    valid_until = _d(q.facts.get("valid_until"))
    if valid_until is None:
        return None
    cal = responsibility.company_calendar(uow)
    return datetime.combine(valid_until + timedelta(days=1), time(0, 0), tzinfo=cal.tz)


def derive_quote_expiry(
    uow: UnitOfWork, quote_id: uuid.UUID, *, event: DomainEvent | None = None, cache: SourceCache | None = None
) -> IssueOutcome | None:
    cache = cache or SourceCache()
    key = keys.quote_expiry_key(quote_id)
    q = cache.read(uow, QUOTE, quote_id)
    if q is None:
        return _closing_outcome(uow, key, Closure(TaskState.CANCELLED.value, {"reason": "quote_removed"}, _closer(event)),
                                IssueResolution.SOURCE_CLOSED.value)
    due = quote_valid_until_end(uow, q)
    valid_until = q.facts.get("valid_until")
    tasks: list[TaskSpec] = []
    named = responsibility.resolve(uow, "sales.quote_expiry", [q.owner_user_id])
    number = q.facts.get("quote_number") or q.label
    lapsed = due is not None and due <= uow.now()
    if q.status in OPEN_QUOTE_FOR_EXPIRY and due is not None and not q.is_closed and not lapsed:
        tasks.append(
            TaskSpec(
                dedup_key=f"expiry:{quote_id}:{valid_until}",
                kind="quote_expiry",
                title=f"{number} expires on {valid_until}",
                completion_check="quote_expiry_resolved",
                required_permission=q.required_permission or "sales.quote.read",
                facts={"quote_number": number, "party_name": q.facts.get("party_name"), "valid_until": valid_until},
                primary_ref_type=QUOTE, primary_ref_id=quote_id, primary_ref_version=q.version,
                owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
                due_kind=DueKind.HARD.value, due_at=due,
                scope_owner_id=q.owner_user_id, scope_branch_id=q.branch_id, branch_id=q.branch_id,
            )
        )
    resolution = IssueResolution.COMPLETED.value
    if q.status in QUOTE_CLOSED_STATUSES or q.is_closed:
        withdrawn = q.status in ("cancelled", "deleted")
        state = TaskState.CANCELLED.value if withdrawn else TaskState.DONE.value
        closure = Closure(state, {"reason": f"quote_{q.status}", "status": q.status}, _closer(event))
        if withdrawn:
            resolution = IssueResolution.SOURCE_CLOSED.value
    elif lapsed:
        # the validity ran out with the quote still open: the same resolution the overdue sweep records
        closure = Closure(TaskState.EXPIRED.value, {"reason": "quote_lapsed"})
        resolution = IssueResolution.SOURCE_CLOSED.value
    else:
        closure = Closure(TaskState.DONE.value, {"reason": "validity_extended", "valid_until": valid_until}, _closer(event))
    from app.modules.tasks.issues import live_issue

    existing = live_issue(uow, key, for_update=False)
    return IssueOutcome(
        issue_key=key,
        family="sales.quote_expiry",
        root_ref_type=QUOTE,
        root_ref_id=quote_id,
        title=f"{number} expiry",
        title_facts={"quote_number": number, "party_name": q.facts.get("party_name")},
        required_permission=q.required_permission or "sales.quote.read",
        scope_owner_id=q.owner_user_id,
        scope_branch_id=q.branch_id,
        members=[_quote_member(q, MemberRole.ROOT.value)],
        tasks=tasks,
        closure=closure,
        resolution=resolution,
        first_seen_at=existing.first_seen_at if existing else (_dt(q.facts.get("sent_at")) or (event.occurred_at if event else uow.now())),
        root_version=q.version,
    )


# ---- common.approvals (approval:{proposal}) -----------------------------------------------------------
_PROPOSAL_CLOSURE = {
    "approved": (TaskState.DONE.value, IssueResolution.COMPLETED.value),
    "rejected": (TaskState.DONE.value, IssueResolution.COMPLETED.value),
    "expired": (TaskState.EXPIRED.value, IssueResolution.SOURCE_CLOSED.value),
    "invalidated": (TaskState.CANCELLED.value, IssueResolution.SOURCE_CLOSED.value),
    "superseded": (TaskState.CANCELLED.value, IssueResolution.SUPERSEDED.value),
    "withdrawn": (TaskState.CANCELLED.value, IssueResolution.SOURCE_CLOSED.value),
}


def proposal_target_quote(uow: UnitOfWork, proposal: Any, cache: SourceCache) -> SourceFacts | None:
    from app.modules.approvals import service as approvals

    for target in approvals.targets_of(uow, proposal):
        if target.target_type == QUOTE:
            return cache.read(uow, QUOTE, target.target_id)
    return None


def approval_title(proposal: Any, quote: SourceFacts | None) -> str:
    exceptions = list((proposal.facts or {}).get("exceptions") or [])
    if quote is None:
        return proposal.title
    number = quote.facts.get("quote_number") or quote.label
    party = quote.facts.get("party_name")
    suffix = f" ({party})" if party else ""
    if "price_override" in exceptions:
        return f"Approve price override on {number}{suffix}"
    if exceptions:
        return f"Approve {number}{suffix}"
    return f"Review {number}{suffix}"


def derive_approval(
    uow: UnitOfWork, proposal_id: uuid.UUID, *, event: DomainEvent | None = None, cache: SourceCache | None = None
) -> IssueOutcome | None:
    from app.core.errors import NotFound
    from app.modules.approvals import service as approvals

    cache = cache or SourceCache()
    key = keys.approval_key(proposal_id)
    try:
        proposal = approvals.get(uow, proposal_id)
    except NotFound:
        return _closing_outcome(uow, key, Closure(TaskState.CANCELLED.value, {"reason": "proposal_removed"}),
                                IssueResolution.SOURCE_CLOSED.value)
    targets = approvals.targets_of(uow, proposal)
    quote = proposal_target_quote(uow, proposal, cache)
    title = approval_title(proposal, quote)
    exceptions = list((proposal.facts or {}).get("exceptions") or [])
    members = [
        MemberSpec(
            key=f"proposal:{proposal.id}", ref_type=PROPOSAL, ref_id=proposal.id, ref_version=proposal.version,
            label=proposal.title, required_permission="approvals.proposal.read", role=MemberRole.ROOT.value,
            facts={"status": proposal.status, "version": proposal.version, "content_hash": proposal.content_hash,
                   "exceptions": exceptions, "kind": proposal.kind},
            scope_owner_id=proposal.requested_by,
        )
    ]
    branch_id = None
    for target in targets:
        if target.target_type == QUOTE and quote is not None:
            members.append(_quote_member(quote))
            branch_id = quote.branch_id
    expired_now = proposal.status == "pending" and proposal.expires_at is not None and proposal.expires_at <= uow.now()
    pending = proposal.status == "pending" and not expired_now
    tasks: list[TaskSpec] = []
    if pending:
        candidates = tuple(responsibility.eligible_approvers(uow, proposal))
        cal = responsibility.company_calendar(uow)
        tasks.append(
            TaskSpec(
                dedup_key=f"approval:{proposal.id}",
                kind="approval_decision",
                title=title,
                completion_check="approval_decided",
                required_permission="approvals.proposal.read",
                facts={"proposal_version": proposal.version, "content_hash": proposal.content_hash,
                       "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
                       "exceptions": exceptions, "kind": proposal.kind,
                       "quote_number": quote.facts.get("quote_number") if quote else None,
                       "party_name": quote.facts.get("party_name") if quote else None},
                primary_ref_type=PROPOSAL, primary_ref_id=proposal.id, primary_ref_version=proposal.version,
                initiator_user_id=proposal.requested_by,
                queue_code=None if candidates else "admin",
                due_kind=DueKind.SOFT.value, due_at=cal.end_of_day_due(cal.work_date(proposal.created_at)),
                scope_owner_id=proposal.requested_by, scope_branch_id=branch_id, branch_id=branch_id,
                candidates=candidates,
            )
        )
    status = "expired" if expired_now else proposal.status
    task_state, resolution = _PROPOSAL_CLOSURE.get(status, (TaskState.CANCELLED.value, IssueResolution.SOURCE_CLOSED.value))
    evidence = {"decision": status}
    if proposal.decided_by is not None:
        evidence["decided_by"] = str(proposal.decided_by)
    return IssueOutcome(
        issue_key=key,
        family="common.approvals",
        root_ref_type=PROPOSAL,
        root_ref_id=proposal.id,
        title=title,
        title_facts={"quote_number": quote.facts.get("quote_number") if quote else None,
                     "party_name": quote.facts.get("party_name") if quote else None, "exceptions": exceptions},
        required_permission="approvals.proposal.read",
        scope_owner_id=proposal.requested_by,
        scope_branch_id=branch_id,
        members=members,
        tasks=tasks,
        closure=Closure(task_state, evidence, proposal.decided_by or _closer(event)),
        resolution=resolution,
        first_seen_at=proposal.created_at,
        root_version=proposal.version,
    )


# ---- sales.enquiries (enquiry:{id}) --------------------------------------------------------------------
def derive_enquiry(
    uow: UnitOfWork, enquiry_id: uuid.UUID, *, event: DomainEvent | None = None, cache: SourceCache | None = None
) -> IssueOutcome | None:
    cache = cache or SourceCache()
    key = keys.enquiry_key(enquiry_id)
    e = cache.read(uow, ENQUIRY, enquiry_id)
    if e is None:
        return _closing_outcome(uow, key, Closure(TaskState.CANCELLED.value, {"reason": "enquiry_removed"}),
                                IssueResolution.SOURCE_CLOSED.value)
    received_at = _dt(e.facts.get("received_at")) or (event.occurred_at if event else uow.now())
    party_name = e.facts.get("party_name") or e.label
    number = e.facts.get("enquiry_number") or e.label
    named = responsibility.resolve(uow, "sales.enquiries", [e.owner_user_id])
    tasks: list[TaskSpec] = []
    if e.status in ENQUIRY_OPEN and not e.is_closed:
        tasks.append(
            TaskSpec(
                dedup_key=f"enquiry:{enquiry_id}",
                kind="enquiry_reply",
                title=f"Answer enquiry {number} from {party_name}",
                completion_check="enquiry_answered",
                required_permission=e.required_permission or "sales.enquiry.read",
                facts={"enquiry_number": number, "party_name": party_name, "channel": e.facts.get("channel"),
                       "received_at": received_at.isoformat()},
                primary_ref_type=ENQUIRY, primary_ref_id=enquiry_id, primary_ref_version=e.version,
                owner_user_id=named.owner_user_id, assignee_user_id=named.assignee_user_id, queue_code=named.queue_code,
                due_kind=DueKind.SOFT.value, due_at=sla_due(uow, received_at),
                scope_owner_id=e.owner_user_id, scope_branch_id=e.branch_id, branch_id=e.branch_id,
            )
        )
    return IssueOutcome(
        issue_key=key,
        family="sales.enquiries",
        root_ref_type=ENQUIRY,
        root_ref_id=enquiry_id,
        title=f"Enquiry {number} from {party_name}",
        title_facts={"enquiry_number": number, "party_name": party_name},
        required_permission=e.required_permission or "sales.enquiry.read",
        scope_owner_id=e.owner_user_id,
        scope_branch_id=e.branch_id,
        members=[
            MemberSpec(
                key=f"enquiry:{enquiry_id}", ref_type=ENQUIRY, ref_id=enquiry_id, ref_version=e.version, label=e.label,
                facts={"status": e.status, "enquiry_number": number, "party_name": party_name},
                required_permission=e.required_permission or "sales.enquiry.read", role=MemberRole.ROOT.value,
                scope_owner_id=e.owner_user_id, scope_branch_id=e.branch_id,
            )
        ],
        tasks=tasks,
        closure=Closure(TaskState.DONE.value, {"reason": f"enquiry_{e.status}"}, _closer(event)),
        resolution=IssueResolution.COMPLETED.value,
        first_seen_at=received_at,
        root_version=e.version,
    )


# ---- sales.customer_changes (info:party:{id}) ------------------------------------------------------------
def humanize_changed_fields(fields: list[str]) -> str:
    labels = [_CHANGED_FIELD_LABELS.get(f, f.split(".")[-1].replace("_", " ")) for f in fields]
    labels = list(dict.fromkeys(labels))
    if not labels:
        return "details"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def derive_party_change(uow: UnitOfWork, party_id: uuid.UUID, event: DomainEvent, *, cache: SourceCache | None = None) -> IssueOutcome | None:
    cache = cache or SourceCache()
    party = cache.read(uow, PARTY, party_id)
    if party is None:
        return None
    changed = [str(f) for f in (event.payload.get("changed_fields") or [])]
    name = party.facts.get("name") or party.label
    what = humanize_changed_fields(changed)
    return IssueOutcome(
        issue_key=keys.party_info_key(party_id),
        family="sales.customer_changes",
        root_ref_type=PARTY,
        root_ref_id=party_id,
        title=f"{name} {what} updated",
        title_facts={"party_name": name, "last_change": {"event_id": str(event.id), "changed_fields": changed,
                                                          "at": event.occurred_at.isoformat()}},
        required_permission=party.required_permission or "parties.party.read",
        scope_owner_id=party.owner_user_id,
        scope_branch_id=party.branch_id,
        info=True,
        members=[
            MemberSpec(
                key=f"party:{party_id}", ref_type=PARTY, ref_id=party_id, ref_version=party.version, label=party.label,
                facts={"name": name}, required_permission=party.required_permission or "parties.party.read",
                role=MemberRole.ROOT.value, scope_owner_id=party.owner_user_id, scope_branch_id=party.branch_id,
            )
        ],
        changes=[
            ChangeSpec(
                change_code="party.updated", ref_type=PARTY, ref_id=party_id, ref_version=party.version,
                fact_at=event.occurred_at, before=None, after={"changed_fields": changed}, actor_user_id=event.actor_user_id,
            )
        ],
        resolution=None,
        first_seen_at=event.occurred_at,
        root_version=party.version,
    )


# ---- common.onboarding (onboarding:{user}:{step}) ---------------------------------------------------------
def onboarding_template_for(uow: UnitOfWork, membership_id: uuid.UUID | None, cache: SourceCache) -> OnboardingTemplate | None:
    role_keys: list[str] = []
    if membership_id is not None:
        membership = cache.read(uow, "identity.membership", membership_id)
        if membership is not None:
            role_keys = [str(r) for r in (membership.facts.get("role_templates") or [])]
    role_keys.append("employee")
    rows = uow.session.scalars(
        select(OnboardingTemplate)
        .where(OnboardingTemplate.company_id == uow.actor.company_id, OnboardingTemplate.active.is_(True))
        .order_by(OnboardingTemplate.template_version.desc())
    ).all()
    by_role: dict[str, OnboardingTemplate] = {}
    for row in rows:
        by_role.setdefault(row.role_key, row)
    for role in role_keys:
        if role in by_role:
            return by_role[role]
    return None


def derive_onboarding(
    uow: UnitOfWork,
    user_id: uuid.UUID,
    *,
    membership_id: uuid.UUID | None,
    manager_user_id: uuid.UUID | None,
    activated_at: datetime,
    cache: SourceCache | None = None,
) -> list[IssueOutcome]:
    cache = cache or SourceCache()
    cal = responsibility.company_calendar(uow)
    work_date = cal.work_date(activated_at)
    steps_due = cal.end_of_day_due(work_date)
    template = onboarding_template_for(uow, membership_id, cache)
    names = responsibility.display_names(uow, [user_id])
    first = responsibility.first_name(names.get(user_id))
    branch_id = responsibility.default_branch_of(uow, user_id)
    outcomes: list[IssueOutcome] = []
    user_member = MemberSpec(
        key=f"user:{user_id}", ref_type="identity.user", ref_id=user_id, ref_version=None, label=names.get(user_id, ""),
        facts={}, required_permission="org.directory.read", role=MemberRole.ROOT.value, scope_owner_id=user_id,
    )
    for step in (template.steps if template else []):
        step_key = str(step["step_key"])
        title = str(step["title"])
        outcomes.append(
            IssueOutcome(
                issue_key=keys.onboarding_key(user_id, step_key),
                family="common.onboarding",
                root_ref_type="identity.user",
                root_ref_id=user_id,
                title=title,
                title_facts={"step_key": step_key},
                required_permission="tasks.task.read",
                scope_owner_id=user_id,
                scope_branch_id=branch_id,
                members=[user_member],
                tasks=[
                    TaskSpec(
                        dedup_key=f"onboarding:{user_id}:{step_key}",
                        kind="onboarding_step",
                        title=title,
                        completion_check=str(step.get("completion_check") or "assertion"),
                        required_permission="tasks.task.read",
                        facts={"step_key": step_key, "template": template.role_key if template else None},
                        primary_ref_type="identity.user", primary_ref_id=user_id,
                        owner_user_id=user_id, assignee_user_id=user_id,
                        due_kind=DueKind.SOFT.value, due_at=steps_due,
                        scope_owner_id=user_id, scope_branch_id=branch_id, branch_id=branch_id,
                    )
                ],
                first_seen_at=activated_at,
            )
        )
    if manager_user_id is not None and responsibility.is_active(uow, manager_user_id):
        days = template.checkin_after_workdays if template else 2
        checkin_date = cal.next_working_day(work_date, days) if days > 0 else work_date
        outcomes.append(
            IssueOutcome(
                issue_key=keys.onboarding_key(user_id, "checkin"),
                family="common.onboarding",
                root_ref_type="identity.user",
                root_ref_id=user_id,
                title=f"Check in with {first}",
                title_facts={"step_key": "checkin", "new_member": first},
                required_permission="tasks.task.read",
                scope_owner_id=manager_user_id,
                scope_branch_id=branch_id,
                members=[user_member],
                tasks=[
                    TaskSpec(
                        dedup_key=f"onboarding:{user_id}:checkin",
                        kind="onboarding_checkin",
                        title=f"Check in with {first}",
                        completion_check="assertion",
                        required_permission="tasks.task.read",
                        facts={"new_member": first},
                        primary_ref_type="identity.user", primary_ref_id=user_id,
                        owner_user_id=manager_user_id, assignee_user_id=None,
                        due_kind=DueKind.SOFT.value, due_at=cal.end_of_day_due(checkin_date),
                        scope_owner_id=manager_user_id, scope_branch_id=branch_id, branch_id=branch_id,
                    )
                ],
                first_seen_at=activated_at,
            )
        )
    return outcomes


def activation_time(uow: UnitOfWork, user_id: uuid.UUID) -> datetime | None:
    """When the member was activated, from the onboarding issues the activation event opened."""
    from sqlalchemy import func

    return uow.session.scalar(
        select(func.min(Issue.first_seen_at)).where(
            Issue.company_id == uow.actor.company_id,
            Issue.family == "common.onboarding",
            Issue.root_ref_type == "identity.user",
            Issue.root_ref_id == user_id,
        )
    )
