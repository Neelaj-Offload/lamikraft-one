"""The overview: greeting by local time and one factual sentence composed from counted, visible items.

No model is involved (Slice 1). Every numeral in the sentence is a count from ``facts``, which are
computed only over the items the member can see (no aggregate leakage). Reminders are private and never
counted.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.modules.briefings.engine.model import Assembly, Context
from app.modules.briefings.engine.priority import due_today, is_overdue

TEMPLATE_VERSION = "en.s1.1"
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
          "eleven", "twelve")


def number_word(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def greeting_period(local: time) -> str:
    if time(4, 0) <= local < time(12, 0):
        return "morning"
    if time(12, 0) <= local < time(17, 0):
        return "afternoon"
    return "evening"


def greeting(now: datetime, zone: str, first_name: str) -> str:
    period = greeting_period(now.astimezone(ZoneInfo(zone)).time())
    name = f", {first_name}" if first_name else ""
    return f"Good {period}{name}."


def count_facts(assembly: Assembly, ctx: Context) -> dict[str, int]:
    """Counts over visible obligation items only (sections already permission-filtered)."""
    facts = {
        "decisions_pending": 0,
        "customer_replies": 0,
        "quotes_expiring_today": 0,
        "tasks_due_today": 0,
        "overdue": 0,
        "onboarding_steps": 0,
        "assigned_tasks": 0,
    }
    for item in assembly.items:
        c = item.candidate
        if c.category != "obligation":
            continue
        overdue = is_overdue(c, ctx)
        today = due_today(c, ctx)
        if c.is_decision:
            facts["decisions_pending"] += 1
            continue
        if overdue:
            facts["overdue"] += 1
        if c.overview_class == "customer_reply":
            facts["customer_replies"] += 1
        elif c.overview_class == "quote_expiry":
            if today and not overdue:
                facts["quotes_expiring_today"] += 1
        elif c.overview_class == "onboarding_step":
            facts["onboarding_steps"] += 1
        elif today and not overdue:
            facts["tasks_due_today"] += 1
        if c.overview_class == "task" and c.responsibility == "ASSIGNED_TO_YOU":
            facts["assigned_tasks"] += 1
    return facts


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


def _join(clauses: list[str]) -> str:
    if len(clauses) == 1:
        body = clauses[0]
    elif len(clauses) == 2:
        body = f"{clauses[0]} and {clauses[1]}"
    else:
        body = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
    return body[0].upper() + body[1:] + "."


def _cap(text: str) -> str:
    return text[0].upper() + text[1:]


def compose(facts: dict[str, int], *, first_name: str, new_member: bool) -> tuple[str, str]:
    """(template_code, sentence)."""
    steps = facts.get("onboarding_steps", 0)
    if new_member and steps:
        assigned = facts.get("assigned_tasks", 0)
        tail = f" and {number_word(assigned)} assigned {_plural(assigned, 'task', 'tasks')}" if assigned else ""
        return "welcome", (
            f"Welcome, {first_name}. You have {number_word(steps)} onboarding {_plural(steps, 'step', 'steps')}{tail}."
        )
    decisions = facts.get("decisions_pending", 0)
    overdue = facts.get("overdue", 0)
    if decisions:
        first = f"{_cap(number_word(decisions))} {_plural(decisions, 'decision needs', 'decisions need')} you."
        if overdue:
            second = f"{_cap(number_word(overdue))} {_plural(overdue, 'item is', 'items are')} overdue."
        else:
            second = "The rest is moving."
        return "decisions", f"{first} {second}"
    clauses: list[str] = []
    replies = facts.get("customer_replies", 0)
    if replies:
        clauses.append(f"{number_word(replies)} customer {_plural(replies, 'reply needs', 'replies need')} attention")
    expiring = facts.get("quotes_expiring_today", 0)
    if expiring:
        clauses.append(f"{number_word(expiring)} {_plural(expiring, 'quote expires', 'quotes expire')} today")
    due = facts.get("tasks_due_today", 0) + facts.get("onboarding_steps", 0)
    if due:
        clauses.append(f"{number_word(due)} {_plural(due, 'task is', 'tasks are')} due today")
    if overdue:
        clauses.append(f"{number_word(overdue)} {_plural(overdue, 'item is', 'items are')} overdue")
    if not clauses:
        return "empty", "Nothing needs you right now."
    return "clauses", _join(clauses)


def numerals_in(sentence: str) -> list[int]:
    """Every number the sentence states (as words or digits), for the facts-consistency property."""
    out: list[int] = []
    for raw in sentence.replace(",", " ").replace(".", " ").split():
        word = raw.lower()
        if word in _WORDS:
            out.append(_WORDS.index(word))
        elif word.isdigit():
            out.append(int(word))
    return out
