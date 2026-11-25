"""Completion checks: "Mark handled" verifies the obligation against its source, never on trust.

Each task stores a ``completion_check`` code. The check re-reads the authoritative source through the
owning module's SourceReader and returns evidence when complete, or the remaining conditions. Manual
tasks and check-ins use an ``assertion`` check (the responsible person confirms). When a source cannot
be read (reader not installed), the check reports ``cannot_verify`` instead of guessing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.platform import sources
from app.platform.uow import UnitOfWork

if TYPE_CHECKING:
    from app.modules.tasks.models import Task

QUOTE_CLOSED_STATUSES = frozenset({"won", "lost", "cancelled", "archived", "deleted"})
QUOTE_SENT_STATUSES = frozenset({"sent", "revised", "won", "lost"})
ENQUIRY_DONE_STATUSES = frozenset({"quoted", "closed"})


@dataclass(frozen=True)
class CompletionResult:
    complete: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    remaining: list[str] = field(default_factory=list)


Check = Callable[[UnitOfWork, "Task"], CompletionResult]
_CHECKS: dict[str, Check] = {}


def register(code: str) -> Callable[[Check], Check]:
    def deco(fn: Check) -> Check:
        _CHECKS[code] = fn
        return fn

    return deco


def check(uow: UnitOfWork, task: Task) -> CompletionResult:
    fn = _CHECKS.get(task.completion_check)
    if fn is None:
        return CompletionResult(False, remaining=[f"unknown_check:{task.completion_check}"])
    return fn(uow, task)


def known_checks() -> frozenset[str]:
    return frozenset(_CHECKS)


#: the SourceReader each source-verified check needs; without it the check can only say cannot_verify
CHECK_SOURCES: dict[str, str] = {
    "reply_sent": "sales.customer_message",
    "quote_left_draft": "sales.quote",
    "quote_expiry_resolved": "sales.quote",
    "enquiry_answered": "sales.enquiry",
    "lead_followed_up": "parties.party",
    "pref_briefing_saved": "identity.user_preference",
    "recent_record_exists": "ui.recent_record",
    "recent_search_exists": "search.recent",
}


def verifiable(completion_check: str) -> bool:
    """Whether "mark handled" can ever succeed for this check right now: approvals are decided through
    the approvals engine, and a source-verified check needs its reader installed (no dead controls)."""
    if completion_check not in _CHECKS or completion_check == "approval_decided":
        return False
    source_type = CHECK_SOURCES.get(completion_check)
    return source_type is None or sources.has_reader(source_type)


def as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def reply_state(
    uow: UnitOfWork,
    message_id: Any,
    read: Callable[[str, Any], Any] | None = None,
    *,
    quote_ids: Iterable[Any] = (),
) -> CompletionResult:
    """A reply obligation ends when the message is replied or a linked quote was sent after it arrived.

    Linked quotes are the message's ``linked_quote_ids`` plus ``quote_ids`` the caller knows are linked
    (quotes whose ``origin_message_id`` is the message, and quote members of the message's issue)."""
    reader = read or (lambda t, i: sources.read(uow, t, i))
    message = reader("sales.customer_message", message_id)
    if message is None:
        return CompletionResult(False, remaining=["cannot_verify:sales.customer_message"])
    replied_at = message.facts.get("replied_at")
    if message.status == "replied" or replied_at:
        return CompletionResult(True, {"reason": "message_replied", "replied_at": replied_at})
    received_at = _parse_dt(message.facts.get("received_at"))
    linked = [as_uuid(q) for q in (message.facts.get("linked_quote_ids") or [])] + [as_uuid(q) for q in quote_ids]
    for quote_id in dict.fromkeys(linked):
        quote = reader("sales.quote", quote_id)
        if quote is None:
            continue
        sent_at = _parse_dt(quote.facts.get("sent_at"))
        if quote.status in QUOTE_SENT_STATUSES and sent_at and (received_at is None or sent_at >= received_at):
            return CompletionResult(
                True, {"reason": "linked_quote_sent", "quote_number": quote.facts.get("quote_number"), "sent_at": str(sent_at)}
            )
    return CompletionResult(False, remaining=["reply_to_customer"])


def issue_quote_ids(uow: UnitOfWork, issue_id: uuid.UUID) -> list[uuid.UUID]:
    """Quotes grouped under a message's issue (linked by the message or by their ``origin_message_id``)."""
    from sqlalchemy import select

    from app.modules.tasks.models import IssueMember

    return list(
        uow.session.scalars(
            select(IssueMember.ref_id)
            .where(IssueMember.issue_id == issue_id, IssueMember.ref_type == "sales.quote", IssueMember.active.is_(True))
            .order_by(IssueMember.ref_id)
        )
    )


@register("reply_sent")
def _reply_sent(uow: UnitOfWork, task: Task) -> CompletionResult:
    return reply_state(uow, task.primary_ref_id, quote_ids=issue_quote_ids(uow, task.issue_id))


@register("quote_left_draft")
def _quote_left_draft(uow: UnitOfWork, task: Task) -> CompletionResult:
    quote = sources.read(uow, "sales.quote", task.primary_ref_id) if task.primary_ref_id else None
    if quote is None:
        return CompletionResult(False, remaining=["cannot_verify:sales.quote"])
    if quote.status != "draft":
        return CompletionResult(True, {"reason": "quote_left_draft", "status": quote.status})
    return CompletionResult(False, remaining=["submit_for_review_or_send"])


@register("quote_expiry_resolved")
def _quote_expiry_resolved(uow: UnitOfWork, task: Task) -> CompletionResult:
    quote = sources.read(uow, "sales.quote", task.primary_ref_id) if task.primary_ref_id else None
    if quote is None:
        return CompletionResult(False, remaining=["cannot_verify:sales.quote"])
    if quote.status in QUOTE_CLOSED_STATUSES or quote.is_closed:
        return CompletionResult(True, {"reason": "quote_closed", "status": quote.status})
    valid_until_end = quote.deadlines.get("valid_until_end")
    if valid_until_end is not None and task.due_at is not None and valid_until_end > task.due_at:
        return CompletionResult(True, {"reason": "validity_extended", "valid_until": quote.facts.get("valid_until")})
    return CompletionResult(False, remaining=["extend_validity_or_record_outcome"])


@register("enquiry_answered")
def _enquiry_answered(uow: UnitOfWork, task: Task) -> CompletionResult:
    enquiry = sources.read(uow, "sales.enquiry", task.primary_ref_id) if task.primary_ref_id else None
    if enquiry is None:
        return CompletionResult(False, remaining=["cannot_verify:sales.enquiry"])
    if enquiry.status in ENQUIRY_DONE_STATUSES or enquiry.is_closed:
        return CompletionResult(True, {"reason": f"enquiry_{enquiry.status}"})
    return CompletionResult(False, remaining=["quote_or_close_enquiry"])


@register("lead_followed_up")
def _lead_followed_up(uow: UnitOfWork, task: Task) -> CompletionResult:
    """Done once the lead moved on: a newer activity changed or cleared the follow-up date, or it was won or lost."""
    lead = sources.read(uow, "parties.party", task.primary_ref_id) if task.primary_ref_id else None
    if lead is None:
        return CompletionResult(False, remaining=["cannot_verify:parties.party"])
    stage = lead.facts.get("lead_stage")
    if stage in ("won", "lost") or lead.is_closed:
        return CompletionResult(True, {"reason": f"lead_{stage or 'closed'}"})
    if lead.facts.get("next_follow_up_on") != (task.facts or {}).get("due_on"):
        return CompletionResult(True, {"reason": "activity_logged"})
    return CompletionResult(False, remaining=["log_activity"])


@register("approval_decided")
def _approval_decided(uow: UnitOfWork, task: Task) -> CompletionResult:
    # approvals are decided only through the approvals engine; never marked handled
    return CompletionResult(False, remaining=["decide_through_approvals"])


@register("assertion")
def _assertion(uow: UnitOfWork, task: Task) -> CompletionResult:
    return CompletionResult(True, {"reason": "confirmed", "confirmed_by": str(uow.actor.user_id)})


def _user_fact(uow: UnitOfWork, source_type: str, task: Task, predicate: Callable[[Any], bool], remaining: str) -> CompletionResult:
    user_id = task.assignee_user_id or task.owner_user_id
    facts = sources.read(uow, source_type, user_id) if user_id else None
    if facts is None:
        return CompletionResult(False, remaining=[f"cannot_verify:{source_type}"])
    if predicate(facts.facts):
        return CompletionResult(True, {"reason": remaining + "_done", "source": source_type})
    return CompletionResult(False, remaining=[remaining])


@register("pref_briefing_saved")
def _pref_saved(uow: UnitOfWork, task: Task) -> CompletionResult:
    return _user_fact(uow, "identity.user_preference", task, lambda f: bool(f.get("briefing_saved")), "save_briefing_preferences")


@register("recent_record_exists")
def _recent_record(uow: UnitOfWork, task: Task) -> CompletionResult:
    return _user_fact(uow, "ui.recent_record", task, lambda f: int(f.get("count", 0)) > 0, "open_a_product_record")


@register("recent_search_exists")
def _recent_search(uow: UnitOfWork, task: Task) -> CompletionResult:
    return _user_fact(uow, "search.recent", task, lambda f: int(f.get("count", 0)) > 0, "use_global_search")


@register("queue_empty")
def _queue_empty(uow: UnitOfWork, task: Task) -> CompletionResult:
    from app.modules.tasks.issues import queued_count

    remaining = queued_count(uow, str((task.facts or {}).get("queue")))
    if remaining == 0:
        return CompletionResult(True, {"reason": "queue_empty"})
    return CompletionResult(False, remaining=[f"assign_{remaining}_queued_items"])


@register("member_work_reassigned")
def _member_work_reassigned(uow: UnitOfWork, task: Task) -> CompletionResult:
    """Offboarding: done when no open obligation is still owned or done by the departed member."""
    from sqlalchemy import func, or_, select

    from app.modules.tasks.models import OPEN_STATES
    from app.modules.tasks.models import Task as TaskModel

    member = (task.facts or {}).get("member_user_id")
    if not member:
        return CompletionResult(False, remaining=["cannot_verify:member"])
    member_id = as_uuid(member)
    left = int(
        uow.session.scalar(
            select(func.count()).select_from(TaskModel).where(
                TaskModel.company_id == task.company_id, TaskModel.state.in_(OPEN_STATES), TaskModel.id != task.id,
                or_(TaskModel.owner_user_id == member_id, TaskModel.assignee_user_id == member_id),
            )
        )
        or 0
    )
    if left == 0:
        return CompletionResult(True, {"reason": "work_reassigned"})
    return CompletionResult(False, remaining=[f"reassign_{left}_open_tasks"])


@register("briefing_recovered")
def _briefing_recovered(uow: UnitOfWork, task: Task) -> CompletionResult:
    """Repeated generation failures: done once the member's briefing generates again."""
    from app.modules.briefings import service as briefings  # briefings builds on tasks: imported lazily

    if task.primary_ref_id is None:
        return CompletionResult(False, remaining=["cannot_verify:briefings.briefing"])
    info = briefings.failure_info(uow, task.primary_ref_id)
    if info is None:
        return CompletionResult(False, remaining=["cannot_verify:briefings.briefing"])
    if info.failures == 0:
        return CompletionResult(True, {"reason": "briefing_generated"})
    return CompletionResult(False, remaining=["briefing_still_failing"])
