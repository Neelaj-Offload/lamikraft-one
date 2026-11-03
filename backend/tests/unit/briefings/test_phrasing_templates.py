"""Slice-3 phrasing templates: every briefing text the phrasing service may reword is built from placeholders whose
substitution gives exactly the deterministic text, and the Demo phraser's echo passes the validator (so demo mode
exercises the whole validated path, and a failure is a real failure)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.agents import phrasing as agents_phrasing
from app.modules.agents.phrasing import Fact, PhraseRequest
from app.modules.briefings import phrasing
from app.modules.briefings.engine.overview import compose, compose_template, sentence_case
from app.modules.briefings.engine.recommend import ACTION_TEXT, REASON_TEXT, RULES, render, sentence_template
from app.modules.briefings.models import BriefingItem

IST = ZoneInfo("Asia/Kolkata")
COUNTS = ("decisions_pending", "customer_replies", "quotes_expiring_today", "tasks_due_today", "overdue", "onboarding_steps",
          "assigned_tasks")


def _request(code: str, template: str, slots: Any) -> PhraseRequest:
    return PhraseRequest(template_code=code, template=template,
                         facts=tuple(Fact(key=s.key, text=s.text, kind=s.kind, label=s.label) for s in slots))  # type: ignore[arg-type]


@settings(max_examples=150, derandomize=True, deadline=None)
@given(
    counts=st.fixed_dictionaries({k: st.integers(min_value=0, max_value=15) for k in COUNTS}),
    new_member=st.booleans(),
    name=st.sampled_from(["Meera", "Sahil", ""]),
)
def test_overview_template_substitutes_to_the_deterministic_sentence(counts: dict[str, int], new_member: bool, name: str) -> None:
    code, sentence = compose(counts, first_name=name, new_member=new_member)
    built_code, template, slots = compose_template(counts, first_name=name, new_member=new_member)
    assert built_code == code
    request = _request(f"briefing.overview.{code}", template, slots)
    assert sentence_case(agents_phrasing.render_template(request)) == sentence
    # no count or name is written into the template itself: only placeholders carry facts
    assert not any(ch.isdigit() for ch in agents_phrasing.PLACEHOLDER.sub(" ", template))
    echoed = agents_phrasing.validate(template, request)
    assert echoed.ok, (template, echoed.failures)


def test_recommendation_sentence_matches_render_for_every_rule() -> None:
    facts = {"contact_name": "Anna Weber", "party_name": "Nordhaus", "quote_numbers": ["LK-QT-2026-0041"],
             "quote_number": "LK-QT-2026-0041", "new_member": "Arjun Rao"}
    for rule in RULES.values():
        rendered = render(rule, facts, set())
        template, slots = sentence_template(rule.action_code, rule.reason_code, facts)
        request = PhraseRequest(template_code="r", template=template,
                                facts=tuple(Fact(key=k, text=t, kind=kind) for k, t, kind in slots))  # type: ignore[arg-type]
        assert agents_phrasing.render_template(request) == f"{rendered['label']}. {rendered['reason']}".strip()
        assert agents_phrasing.validate(template, request).ok, template
    assert set(ACTION_TEXT) >= {r.action_code for r in RULES.values()} and set(REASON_TEXT) >= {r.reason_code for r in RULES.values()}


def _row(**overrides: Any) -> BriefingItem:
    base: dict[str, Any] = dict(
        issue_id=uuid.uuid4(), title="Nordhaus export quote LK-QT-2026-0041", kind="approval_decision", family="common.approvals",
        facts={"_money": [{"amount": "5760.00", "currency": "EUR"}]}, reason_codes=["DUE_TODAY"],
        due_at=datetime(2026, 10, 12, 14, 0, tzinfo=IST), source_refs=[{"type": "sales.quote", "label": "LK-QT-2026-0041", "path": "/sales/quotes/x"}],
        recommendation={"action_code": "REVIEW_AND_DECIDE", "label": "Review the request and decide", "reason_code": "AWAITING_YOUR_DECISION"},
        is_reminder=False,
    )
    base.update(overrides)
    return BriefingItem(**base)


def test_narration_body_is_two_sentences_and_keeps_the_facts() -> None:
    row = _row()
    request = phrasing.narration_request(row, zone="Asia/Kolkata", work_date=date(2026, 10, 12))
    text = agents_phrasing.render_template(request)
    assert text == "Nordhaus export quote LK-QT-2026-0041, EUR 5,760.00, today 14:00. Suggested: Review the request and decide."
    assert agents_phrasing.validate(request.template, request).ok
    money = [f for f in request.facts if f.kind == "money"]
    assert money and money[0].currency == "EUR"
    assert phrasing.readback_values(row) == ["Nordhaus export quote LK-QT-2026-0041", "EUR 5,760.00"]
    assert phrasing.family_label(row) == "Decision" and phrasing.ordinal_word(2) == "Second"


def test_model_wording_with_its_own_numbers_or_names_is_rejected() -> None:
    request = phrasing.narration_request(_row(), zone="Asia/Kolkata", work_date=date(2026, 10, 12))
    assert not agents_phrasing.validate("{{a1}} costs 5760 euros. Suggested: {{a4}}.", request).ok  # numeral not from facts
    assert not agents_phrasing.validate("{{a1}} for Maison, {{a2}}. Suggested: {{a4}}.", request).ok  # new proper noun
    assert not agents_phrasing.validate("{{a1}}. Suggested: {{a4}}.", request).ok  # the amount was dropped
    assert agents_phrasing.validate("Please look at {{a1}} ({{a2}}, {{a3}}). Suggested: {{a4}}.", request).ok


def test_sentence_case_restores_capitals_only_at_sentence_starts() -> None:
    assert sentence_case("two decisions need you. the rest is moving.") == "Two decisions need you. The rest is moving."
    assert sentence_case("In short: two items, EUR 5,760.00 total.") == "In short: two items, EUR 5,760.00 total."
