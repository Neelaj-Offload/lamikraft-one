"""SCN-A1: Meera opens Today in her local morning: only authorised items, real updates, source-linked suggestions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.seed.world import keys
from tests.integration.briefings.test_expected_briefings import key_id, today
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db


def test_meera_sentence_and_sections(world: FakeWorld) -> None:
    """A-03/A-06: computed overview, five items in rank order, empty sections omitted."""
    view = today(world, keys.USERS.MEERA)
    assert view.status == "ready" and not view.fallback
    assert view.overview is not None
    assert view.overview.greeting == keys.EXPECTED.MEERA_S1_GREETING
    assert view.overview.sentence == keys.EXPECTED.MEERA_S1_SENTENCE
    assert view.overview.facts == {"customer_replies": 2, "quotes_expiring_today": 1}
    # fixtures.md §9.1 rows 1-4 (row 5, the reminder, is checked below)
    expected_order = [key_id(world, template.format_map(world.refs)) for template in keys.EXPECTED.MEERA_S1_ITEM_ORDER[:4]]
    assert [i.issue_id for i in view.items][:4] == expected_order
    assert view.items[4].is_reminder and view.items[4].due_label == "Tomorrow 10:00"
    sections = {s.code: s.total for s in view.sections}
    assert sections == {"needs_you_now": 2, "plan_for_today": 1, "changes_since_last_visit": 1, "coming_next": 1}
    assert "handled_for_you" not in sections and "recommendations" not in sections
    assert len(view.initial_view) == 5 and len(view.items) == 5
    reply, expiry, nordhaus = view.items[:3]
    assert (reply.score, reply.band, expiry.score, expiry.band, nordhaus.score, nordhaus.band) == (75, "P1", 75, "P1", 65, "P2")
    assert reply.due_label == "Today 18:30" and reply.due_at == datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    assert expiry.due_label == "Expires today"
    assert nordhaus.blocked and keys.QUOTES.NORDHAUS_DRAFT in nordhaus.title
    assert nordhaus.blocked_by[0]["label"].startswith("Review " + keys.QUOTES.NORDHAUS_DRAFT)
    assert nordhaus.recommendation is not None and nordhaus.recommendation.action_code == "FOLLOW_UP_REVIEW"
    maison = view.items[3]
    assert maison.title == f"{keys.PARTY_NAMES['MAISON']} shipping address updated by Priya"
    assert [m.amount for m in expiry.money] and expiry.money[0].currency == "EUR"
