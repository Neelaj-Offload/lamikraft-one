"""Split by request (ai-routing.md section 3) and the escalation rules (section 2).

Order: the deterministic command grammar (``demo_intents``) → the deterministic request grammar (``demo.parse_request``)
→ in live mode the Haiku low-effort classifier with structured output. The router returns exactly one request type
and the extracted slots with ``quantity_source``; it may never select Opus for a single-domain request. Escalation
to Opus happens only by rule: ≥2 clarification failures on the same slot, a multi-domain request, or an explicit
"think harder".
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.agents.providers.base import Message, ModelRequest, ModelResponse, TextBlock
from app.modules.agents.providers.demo import parse_request
from app.modules.agents.schemas import RequestType

REQUEST_TYPES: tuple[str, ...] = ("command", "screen_question", "visual_extraction", "data_or_action", "analysis", "out_of_scope")
ROUTER_PROMPT_VERSION = "router.v1"
ROUTER_SYSTEM = (
    f"{ROUTER_PROMPT_VERSION}\nClassify one assistant message for a manufacturing ERP into exactly one request type "
    "and extract slots. Types: command (navigation, snooze, open an item), screen_question (what is shown on screen), "
    "visual_extraction (an attached photo or document), data_or_action (lookups, quote drafts, proposals), "
    "analysis (cross-team planning, what-if), out_of_scope. Slots: customer, product, quantity (digits only, with "
    "quantity_source 'user_turn'), unit, currency, date. Never invent a value; leave a slot null when not stated."
)
ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["request_type", "slots", "domains", "think_harder"],
    "properties": {
        "request_type": {"type": "string", "enum": list(REQUEST_TYPES)},
        "domains": {"type": "array", "items": {"type": "string", "enum": ["sales", "catalogue", "procurement", "production", "warehouse", "finance", "management"]}},
        "think_harder": {"type": "boolean"},
        "slots": {
            "type": "object",
            "additionalProperties": False,
            "required": ["customer", "product", "quantity", "quantity_source", "unit", "currency", "date"],
            "properties": {
                "customer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "product": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quantity": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quantity_source": {"anyOf": [{"type": "string", "enum": ["user_turn"]}, {"type": "null"}]},
                "unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "currency": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
        },
    },
}
_THINK_HARDER = re.compile(r"\b(think (harder|deeper|carefully|again)|dig deeper|deep analysis|zyada socho|dhyan se socho)\b", re.I)
_ANALYSIS = re.compile(r"\b(what[- ]if|cross[- ]team|across (teams|departments)|plan(ning)? for next (month|quarter)|forecast|scenario)\b", re.I)
_DOMAIN_WORDS: dict[str, re.Pattern[str]] = {
    "sales": re.compile(r"\b(quote|quotation|customer|enquiry|order|party)\b", re.I),
    "catalogue": re.compile(r"\b(product|catalogue|catalog|sku|decor|tray)\b", re.I),
    "procurement": re.compile(r"\b(purchase|vendor|supplier|po\b|procure)\b", re.I),
    "production": re.compile(r"\b(production|shift|machine|press|cutting|job card)\b", re.I),
    "warehouse": re.compile(r"\b(stock|warehouse|dispatch|challan|inventory|godown)\b", re.I),
    "finance": re.compile(r"\b(invoice|payment|receivable|ledger|gst|finance)\b", re.I),
}
MAX_CLARIFICATION_FAILURES = 2


@dataclass(frozen=True)
class Classification:
    request_type: str
    detail: str
    source: str  # grammar | demo-router | haiku
    slots: Mapping[str, Any] = field(default_factory=dict)
    domains: tuple[str, ...] = ()
    think_harder: bool = False
    model: str | None = None
    response: ModelResponse | None = None

    def as_output(self) -> dict[str, Any]:
        return {"request_type": self.request_type, "detail": self.detail, "source": self.source,
                "slots": dict(self.slots), "domains": list(self.domains), "think_harder": self.think_harder}


@dataclass(frozen=True)
class Escalation:
    escalate: bool
    reason: str | None = None

    @property
    def task_class(self) -> str:
        return "escalation" if self.escalate else "orchestration"


def domains_in(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _DOMAIN_WORDS.items() if pattern.search(text))


def classify_deterministic(text: str, *, selected_option: Mapping[str, Any] | None) -> Classification | None:
    """The request grammar (no model): a clarification answer or a parsed Demo intent; None when unrecognised."""
    if selected_option:
        return Classification("data_or_action", "clarification_answer", "grammar")
    intent = parse_request(text)
    if intent is None:
        if _ANALYSIS.search(text):
            return Classification("analysis", "analysis_pattern", "grammar", domains=domains_in(text), think_harder=bool(_THINK_HARDER.search(text)))
        return None
    if intent.kind == "screen_question":
        return Classification("screen_question", intent.kind, "grammar")
    slots = {"customer": intent.party_query, "product": intent.product_words,
             "quantity": str(intent.quantity) if intent.quantity is not None else None,
             "quantity_source": "user_turn" if intent.quantity is not None else None, "currency": intent.currency}
    return Classification("data_or_action", intent.kind, "grammar", slots=slots, domains=domains_in(text),
                          think_harder=bool(_THINK_HARDER.search(text)))


def router_request(text: str, *, model: str, context: Mapping[str, Any] | None = None) -> ModelRequest:
    return ModelRequest(
        task_class="routing", system=ROUTER_SYSTEM, model=model, max_tokens=1_024, effort="low",
        messages=(Message(role="user", content=(TextBlock(text),)),), output_schema=ROUTER_SCHEMA,
        context=dict(context or {}),
    )


def parse_router_output(response: ModelResponse, *, text: str) -> Classification:
    """A classifier reply as a Classification; anything malformed is ``out_of_scope`` (never a guess)."""
    try:
        data = json.loads(response.text or "{}")
    except json.JSONDecodeError:
        data = {}
    request_type = data.get("request_type") if isinstance(data, Mapping) else None
    if request_type not in REQUEST_TYPES:
        return Classification("out_of_scope", "router_unparseable", "haiku", model=response.model, response=response)
    slots = data.get("slots") if isinstance(data.get("slots"), Mapping) else {}
    quantity = slots.get("quantity") if isinstance(slots, Mapping) else None
    if quantity is not None and not re.fullmatch(r"\d{1,14}(\.\d{1,6})?", str(quantity)):
        slots = {**slots, "quantity": None, "quantity_source": None}
    if quantity is not None and str(quantity) not in text.replace(",", ""):
        slots = {**slots, "quantity": None, "quantity_source": None}  # numeric provenance: the literal must be in the turn
    domains = tuple(d for d in (data.get("domains") or []) if isinstance(d, str))
    return Classification(str(request_type), "haiku", "haiku", slots=dict(slots), domains=domains,
                          think_harder=bool(data.get("think_harder")) or bool(_THINK_HARDER.search(text)),
                          model=response.model, response=response)


def clarification_failures(previous_runs: Sequence[Mapping[str, Any]], slot: str | None) -> int:
    """How many consecutive earlier runs in this conversation ended with a clarification on ``slot``."""
    count = 0
    for run in reversed(list(previous_runs)):
        if run.get("clarification_slot") == slot and slot is not None:
            count += 1
        else:
            break
    return count


def decide_escalation(classification: Classification, *, repeated_clarifications: int) -> Escalation:
    """Opus only by rule (section 2); the router may never select it directly for a single-domain request."""
    if classification.request_type == "analysis":
        return Escalation(True, "analysis")
    if classification.think_harder:
        return Escalation(True, "think_harder")
    if len(classification.domains) >= 2 and classification.request_type == "data_or_action" and len(set(classification.domains) - {"sales", "catalogue"}) >= 1:
        return Escalation(True, "multi_domain")
    if repeated_clarifications >= MAX_CLARIFICATION_FAILURES:
        return Escalation(True, "repeated_clarification")
    return Escalation(False)


def route_for(request_type: str) -> str:
    """Which model class answers a request type before escalation rules (section 3)."""
    return {
        "command": "grammar", "screen_question": "vision", "visual_extraction": "vision",
        "data_or_action": "orchestration", "analysis": "escalation", "out_of_scope": "grammar",
    }[request_type]


def expected_provider(request_type: RequestType, *, mode: str) -> str:
    """The provider a request type routes to (section 9 test): demo in demo mode, else by route."""
    if mode == "demo":
        return "demo"
    return {"grammar": "none", "vision": "gemini", "orchestration": "anthropic", "escalation": "anthropic"}[route_for(request_type)]


__all__ = [
    "MAX_CLARIFICATION_FAILURES",
    "REQUEST_TYPES",
    "ROUTER_SCHEMA",
    "Classification",
    "Escalation",
    "clarification_failures",
    "classify_deterministic",
    "decide_escalation",
    "domains_in",
    "expected_provider",
    "parse_router_output",
    "route_for",
    "router_request",
]
