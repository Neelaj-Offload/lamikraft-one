"""Ordering, bands, sections and the overview sentence are deterministic and leak nothing (property tests).

Acceptance: unit/briefings/test_priority_and_sections_properties — deterministic total order, each
issue in exactly one section, initial view <= 5, no empty sections, every numeral in the overview text
present in the overview facts; bands at the fixtures.md §9 thresholds.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.briefings.engine import overview
from app.modules.briefings.engine.model import Candidate
from app.modules.briefings.engine.priority import WEIGHTS, band_for, priority
from app.modules.briefings.engine.sections import SECTION_ORDER, assemble, order_key
from app.modules.briefings.service import build_context
from app.platform.org.workcal import CalendarView

IST = ZoneInfo("Asia/Kolkata")
CAL = CalendarView()
CTX = build_context(CAL, date(2026, 10, 12))
BASE = datetime(2026, 10, 12, 8, 55, tzinfo=IST)
RESPONSIBILITIES = ("YOUR_DECISION", "ASSIGNED_TO_YOU", "YOU_OWN", "FYI")
DUE_OFFSETS = (None, -26, -2, 1, 5, 9, 25, 49, 73, 150)  # hours from D0 08:55
KINDS = ("reply_needed", "quote_expiry", "approval_decision", "manual", "onboarding_step", "review_draft")


@st.composite
def candidates(draw: st.DrawFn) -> list[Candidate]:
    n = draw(st.integers(min_value=0, max_value=14))
    out: list[Candidate] = []
    for i in range(n):
        category = draw(st.sampled_from(("obligation", "obligation", "obligation", "change", "handled", "reminder")))
        kind = draw(st.sampled_from(KINDS)) if category == "obligation" else category
        offset = draw(st.sampled_from(DUE_OFFSETS)) if category in ("obligation", "reminder") else None
        due = BASE + timedelta(hours=offset) if offset is not None else None
        out.append(
            Candidate(
                issue_id=uuid.UUID(int=draw(st.integers(min_value=1, max_value=10**12)) * 100 + i),
                category=category,  # type: ignore[arg-type]
                kind=kind,
                family="test",
                title=f"item {i}",
                fact_at=BASE - timedelta(minutes=draw(st.integers(min_value=0, max_value=5000))),
                issue_fingerprint="f" * 64,
                responsibility=draw(st.sampled_from(RESPONSIBILITIES)) if category == "obligation" else "FYI",  # type: ignore[arg-type]
                due_at=due,
                due_kind=draw(st.sampled_from(("hard", "soft"))) if due else "none",
                overdue_fact=draw(st.booleans()) if due and offset is not None and offset < 0 else False,
                blocked=draw(st.booleans()) if category == "obligation" else False,
                unblock_expected_today=draw(st.booleans()),
                impact=("CUSTOMER_COMMITMENT_AT_RISK",) if kind in ("reply_needed", "quote_expiry") else (),
                actionable=category in ("obligation", "reminder"),
                is_decision=kind == "approval_decision",
                changed_since_last_visit=draw(st.booleans()),
                overview_class={"reply_needed": "customer_reply", "quote_expiry": "quote_expiry", "approval_decision": "decision",
                                "onboarding_step": "onboarding_step"}.get(kind, "task") if category == "obligation" else None,
            )
        )
    return out


@settings(derandomize=True, max_examples=300, deadline=None)
@given(items=candidates(), seed=st.integers(min_value=0, max_value=10_000))
def test_total_order_is_deterministic_and_input_order_independent(items: list[Candidate], seed: int) -> None:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    a = assemble(items, CTX)
    b = assemble(shuffled, CTX)
    assert [(i.issue_id, i.ordinal, i.section) for i in a.items] == [(i.issue_id, i.ordinal, i.section) for i in b.items]
    keys = [order_key(i) for i in a.items]
    assert keys == sorted(keys)


@settings(derandomize=True, max_examples=300, deadline=None)
@given(items=candidates())
def test_each_issue_once_no_empty_sections_initial_at_most_five(items: list[Candidate]) -> None:
    result = assemble(items, CTX)
    ids = [i.issue_id for i in result.items]
    assert len(ids) == len(set(ids))
    assert [i.ordinal for i in result.items] == list(range(1, len(ids) + 1))
    placed = [issue for _, issues in result.sections for issue in issues]
    assert sorted(placed, key=str) == sorted(ids, key=str)
    assert all(issues for _, issues in result.sections)
    codes = [code for code, _ in result.sections]
    assert codes == [c for c in SECTION_ORDER if c in codes]
    assert len(result.initial_issue_ids) == min(5, len(ids))
    assert list(result.initial_issue_ids) == ids[:5]


@settings(derandomize=True, max_examples=300, deadline=None)
@given(items=candidates())
def test_score_is_explained_by_reason_codes_with_one_responsibility(items: list[Candidate]) -> None:
    for c in items:
        score, band, reasons = priority(c, CTX)
        assert score == sum(WEIGHTS[r] for r in reasons)
        assert band == band_for(score)
        assert sum(1 for r in reasons if r in RESPONSIBILITIES or r == "DELEGATED_TO_YOU") == 1
        if c.blocked:
            assert "BLOCKED_BY" in reasons


def test_band_thresholds() -> None:
    assert [band_for(s) for s in (100, 70, 69, 40, 39, 15, 14, 0, -10)] == ["P1", "P1", "P2", "P2", "P3", "P3", "P4", "P4", "P4"]


@settings(derandomize=True, max_examples=300, deadline=None)
@given(items=candidates(), new_member=st.booleans())
def test_every_numeral_in_the_sentence_is_a_fact(items: list[Candidate], new_member: bool) -> None:
    result = assemble(items, CTX)
    facts = overview.count_facts(result, CTX)
    _code, sentence = overview.compose(facts, first_name="Meera", new_member=new_member)
    stated = overview.numerals_in(sentence)
    derived = set(facts.values()) | {facts["tasks_due_today"] + facts["onboarding_steps"]}
    assert all(n in derived and n > 0 for n in stated)
    assert sentence.endswith(".")


@settings(derandomize=True, max_examples=200, deadline=None)
@given(items=candidates(), hidden=st.sets(st.integers(min_value=0, max_value=13)))
def test_counts_come_only_from_visible_items(items: list[Candidate], hidden: set[int]) -> None:
    """A-13 at engine level: dropping items before assembly changes counts exactly by what was dropped."""
    visible = [c for n, c in enumerate(items) if n not in hidden]
    result = assemble(visible, CTX)
    facts = overview.count_facts(result, CTX)
    placed = {i.issue_id for i in result.items}
    decisions = sum(1 for c in visible if c.issue_id in placed and c.category == "obligation" and c.is_decision)
    replies = sum(1 for c in visible if c.issue_id in placed and c.category == "obligation" and not c.is_decision
                  and c.overview_class == "customer_reply")
    assert facts["decisions_pending"] == decisions
    assert facts["customer_replies"] == replies
    hidden_ids = {c.issue_id for n, c in enumerate(items) if n in hidden} - {c.issue_id for c in visible}
    assert not hidden_ids & placed
