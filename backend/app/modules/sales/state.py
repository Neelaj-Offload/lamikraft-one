"""The quote state machine as one table (LM-51, BUG-01).

``(from_status, action) -> Transition``. Anything not in the table (including the Slice-2 actions ``archive``,
``revise``, ``extend_validity`` and ``correct``) is a 409 ``invalid_transition`` carrying ``allowed_transitions``,
never a 400 with a bogus message. Guards are evaluated by the service with the loaded quote.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.sales.schemas import QuoteStatus, TransitionAction

D = QuoteStatus.DRAFT.value
R = QuoteStatus.INTERNAL_REVIEW.value
S = QuoteStatus.SENT.value


@dataclass(frozen=True)
class Transition:
    action: str
    from_status: str
    to_status: str
    #: the ``sales.quote.<verb>`` action the actor needs in scope over the quote
    permission_action: str
    requires_reason: bool = False
    #: named guard evaluated by the service (``lines_present``, ``issue_allowed``, ``proposal_pending``)
    guard: str | None = None
    #: the specific event emitted alongside ``sales.quote.status_changed``
    event: str | None = None
    #: the command must carry an ``Idempotency-Key`` through the API (api-conventions §6)
    idempotency_required: bool = False


TRANSITIONS: dict[tuple[str, str], Transition] = {
    (t.from_status, t.action): t
    for t in (
        Transition(TransitionAction.SUBMIT_REVIEW, D, R, "transition", guard="lines_present", event="sales.quote.review_requested"),
        Transition(TransitionAction.WITHDRAW_REVIEW, R, D, "transition", guard="proposal_pending", event="sales.quote.review_withdrawn"),
        Transition(TransitionAction.MARK_SENT, D, S, "issue", guard="issue_allowed", event="sales.quote.issued", idempotency_required=True),
        Transition(TransitionAction.MARK_SENT, R, S, "issue", guard="issue_allowed", event="sales.quote.issued", idempotency_required=True),
        Transition(TransitionAction.MARK_WON, S, QuoteStatus.WON.value, "transition", event="sales.quote.won", idempotency_required=True),
        Transition(TransitionAction.MARK_LOST, S, QuoteStatus.LOST.value, "transition", requires_reason=True, event="sales.quote.lost", idempotency_required=True),
        Transition(TransitionAction.CANCEL, D, QuoteStatus.CANCELLED.value, "transition", requires_reason=True, event="sales.quote.cancelled", idempotency_required=True),
        Transition(TransitionAction.CANCEL, R, QuoteStatus.CANCELLED.value, "transition", requires_reason=True, event="sales.quote.cancelled", idempotency_required=True),
        Transition(TransitionAction.CANCEL, S, QuoteStatus.CANCELLED.value, "transition", requires_reason=True, event="sales.quote.cancelled", idempotency_required=True),
    )
}

#: actions whose name is known (Slice 2) but not implemented: they get the same 409 as a wrong state
KNOWN_FUTURE_ACTIONS = frozenset({"archive", "unarchive", "revise", "extend_validity", "correct", "duplicate"})


def transitions_from(status: str) -> list[Transition]:
    return [t for (from_status, _action), t in TRANSITIONS.items() if from_status == status]
