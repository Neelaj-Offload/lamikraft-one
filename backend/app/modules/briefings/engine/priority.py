"""Rule-based priority with reason codes (pure, versioned; fixtures.md §9 weights).

score = one due component + impact components + the single highest responsibility component
(+ BLOCKED_BY −10). Bands: P1 ≥ 70, P2 40–69, P3 15–39, P4 < 15. Due components are relative to the
briefing's work window; OVERDUE comes from the sweep's recorded fact (or a due date before the window),
so the passage of time alone never changes a stored priority.
"""

from __future__ import annotations

from app.modules.briefings.engine.model import Candidate, Context

WEIGHTS: dict[str, int] = {
    "OVERDUE": 50,
    "DUE_TODAY": 35,
    "SOFT_OVERDUE": 20,
    "DUE_NEXT_WORKDAY": 15,
    "DUE_WITHIN_3_WORKDAYS": 5,
    "CUSTOMER_COMMITMENT_AT_RISK": 25,
    "YOUR_DECISION": 20,
    "ASSIGNED_TO_YOU": 15,
    "DELEGATED_TO_YOU": 10,
    "YOU_OWN": 5,
    "FYI": 0,
    "BLOCKED_BY": -10,
}
RESPONSIBILITY_ORDER = ("YOUR_DECISION", "ASSIGNED_TO_YOU", "DELEGATED_TO_YOU", "YOU_OWN", "FYI")
BAND_THRESHOLDS = (("P1", 70), ("P2", 40), ("P3", 15))
BAND_RANK = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}

REASON_TEXT: dict[str, str] = {
    "OVERDUE": "Past its deadline",
    "SOFT_OVERDUE": "Past its target time",
    "DUE_TODAY": "Due today",
    "DUE_NEXT_WORKDAY": "Due next working day",
    "DUE_WITHIN_3_WORKDAYS": "Due within three working days",
    "CUSTOMER_COMMITMENT_AT_RISK": "A customer is waiting",
    "YOUR_DECISION": "Your decision",
    "ASSIGNED_TO_YOU": "Assigned to you",
    "DELEGATED_TO_YOU": "Delegated to you",
    "YOU_OWN": "You own it",
    "FYI": "For your information",
    "BLOCKED_BY": "Waiting on something else",
}


def band_for(score: int) -> str:
    for band, threshold in BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return "P4"


def is_overdue(c: Candidate, ctx: Context) -> bool:
    if c.due_at is None:
        return False
    return c.overdue_fact or c.due_at < ctx.window_start


def due_today(c: Candidate, ctx: Context) -> bool:
    return c.due_at is not None and ctx.window_start <= c.due_at < ctx.window_end


def due_component(c: Candidate, ctx: Context) -> str | None:
    if c.due_at is None:
        return None
    if is_overdue(c, ctx):
        return "OVERDUE" if c.due_kind == "hard" else "SOFT_OVERDUE"
    if c.due_at < ctx.window_end:
        return "DUE_TODAY"
    if c.due_at < ctx.next_window_end:
        return "DUE_NEXT_WORKDAY"
    if c.due_at < ctx.horizon_end:
        return "DUE_WITHIN_3_WORKDAYS"
    return None


def priority(c: Candidate, ctx: Context) -> tuple[int, str, tuple[str, ...]]:
    """(score, band, reason codes) — the reason codes explain every point of the score."""
    reasons: list[str] = []
    due = due_component(c, ctx) if c.category in ("obligation", "reminder") else None
    if due:
        reasons.append(due)
    if c.category == "obligation":
        reasons.extend(i for i in c.impact if i in WEIGHTS)
    reasons.append(c.responsibility if c.responsibility in WEIGHTS else "FYI")
    if c.blocked:
        reasons.append("BLOCKED_BY")
    score = sum(WEIGHTS[r] for r in reasons)
    return score, band_for(score), tuple(reasons)
