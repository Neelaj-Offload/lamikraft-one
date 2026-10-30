"""Deterministic overview sentences (fixtures.md §9, keys.EXPECTED), greetings and due labels."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.modules.briefings.engine.labels import due_label
from app.modules.briefings.engine.overview import compose, greeting, greeting_period, number_word
from app.seed.world import keys
from app.seed.world.keys import CLOCK_D0, EXPECTED

UTC = ZoneInfo("UTC")
D0 = date(2026, 10, 12)


def _facts(**values: int) -> dict[str, int]:
    base = dict.fromkeys(
        ("decisions_pending", "customer_replies", "quotes_expiring_today", "tasks_due_today", "overdue", "onboarding_steps",
         "assigned_tasks"), 0)
    base.update(values)
    return base


def test_persona_sentences_match_fixtures() -> None:
    assert compose(_facts(customer_replies=2, quotes_expiring_today=1), first_name="Meera", new_member=False)[1] == EXPECTED.MEERA_S1_SENTENCE
    assert compose(_facts(decisions_pending=3), first_name="Sahil", new_member=False)[1] == EXPECTED.SAHIL_S1_SENTENCE
    assert compose(_facts(decisions_pending=3, overdue=1), first_name="Sahil", new_member=False)[1] == EXPECTED.SAHIL_A08_SENTENCE
    assert compose(_facts(decisions_pending=1), first_name="Sahil", new_member=False)[1] == EXPECTED.SAHIL_A09_SENTENCE
    assert compose(_facts(quotes_expiring_today=1), first_name="Neha", new_member=False)[1] == EXPECTED.NEHA_S1_SENTENCE
    assert compose(_facts(onboarding_steps=3, assigned_tasks=1), first_name="Arjun", new_member=True)[1] == EXPECTED.ARJUN_S1_SENTENCE
    assert compose(_facts(tasks_due_today=1), first_name="Kabir", new_member=False)[1] == EXPECTED.KABIR_S1_SENTENCE
    assert compose(_facts(tasks_due_today=1), first_name="Ravi", new_member=False)[1] == EXPECTED.RAVI_S1_SENTENCE
    assert compose(_facts(), first_name="Ananya", new_member=False)[1] == EXPECTED.ANANYA_S1_SENTENCE


def test_grammar_for_singular_plural_and_three_clauses() -> None:
    assert compose(_facts(customer_replies=1), first_name="M", new_member=False)[1] == "One customer reply needs attention."
    assert compose(_facts(customer_replies=2, quotes_expiring_today=2, tasks_due_today=3), first_name="M", new_member=False)[1] == (
        "Two customer replies need attention, two quotes expire today, and three tasks are due today."
    )
    assert compose(_facts(onboarding_steps=1), first_name="Arjun", new_member=True)[1] == "Welcome, Arjun. You have one onboarding step."
    assert number_word(13) == "13"


def test_greeting_by_local_time() -> None:
    assert greeting(CLOCK_D0, "Asia/Kolkata", "Meera") == EXPECTED.MEERA_S1_GREETING
    assert greeting(CLOCK_D0, "Asia/Kolkata", "Sahil") == EXPECTED.SAHIL_S1_GREETING
    assert [greeting_period(time(h, 0)) for h in (3, 4, 11, 12, 16, 17, 23)] == [
        "evening", "morning", "morning", "afternoon", "afternoon", "evening", "evening"]


def test_due_labels_in_the_viewers_zone() -> None:
    reply_due = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)
    assert due_label(reply_due, zone="Asia/Kolkata", work_date=D0) == "Today 18:30"
    assert due_label(reply_due, zone="Europe/Berlin", work_date=D0) == keys.EXPECTED.BERLIN_DUE_LABEL  # A-05 Berlin variant
    expiry = datetime(2026, 10, 12, 18, 30, tzinfo=UTC)  # end of 2026-10-12 in IST
    assert due_label(expiry, zone="Asia/Kolkata", work_date=D0, kind="quote_expiry") == "Expires today"
    assert due_label(datetime(2026, 10, 13, 4, 30, tzinfo=UTC), zone="Asia/Kolkata", work_date=D0) == "Tomorrow 10:00"
    assert due_label(datetime(2026, 10, 14, 13, 0, tzinfo=UTC), zone="Asia/Kolkata", work_date=D0) == "Wed 18:30"
    assert due_label(datetime(2026, 10, 12, 8, 30, tzinfo=UTC), zone="Asia/Kolkata", work_date=D0, overdue=True) == "Overdue since 14:00"
    assert due_label(None, zone="Asia/Kolkata", work_date=D0) is None
