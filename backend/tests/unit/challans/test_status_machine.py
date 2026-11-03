"""LM-83, FG-DC-12, UI-79: the challan state machine is one table; anything outside it is invalid."""

from __future__ import annotations

from app.modules.challans.schemas import ChallanStatus, TransitionAction
from app.modules.challans.state import TERMINAL, TRANSITIONS, lookup, transitions_from

S = ChallanStatus


def test_valid_and_invalid_transitions_table() -> None:
    """draft -> issued | cancelled; issued -> closed | cancelled; closed and cancelled are terminal (BUG-14)."""
    valid = {
        (S.DRAFT.value, "issue"): (S.ISSUED.value, "issue"),
        (S.DRAFT.value, "cancel"): (S.CANCELLED.value, "transition"),
        (S.ISSUED.value, "close"): (S.CLOSED.value, "transition"),
        (S.ISSUED.value, "cancel"): (S.CANCELLED.value, "reverse"),
    }
    assert set(TRANSITIONS) == set(valid)
    for (from_status, action), (to_status, permission) in valid.items():
        t = lookup(from_status, action)
        assert t is not None and t.to_status == to_status and t.permission_action == permission
    # every other (status, action) pair is invalid: the service answers 409 invalid_transition with the allowed list
    for status in S:
        for action in [*[a.value for a in TransitionAction], "reopen", "archive", "draft", "issued", "closed"]:
            if (status.value, action) not in valid:
                assert lookup(status.value, action) is None, (status, action)
    assert TERMINAL == {S.CLOSED.value, S.CANCELLED.value}
    assert transitions_from(S.CLOSED.value) == [] and transitions_from(S.CANCELLED.value) == []
    assert {t.action for t in transitions_from(S.DRAFT.value)} == {"issue", "cancel"}
    assert {t.action for t in transitions_from(S.ISSUED.value)} == {"close", "cancel"}


def test_reasons_guards_events_and_idempotency_requirements() -> None:
    issue = lookup(S.DRAFT.value, "issue")
    cancel_draft = lookup(S.DRAFT.value, "cancel")
    close = lookup(S.ISSUED.value, "close")
    cancel_issued = lookup(S.ISSUED.value, "cancel")
    assert issue and issue.guard == "issue_ready" and issue.idempotency_required and issue.event == "challans.challan.issued"
    assert cancel_draft and cancel_draft.requires_reason and cancel_draft.event == "challans.challan.cancelled"
    assert close and not close.requires_reason and close.event == "challans.challan.closed"
    assert cancel_issued and cancel_issued.requires_reason and cancel_issued.idempotency_required
    assert cancel_issued.guard == "no_return_links" and cancel_issued.permission_action == "reverse"
