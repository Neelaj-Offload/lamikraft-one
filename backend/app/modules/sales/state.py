"""The quote state machine as one table (LM-51, BUG-01, LP-06.8).

``(from_status, action) -> Transition``. Anything not in the table is a 409 ``invalid_transition`` carrying
``allowed_transitions``, never a 400 with a bogus message. Guards are evaluated by the service with the loaded quote.

"Editable" means ``draft`` (never issued) or ``revised`` (a working copy of an issued quote). Actions whose target
depends on the quote are marked: ``editable`` (draft when never issued, else revised), ``archived_from`` (the status
the quote was archived from) and ``correction`` (a cancelled quote returns to draft when never issued, else sent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.sales.schemas import QuoteStatus, TransitionAction

D = QuoteStatus.DRAFT.value
R = QuoteStatus.INTERNAL_REVIEW.value
S = QuoteStatus.SENT.value
V = QuoteStatus.REVISED.value
W = QuoteStatus.WON.value
L = QuoteStatus.LOST.value
C = QuoteStatus.CANCELLED.value
A = QuoteStatus.ARCHIVED.value
A_ = TransitionAction


@dataclass(frozen=True)
class Transition:
    action: str
    from_status: str
    to_status: str
    #: the ``sales.quote.<verb>`` action the actor needs in scope over the quote
    permission_action: str
    requires_reason: bool = False
    #: named guard evaluated by the service (``lines_present``, ``issue_allowed``, ``valid_until``)
    guard: str | None = None
    #: the specific event emitted alongside ``sales.quote.status_changed``
    event: str | None = None
    #: the command must carry an ``Idempotency-Key`` through the API (api-conventions §6)
    idempotency_required: bool = False
    #: dynamic target: ``editable`` | ``archived_from`` | ``correction`` (``to_status`` is then the usual target)
    target: str | None = None


def _t(action: str, frm: str, to: str, perm: str, **kw: Any) -> Transition:
    return Transition(action, frm, to, perm, **kw)


TRANSITIONS: dict[tuple[str, str], Transition] = {
    (t.from_status, t.action): t
    for t in (
        _t(A_.SUBMIT_REVIEW, D, R, "transition", guard="lines_present", event="sales.quote.review_requested"),
        _t(A_.SUBMIT_REVIEW, V, R, "transition", guard="lines_present", event="sales.quote.review_requested"),
        _t(A_.WITHDRAW_REVIEW, R, D, "transition", event="sales.quote.review_withdrawn", target="editable"),
        _t(A_.MARK_SENT, D, S, "issue", guard="issue_allowed", event="sales.quote.issued", idempotency_required=True),
        _t(A_.MARK_SENT, R, S, "issue", guard="issue_allowed", event="sales.quote.issued", idempotency_required=True),
        _t(A_.MARK_SENT, V, S, "issue", guard="issue_allowed", event="sales.quote.issued", idempotency_required=True),
        _t(A_.REVISE, S, V, "transition", event="sales.quote.revised"),
        _t(A_.DISCARD_REVISION, V, S, "transition", event="sales.quote.restored"),
        _t(A_.EXTEND_VALIDITY, S, S, "transition", guard="valid_until", event="sales.quote.validity_extended",
           idempotency_required=True),
        _t(A_.MARK_WON, S, W, "transition", event="sales.quote.won", idempotency_required=True),
        _t(A_.MARK_LOST, S, L, "transition", requires_reason=True, event="sales.quote.lost", idempotency_required=True),
        _t(A_.MARK_LOST, V, L, "transition", requires_reason=True, event="sales.quote.lost", idempotency_required=True),
        *(
            _t(A_.CANCEL, frm, C, "transition", requires_reason=True, event="sales.quote.cancelled", idempotency_required=True)
            for frm in (D, R, S, V)
        ),
        *(_t(A_.ARCHIVE, frm, A, "archive", event="sales.quote.archived") for frm in (W, L, C)),
        _t(A_.UNARCHIVE, A, W, "archive", event="sales.quote.unarchived", target="archived_from"),
        # lawful correction paths (management, reason required): won/lost back to sent, cancelled back to draft/sent;
        # won -> sent is blocked while an active sales order exists (Slice 4, orders module)
        _t(A_.CORRECT_STATUS, W, S, "correct", requires_reason=True, event="sales.quote.status_corrected"),
        _t(A_.CORRECT_STATUS, L, S, "correct", requires_reason=True, event="sales.quote.status_corrected"),
        _t(A_.CORRECT_STATUS, C, S, "correct", requires_reason=True, event="sales.quote.status_corrected", target="correction"),
    )
}

#: actions requested through POST /transitions (``review_rejected`` and the history-only actions are not)
REQUESTABLE = frozenset(t.action for t in TRANSITIONS.values())


def transitions_from(status: str) -> list[Transition]:
    return [t for (from_status, _action), t in TRANSITIONS.items() if from_status == status]


def target_status(t: Transition, quote: Any) -> str:
    """The status the quote moves to (dynamic targets resolved against the quote)."""
    issued = int(getattr(quote, "revision_no", 0) or 0) >= 1
    if t.target == "editable":
        return V if issued else D
    if t.target == "archived_from":
        return str(getattr(quote, "archived_from_status", None) or W)
    if t.target == "correction":
        return S if issued else D
    return t.to_status
