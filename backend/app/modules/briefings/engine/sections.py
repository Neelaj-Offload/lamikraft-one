"""Section placement and the total order (pure).

Each issue lands in exactly one section (first match wins); empty sections are omitted. Display order:
Needs you now, Plan for today, Recommendations, Changes since your last visit, Handled for you,
Coming next (fixtures.md §10 places Recommendations before Changes). Within a section:
band → score desc → due asc (nulls last) → fact_at asc → issue id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.briefings.engine.model import Assembly, Candidate, Context, Item
from app.modules.briefings.engine.priority import BAND_RANK, due_today, is_overdue, priority

SECTION_ORDER = (
    "needs_you_now",
    "plan_for_today",
    "recommendations",
    "changes_since_last_visit",
    "handled_for_you",
    "coming_next",
)
SECTION_TITLES = {
    "needs_you_now": "Needs you now",
    "plan_for_today": "Plan for today",
    "recommendations": "Recommendations",
    "changes_since_last_visit": "Changes since your last visit",
    "handled_for_you": "Handled for you",
    "coming_next": "Coming next",
}
_FAR = datetime.max.replace(tzinfo=UTC)


def place(c: Candidate, band: str, ctx: Context) -> str | None:
    """First matching section, or None when the item belongs to no section of this day."""
    if c.category == "change":
        return "changes_since_last_visit"
    if c.category == "handled":
        return "handled_for_you"
    if c.category == "recommendation":
        return "recommendations"
    if c.due_at is not None and c.due_at >= ctx.horizon_end:
        return "changes_since_last_visit" if c.changed_since_last_visit else None
    today = due_today(c, ctx)
    overdue = is_overdue(c, ctx)
    if c.category == "reminder":
        if ctx.day_type == "working" and (today or overdue):
            return "plan_for_today"
        if c.due_at is not None and c.due_at >= ctx.window_end:
            return "coming_next"
        return "coming_next" if ctx.day_type != "working" else "plan_for_today"
    # obligations
    if ctx.day_type != "working":
        hard_before_next = c.due_kind == "hard" and c.due_at is not None and c.due_at < ctx.next_window_start
        if overdue or hard_before_next:
            return "needs_you_now"
        if c.due_at is not None and c.due_at >= ctx.window_end:
            return "coming_next"
        return "changes_since_last_visit" if c.changed_since_last_visit else None
    actionable_now = c.actionable and not c.blocked
    if actionable_now and (band == "P1" or overdue or (c.is_decision and today)):
        return "needs_you_now"
    if (c.actionable and today) or (c.blocked and (c.unblock_expected_today or overdue)) or (
        band == "P2" and c.due_at is None
    ):
        return "plan_for_today"
    if overdue and c.actionable:
        return "needs_you_now"
    if c.due_at is not None and c.due_at >= ctx.window_end:
        return "coming_next"
    if c.changed_since_last_visit:
        return "changes_since_last_visit"
    if c.actionable and c.due_at is None:
        return "plan_for_today"  # an open obligation without a deadline is never absent from Today
    return None


def order_key(item: Item) -> tuple[int, int, int, datetime, datetime, str]:
    c = item.candidate
    return (
        SECTION_ORDER.index(item.section),
        BAND_RANK[item.band],
        -item.score,
        c.due_at or _FAR,
        c.fact_at,
        str(c.issue_id),
    )


def assemble(candidates: list[Candidate], ctx: Context) -> Assembly:
    """Priority, placement, global rank and the initial view. One item per issue (first wins)."""
    seen: set[str] = set()
    placed: list[Item] = []
    for c in candidates:
        key = str(c.issue_id)
        if key in seen:
            continue
        score, band, reasons = priority(c, ctx)
        section = place(c, band, ctx)
        if section is None:
            continue
        seen.add(key)
        placed.append(Item(candidate=c, section=section, band=band, score=score, reason_codes=reasons))
    placed.sort(key=order_key)
    ranked = tuple(
        Item(candidate=i.candidate, section=i.section, band=i.band, score=i.score, reason_codes=i.reason_codes, ordinal=n)
        for n, i in enumerate(placed, start=1)
    )
    sections = tuple(
        (code, tuple(i.issue_id for i in ranked if i.section == code))
        for code in SECTION_ORDER
        if any(i.section == code for i in ranked)
    )
    initial = tuple(i.issue_id for i in ranked[: ctx.initial_cap])
    return Assembly(items=ranked, sections=sections, initial_issue_ids=initial)
