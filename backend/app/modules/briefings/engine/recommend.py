"""Recommendation rule table: (kind, facts) → recommended action, reason, expected effect, alternatives.

Text is rendered only from facts the member can see. Recommendations are persisted with the issue
fingerprint they were based on; a changed source makes them stale (new recommendation, same issue id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.briefings.engine.model import Candidate


@dataclass(frozen=True)
class Rule:
    action_code: str
    reason_code: str
    effect_code: str
    alternatives: tuple[str, ...]


RULES: dict[str, Rule] = {
    "reply_needed": Rule("REPLY_TO_CUSTOMER", "CUSTOMER_WAITING", "KEEPS_REPLY_PROMISE", ("assign", "snooze")),
    "reply_needed:blocked": Rule("FOLLOW_UP_REVIEW", "WAITING_FOR_REVIEW", "UNBLOCKS_REPLY", ("snooze",)),
    "quote_expiry": Rule("EXTEND_OR_FOLLOW_UP", "QUOTE_EXPIRES", "KEEPS_OFFER_OPEN", ("mark_handled", "snooze")),
    "review_draft": Rule("REVIEW_DRAFT", "DRAFT_READY", "READY_TO_SEND", ("assign", "snooze")),
    "approval_decision": Rule("REVIEW_AND_DECIDE", "AWAITING_YOUR_DECISION", "UNBLOCKS_REQUESTER", ("approve", "reject")),
    "enquiry_reply": Rule("ANSWER_ENQUIRY", "CUSTOMER_WAITING", "KEEPS_REPLY_PROMISE", ("assign", "snooze")),
    "onboarding_step": Rule("COMPLETE_STEP", "ONBOARDING", "GETS_YOU_STARTED", ("snooze",)),
    "onboarding_checkin": Rule("CHECK_IN", "NEW_TEAM_MEMBER", "SUPPORTS_NEW_HIRE", ("snooze",)),
    "manual": Rule("DO_TASK", "ASSIGNED_WORK", "COMPLETES_TASK", ("assign", "snooze")),
}

ACTION_TEXT = {
    "REPLY_TO_CUSTOMER": "Reply to {contact}",
    "FOLLOW_UP_REVIEW": "Reply once the review of {quotes} is decided",
    "EXTEND_OR_FOLLOW_UP": "Follow up with {party} or extend the validity",
    "REVIEW_DRAFT": "Review the draft and submit it",
    "REVIEW_AND_DECIDE": "Review the request and decide",
    "ANSWER_ENQUIRY": "Prepare a quote or reply to {party}",
    "COMPLETE_STEP": "Complete this step",
    "CHECK_IN": "Check in with {member}",
    "DO_TASK": "Do the task and mark it handled",
}
REASON_TEXT = {
    "CUSTOMER_WAITING": "{party} is waiting for an answer.",
    "WAITING_FOR_REVIEW": "The reply depends on the review of {quotes}.",
    "QUOTE_EXPIRES": "{quote} stops being valid at the end of its validity date.",
    "DRAFT_READY": "A draft is waiting for your review.",
    "AWAITING_YOUR_DECISION": "You are an eligible approver for this request.",
    "ONBOARDING": "Part of your onboarding.",
    "NEW_TEAM_MEMBER": "{member} joined your team.",
    "ASSIGNED_WORK": "This was assigned to you.",
}
EFFECT_TEXT = {
    "KEEPS_REPLY_PROMISE": "Keeps the reply within the promised time.",
    "UNBLOCKS_REPLY": "Lets you reply to the customer.",
    "KEEPS_OFFER_OPEN": "Keeps the offer open for the customer.",
    "READY_TO_SEND": "The quote can go to review or to the customer.",
    "UNBLOCKS_REQUESTER": "Lets the requester continue.",
    "GETS_YOU_STARTED": "Gets you set up.",
    "SUPPORTS_NEW_HIRE": "Helps the new team member settle in.",
    "COMPLETES_TASK": "Closes the task.",
}


def rule_for(c: Candidate) -> Rule | None:
    if c.category != "obligation":
        return None
    if c.kind == "reply_needed" and c.blocked:
        return RULES["reply_needed:blocked"]
    return RULES.get(c.kind)


def _fmt(template: str, facts: dict[str, Any]) -> str:
    safe = {
        "contact": facts.get("contact_name") or facts.get("party_name") or "the customer",
        "party": facts.get("party_name") or "the customer",
        "quotes": ", ".join(facts.get("quote_numbers") or []) or "the quote",
        "quote": facts.get("quote_number") or "The quote",
        "member": facts.get("new_member") or "the new team member",
    }
    return template.format(**safe)


def render(rule: Rule, facts: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {
        "action_code": rule.action_code,
        "label": _fmt(ACTION_TEXT.get(rule.action_code, rule.action_code), facts),
        "reason_code": rule.reason_code,
        "reason": _fmt(REASON_TEXT.get(rule.reason_code, ""), facts),
        "effect_code": rule.effect_code,
        "effect": _fmt(EFFECT_TEXT.get(rule.effect_code, ""), facts),
        "alternatives": [a for a in rule.alternatives if a in allowed],
    }
