"""The challan state machine as one table (LM-83, BUG-14, FG-DC-12).

``(from_status, action) -> Transition``. Anything not in the table is a 409 ``invalid_transition`` carrying
``allowed_transitions`` (the legacy ``PUT /challans/{id}`` accepted any status string). ``closed`` and ``cancelled``
are terminal; an issued challan is immutable except for its internal note (collab) and these transitions.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.challans.schemas import ChallanStatus, TransitionAction

D = ChallanStatus.DRAFT.value
I = ChallanStatus.ISSUED.value  # noqa: E741 - the status letter, mirrors the sales table
C = ChallanStatus.CLOSED.value
X = ChallanStatus.CANCELLED.value


@dataclass(frozen=True)
class Transition:
    action: str
    from_status: str
    to_status: str
    #: the ``challans.challan.<verb>`` the actor needs in scope over the challan
    permission_action: str
    requires_reason: bool = False
    #: named guard evaluated by the service (``issue_ready``, ``no_return_links``)
    guard: str | None = None
    #: the specific catalogued event emitted after the change
    event: str | None = None
    #: the command must carry an ``Idempotency-Key`` through the API (api-conventions §6)
    idempotency_required: bool = False


TRANSITIONS: dict[tuple[str, str], Transition] = {
    (t.from_status, t.action): t
    for t in (
        Transition(
            TransitionAction.ISSUE,
            D,
            I,
            "issue",
            guard="issue_ready",
            event="challans.challan.issued",
            idempotency_required=True,
        ),
        Transition(
            TransitionAction.CANCEL,
            D,
            X,
            "transition",
            requires_reason=True,
            event="challans.challan.cancelled",
        ),
        Transition(
            TransitionAction.CLOSE, I, C, "transition", guard="close_ready", event="challans.challan.closed"
        ),
        # cancelling an issued document needs the restricted reverse right (Slice 4: a reversal posting)
        Transition(
            TransitionAction.CANCEL,
            I,
            X,
            "reverse",
            requires_reason=True,
            guard="no_return_links",
            event="challans.challan.cancelled",
            idempotency_required=True,
        ),
    )
}

TERMINAL = frozenset({C, X})


def transitions_from(status: str) -> list[Transition]:
    return [t for (from_status, _action), t in TRANSITIONS.items() if from_status == status]


def lookup(status: str, action: str) -> Transition | None:
    return TRANSITIONS.get((status, action))
