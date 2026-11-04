"""The overview: greeting by local time and one factual sentence composed from counted, visible items.

The sentence is deterministic; ``compose_template`` gives the same sentence with ``{{a1}}`` placeholders for the
phrasing service (Slice 3), which may reword it but never its facts. Every numeral in the sentence is a count from ``facts``, which are
computed only over the items the member can see (no aggregate leakage). Reminders are private and never
counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


def _join_plain(clauses: list[str]) -> str:
    if len(clauses) == 1:
        body = clauses[0]
    elif len(clauses) == 2:
        body = f"{clauses[0]} and {clauses[1]}"
    else:
        body = ", ".join(clauses[:-1]) + f", and {clauses[-1]}"
    return body + "."


def _cap(text: str) -> str:
    return text[0].upper() + text[1:]


_SENTENCE_START = re.compile(r"(^\s*|[.!?]\s+)([a-z])")


@dataclass(frozen=True)
class Slot:
    """A fact the overview sentence states (a count word or the member's first name), for phrasing."""

    key: str
    text: str
    kind: str
    label: str


class _Slots:
    """Collects the facts a sentence states; in template mode each fact is written as ``{{key}}``."""

    def __init__(self, template: bool) -> None:
        self.template = template
        self.slots: list[Slot] = []

    def put(self, text: str, kind: str, label: str) -> str:
        if not self.template:
            return text
        key = f"a{len(self.slots) + 1}"
        self.slots.append(Slot(key, text, kind, label))
        return "{{" + key + "}}"

    def count(self, n: int, label: str, *, cap: bool = False) -> str:
        """A count word. In template mode the fact is always lower case (the model may move it inside a
        sentence); ``sentence_case`` restores the capital wherever a sentence starts."""
        word = number_word(n)
        return self.put(word if self.template else (_cap(word) if cap else word), "count", label)


def _compose(facts: dict[str, int], first_name: str, new_member: bool, out: _Slots) -> tuple[str, str]:
    steps = facts.get("onboarding_steps", 0)
    if new_member and steps:
        assigned = facts.get("assigned_tasks", 0)
        tail = (
            f" and {out.count(assigned, 'assigned tasks')} assigned {_plural(assigned, 'task', 'tasks')}" if assigned else ""
        )
        name = out.put(first_name, "name", "first name") if first_name else ""
        return "welcome", (
            f"Welcome, {name}. You have {out.count(steps, 'onboarding steps')} onboarding "
            f"{_plural(steps, 'step', 'steps')}{tail}."
        )
    decisions = facts.get("decisions_pending", 0)
    overdue = facts.get("overdue", 0)
    if decisions:
        first = f"{out.count(decisions, 'decisions pending', cap=True)} {_plural(decisions, 'decision needs', 'decisions need')} you."
        if overdue:
            second = f"{out.count(overdue, 'overdue items', cap=True)} {_plural(overdue, 'item is', 'items are')} overdue."
        else:
            second = "The rest is moving."
        return "decisions", f"{first} {second}"
    clauses: list[tuple[int, str, str]] = []  # (count, label, the words after the count)
    replies = facts.get("customer_replies", 0)
    if replies:
        clauses.append((replies, "customer replies", f"customer {_plural(replies, 'reply needs', 'replies need')} attention"))
    expiring = facts.get("quotes_expiring_today", 0)
    if expiring:
        clauses.append((expiring, "quotes expiring today", f"{_plural(expiring, 'quote expires', 'quotes expire')} today"))
    due = facts.get("tasks_due_today", 0) + facts.get("onboarding_steps", 0)
    if due:
        clauses.append((due, "tasks due today", f"{_plural(due, 'task is', 'tasks are')} due today"))
    if overdue:
        clauses.append((overdue, "overdue items", f"{_plural(overdue, 'item is', 'items are')} overdue"))
    if not clauses:
        return "empty", "Nothing needs you right now."
    # every clause starts with its count, so the first count word carries the sentence's capital
    parts = [f"{out.count(n, label, cap=index == 0)} {rest}" for index, (n, label, rest) in enumerate(clauses)]
    return "clauses", _join_plain(parts)


def sentence_case(text: str) -> str:
    """Capitalise the first letter of the text and of each sentence (for substituted templates and phrased
    text: a count fact is lower case so that the model may place it anywhere)."""
    return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def compose(facts: dict[str, int], *, first_name: str, new_member: bool) -> tuple[str, str]:
    """(template_code, sentence)."""
    return _compose(facts, first_name, new_member, _Slots(template=False))


def compose_template(facts: dict[str, int], *, first_name: str, new_member: bool) -> tuple[str, str, tuple[Slot, ...]]:
    """(template_code, sentence with ``{{a1}}`` placeholders, the facts behind them). Substituting the slots and
    applying ``sentence_case`` gives exactly ``compose``'s sentence; phrasing rewords the template and the
    validator checks it against the slots."""
    out = _Slots(template=True)
    code, template = _compose(facts, first_name, new_member, out)
    return code, template, tuple(out.slots)


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
