"""The deterministic Demo orchestrator (``LK_AI_MODE=demo``): Claude-shaped, no keys, labelled "Demo".

It implements the same provider interface the Slice-3 Anthropic adapter will: it reads the message history (user
text plus the tool results the orchestrator appended), parses the request with a small intent grammar and slot
extractor, and emits the next step as a ``ToolUseBlock`` over the registered ToolDefs — ``resolve_party``,
``find_usual_order``, ``resolve_product``, ``resolve_price``, ``calculate_quote``, ``draft_quote``
(``revise_draft_line`` when the sales module provides it) — or a meta ``ask_clarification`` call, or final text.
It is stateless: every call recomputes the plan from the history, so a replayed request yields the same step.

Figures never appear in its text (the server builds cards from tool outputs; the numeric-claim checker would
replace them anyway). Prices are never tool inputs; quantities carry ``quantity_source`` for provenance.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.modules.agents import numbers
from app.modules.agents.providers.base import (
    Message,
    ModelRequest,
    ModelResponse,
    Stopwatch,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    latest_user_text,
    tool_results,
)
from app.modules.agents.providers.demo_intents import HELP_TEXT

PROVIDER_NAME = "demo"
PROVIDER_LABEL = "Demo"
DEMO_MODEL = "demo-orchestrator-v1"
ASK_CLARIFICATION = "ask_clarification"

RequestKind = Literal["prepare_usual_quote", "change_quantity", "screen_question"]
CURRENCIES = ("EUR", "GBP", "USD", "INR")


@dataclass(frozen=True)
class RequestIntent:
    kind: RequestKind
    language: Literal["en", "hinglish"]
    pattern: str
    party_query: str | None = None
    product_words: str | None = None
    quantity: Decimal | None = None
    currency: str | None = None
    usual: bool = False


# ---- request grammar and slot extraction ----------------------------------------------------------------------
_CURRENCY = re.compile(r"\b(?:in\s+)?(EUR|GBP|USD|INR|euros?|pounds?|dollars?|rupees?)\b", re.I)
_CURRENCY_WORDS = {"euro": "EUR", "euros": "EUR", "pound": "GBP", "pounds": "GBP", "dollar": "USD", "dollars": "USD",
                   "rupee": "INR", "rupees": "INR"}
_QTY_SUFFIX = re.compile(
    r"\b(?:for|of|x|qty|quantity)?\s*(\d{1,3}(?:,\d{2,3})+|\d+)\s*(?:pcs|pieces|piece|units|nos|sets)?\s*$", re.I
)
_NUM_WORD = r"(?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?|[a-z]+(?:[\s-][a-z]+){0,4})"

_USUAL_EN = (
    ("usual_possessive_en",
     re.compile(r"^(?:please\s+)?(?:prepare|make|create|draft|build|raise|do|get)\s+(?:me\s+)?(?:a\s+|the\s+)?"
                r"(?:quote\s+(?:for|of)\s+)?(?P<party>.+?)(?:'s|’s|s')\s+(?:usual|repeat|regular|standard|last)\s+"
                r"(?P<product>.+?)\s+(?:quote|quotation)(?P<tail>.*)$", re.I)),
    ("usual_for_en",
     re.compile(r"^(?:please\s+)?(?:prepare|make|create|draft|build|raise)\s+(?:me\s+)?(?:a\s+|the\s+)?"
                r"(?:usual|repeat|regular|standard)\s+(?P<product>.+?)\s+(?:quote|quotation)\s+for\s+(?P<party>.+?)"
                r"(?P<tail>\s+(?:for|at|of|x)\s+.*)?$", re.I)),
    ("repeat_order_en",
     re.compile(r"^(?:please\s+)?(?:repeat|redo)\s+(?P<party>.+?)(?:'s|’s|s')\s+(?:last|usual|previous)\s+"
                r"(?P<product>.+?)\s+(?:order|quote)(?:\s+as\s+a\s+quote)?(?P<tail>.*)$", re.I)),
)
_USUAL_HI = (
    ("usual_hi",
     re.compile(r"^(?:please\s+)?(?P<party>.+?)\s+(?:ka|ki|ke)\s+(?:usual|wahi|regular|same|purana|pichla)\s+"
                r"(?P<product>.+?)\s+(?:quote|quotation)\s+(?:bana\s*do|banao|bana|taiyar\s*karo|taiyaar\s*karo|"
                r"ready\s*karo|prepare\s*karo)(?P<tail>.*)$", re.I)),
)
_CHANGE_EN = (
    ("change_en",
     re.compile(r"^(?:please\s+)?(?:change|update|make|set|revise)\s+(?:it|that|this|the\s+(?:quantity|qty|line|"
                r"quantity\s+on\s+(?:it|that|this|the line)))\s+to\s+(?P<qty>" + _NUM_WORD +
                r")(?:\s*(?:pcs|pieces|units|nos))?$", re.I)),
    ("quantity_en", re.compile(r"^(?:(?:change|set|make|update)\s+)?(?:the\s+)?(?:quantity|qty)\s+(?:to\s+)?(?P<qty>"
                               + _NUM_WORD + r")$", re.I)),
)
_CHANGE_HI = (
    ("change_hi",
     re.compile(r"^(?:please\s+)?(?:isko|ise|is\s*ko|quantity|qty|yeh|ye)\s+(?P<qty>" + _NUM_WORD +
                r")\s+(?:kar\s*do|karo|karde|kardo|kar)$", re.I)),
    ("change_hi_bare", re.compile(r"^(?P<qty>" + _NUM_WORD + r")\s+(?:kar\s*do|karo|kardo)$", re.I)),
)
_SCREEN_QUESTION = re.compile(
    r"^(?:what(?:'s| is)\s+(?:on|shown on|this)\s+(?:my\s+)?(?:screen|page|panel)|what\s+(?:does|do)\s+(?:this|these)"
    r"\s+(?:show|mean)|explain\s+(?:this|the)\s+(?:panel|screen|page|chart)|where\s+is\s+.+\s+on\s+(?:my\s+)?screen)"
    r"\??$", re.I)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip().strip(".!?,; ")


def _slot_currency(text: str) -> str | None:
    match = _CURRENCY.search(text)
    if not match:
        return None
    raw = match.group(1).lower()
    return raw.upper() if raw.upper() in CURRENCIES else _CURRENCY_WORDS.get(raw)


def _strip_currency(text: str) -> str:
    return _clean(_CURRENCY.sub(" ", text))


def _quantity_from_tail(tail: str) -> Decimal | None:
    tail = _clean(tail)
    if not tail:
        return None
    match = _QTY_SUFFIX.search(tail)
    if match:
        return numbers.parse_decimal(match.group(1))
    return numbers.first_quantity(tail)


def parse_request(text: str) -> RequestIntent | None:
    """Parse an orchestration request (usual quote, quantity change) or a screen question; ``None`` when unknown."""
    cleaned = _clean(text)
    if not cleaned or len(cleaned) > 400:
        return None
    currency = _slot_currency(cleaned)
    for language, patterns in (("en", _USUAL_EN), ("hinglish", _USUAL_HI)):
        for name, pattern in patterns:
            match = pattern.fullmatch(cleaned)
            if not match:
                continue
            party = _strip_currency(match.group("party"))
            product = _strip_currency(match.group("product"))
            quantity = _quantity_from_tail(match.group("tail") or "")
            if not party or not product:
                continue
            return RequestIntent(
                kind="prepare_usual_quote", language=language, pattern=name, party_query=party,  # type: ignore[arg-type]
                product_words=product, quantity=quantity, currency=currency, usual=True,
            )
    for language, patterns in (("en", _CHANGE_EN), ("hinglish", _CHANGE_HI)):
        for name, pattern in patterns:
            match = pattern.fullmatch(cleaned)
            if not match:
                continue
            quantity = numbers.first_quantity(match.group("qty"))
            if quantity is None:
                continue
            return RequestIntent(kind="change_quantity", language=language, pattern=name, quantity=quantity)  # type: ignore[arg-type]
    if _SCREEN_QUESTION.fullmatch(cleaned):
        return RequestIntent(kind="screen_question", language="en", pattern="screen_question")
    return None


# ---- reading the history --------------------------------------------------------------------------------------
@dataclass
class Results:
    """Tool results of this run by name (the Demo provider reads earlier results like a model would)."""

    items: list[ToolResultBlock] = field(default_factory=list)

    def last(self, name: str) -> ToolResultBlock | None:
        for item in reversed(self.items):
            if item.name == name:
                return item
        return None

    def last_ok(self, name: str) -> Mapping[str, Any] | None:
        item = self.last(name)
        if item is None or item.is_error:
            return None
        output = item.content.get("output")
        return output if isinstance(output, Mapping) else None

    @property
    def last_error(self) -> ToolResultBlock | None:
        return self.items[-1] if self.items and self.items[-1].is_error else None


@dataclass(frozen=True)
class _Step:
    tool: ToolUseBlock | None = None
    text: str | None = None


def _tool(name: str, data: Mapping[str, Any]) -> _Step:
    return _Step(tool=ToolUseBlock(id=f"demo-{uuid.uuid4().hex[:12]}", name=name, input=dict(data)))


def _clarify(slot: str, question: str) -> _Step:
    return _tool(ASK_CLARIFICATION, {"slot": slot, "question": question})


def _final(text: str) -> _Step:
    return _Step(text=text)


def _line_matches(line: Mapping[str, Any], words: str | None) -> bool:
    if not words:
        return True
    tokens = {t for t in re.split(r"[^a-z0-9]+", words.lower()) if t}
    haystack = " ".join(str(line.get(k) or "") for k in ("product_key", "product_name", "display_sku")).lower()
    return bool(tokens) and all(t in haystack for t in tokens)


def _pick_line(
    lines: Sequence[Mapping[str, Any]], words: str | None, resolved_product: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    if resolved_product and resolved_product.get("status") == "unique":
        candidate = resolved_product["candidates"][0]
        for line in lines:
            if str(line.get("product_id")) == str(candidate.get("product_id")):
                return line
    matching = [line for line in lines if _line_matches(line, words)]
    if len(matching) == 1:
        return matching[0]
    if len(lines) == 1 and not words:
        return lines[0]
    if len(lines) == 1 and words:
        # one line in the usual order: accept it unless the words clearly name something else
        return lines[0] if matching or resolved_product is None else None
    return None


def _party_error(status: str, query: str | None) -> str:
    if status == "not_found":
        return f"I could not find a customer matching “{query}” in your access. Check the name or ask for it to be shared."
    return f"The customer “{query}” could not be resolved ({status})."


def _plan_usual_quote(intent: RequestIntent, results: Results, context: Mapping[str, Any], tools: frozenset[str]) -> _Step:
    error = results.last_error
    if error is not None:
        return _final("Demo: I could not complete that step; the details are on the card.")
    selected = context.get("selected_option") or {}
    party_id: str | None = None
    party_label = intent.party_query or "the customer"
    currency = intent.currency
    if selected.get("slot") == "party" and selected.get("value"):
        party_id = str(selected["value"])
        party_label = str(selected.get("label") or party_label)
        currency = currency or (selected.get("data") or {}).get("default_currency")
    else:
        party = results.last_ok("resolve_party")
        if party is None:
            return _tool("resolve_party", {"query": intent.party_query, "party_role": "customer"})
        if party.get("status") == "ambiguous":
            return _clarify("party", f"Which customer do you mean by “{intent.party_query}”?")
        if party.get("status") != "unique":
            return _final(_party_error(str(party.get("status")), intent.party_query))
        candidate = party["candidates"][0]
        party_id = str(candidate["party_id"])
        party_label = str(candidate.get("display_name") or party_label)
        currency = currency or candidate.get("default_currency")
    usual = results.last_ok("find_usual_order")
    if usual is None:
        return _tool("find_usual_order", {"party_id": party_id})
    lines = list(usual.get("lines") or [])
    if not usual.get("quote_id") or not lines:
        return _final(f"Demo: {party_label} has no previous won quote to repeat, so there is no usual order to draft.")
    line = _pick_line(lines, intent.product_words, results.last_ok("resolve_product"))
    if line is None:
        if intent.product_words and results.last("resolve_product") is None and "resolve_product" in tools:
            return _tool("resolve_product", {"query": intent.product_words})
        return _clarify("line", f"Which line of {usual.get('quote_number')} should I repeat?")
    quantity = intent.quantity if intent.quantity is not None else Decimal(str(line["quantity"]))
    quantity_source = "user_turn" if intent.quantity is not None else "record"
    currency = currency or usual.get("currency") or "EUR"
    price = results.last_ok("resolve_price")
    if price is None:
        return _tool("resolve_price", {
            "product_id": str(line["product_id"]), "party_id": party_id, "currency": currency, "uom": line.get("uom") or "pcs",
        })
    if price.get("status") != "found":
        return _final("Demo: no usable price was found for that line; the details are on the card.")
    calculation = results.last_ok("calculate_quote")
    if calculation is None:
        return _tool("calculate_quote", {
            "currency": currency,
            "surcharge_requested": False,
            "lines": [{"line_key": "l1", "price_list_item_id": str(price["item_id"]), "quantity": str(quantity),
                       "quantity_source": quantity_source}],
        })
    draft = results.last_ok("draft_quote")
    if draft is None:
        return _tool("draft_quote", {
            "party_id": party_id,
            "currency": currency,
            "lines": [{"product_id": str(line["product_id"]), "quantity": str(quantity), "quantity_source": quantity_source,
                       "uom": line.get("uom") or "pcs"}],
        })
    return _final(f"Demo: draft {draft.get('quote_number')} for {party_label} is ready to review; the figures are on the card.")


def _focused_line(context: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any] | None, list[Mapping[str, Any]]]:
    """(quote_id, line, all lines) from the re-read screen focus or the last QuoteDraftCard."""
    card = context.get("last_quote_card") or {}
    lines = list(card.get("lines") or [])
    focus = context.get("focus") or {}
    if focus.get("type") == "sales.quote_line" and focus.get("id"):
        for line in lines:
            if str(line.get("line_id")) == str(focus["id"]):
                return str(card.get("quote_id")), line, lines
        return str(focus.get("quote_id") or card.get("quote_id") or ""), {"line_id": str(focus["id"])}, lines
    if len(lines) == 1:
        return str(card.get("quote_id")), lines[0], lines
    return (str(card.get("quote_id")) if card else None), None, lines


def _plan_change_quantity(intent: RequestIntent, results: Results, context: Mapping[str, Any], tools: frozenset[str]) -> _Step:
    if results.last_error is not None:
        return _final("Demo: I could not apply that change; the details are on the card.")
    quote_id, line, lines = _focused_line(context)
    if not quote_id or line is None:
        if lines:
            return _clarify("line", "Which line should I change?")
        return _final("Demo: there is no draft quote line in focus. Open the draft or ask for a quote first.")
    quantity = str(intent.quantity)
    if "revise_draft_line" in tools:
        if results.last_ok("revise_draft_line") is None:
            return _tool("revise_draft_line", {
                "quote_id": quote_id, "line_id": str(line["line_id"]), "quantity": quantity, "quantity_source": "user_turn",
            })
        return _final("Demo: the line is updated; the recalculated figures are on the card.")
    if results.last_ok("calculate_quote") is None:
        item_id = line.get("price_list_item_id")
        if not item_id:
            return _final("Demo: the focused line has no price-list item to recalculate from.")
        return _tool("calculate_quote", {
            "currency": str(context.get("last_quote_card", {}).get("currency") or "EUR"),
            "surcharge_requested": bool(context.get("last_quote_card", {}).get("apply_minimum_surcharge", False)),
            "lines": [{"line_key": str(line["line_id"]), "price_list_item_id": str(item_id), "quantity": quantity,
                       "quantity_source": "user_turn"}],
        })
    return _final("Demo: recalculated the line as a preview; the figures are on the card.")


def _plan_screen_question(*_: Any) -> _Step:
    return _final(
        "Demo: answers about what is on screen use the vision provider, which arrives in Slice 3. "
        "Ask for a record or an action instead."
    )


_PLANS = {
    "prepare_usual_quote": _plan_usual_quote,
    "change_quantity": _plan_change_quantity,
    "screen_question": _plan_screen_question,
}


def intent_from_messages(messages: Sequence[Message]) -> RequestIntent | None:
    """The request the conversation is about: the latest user text that parses (a clarification answer may carry
    no parseable text, so the earlier request still applies)."""
    for message in reversed(messages):
        if message.role != "user":
            continue
        text = message.text.strip()
        if not text:
            continue
        intent = parse_request(text)
        if intent is not None:
            return intent
    return None


class DemoProvider:
    name = PROVIDER_NAME
    label = PROVIDER_LABEL
    model = DEMO_MODEL

    def generate(self, request: ModelRequest) -> ModelResponse:
        clock = Stopwatch()
        intent = intent_from_messages(request.messages)
        if intent is None:
            text = HELP_TEXT if latest_user_text(request.messages) else "Demo: tell me what to prepare."
            return self._response((TextBlock(text),), "end_turn", clock)
        results = Results(tool_results(request.messages))
        step = _PLANS[intent.kind](intent, results, request.context, request.tool_names)
        if step.tool is not None:
            return self._response((step.tool,), "tool_use", clock)
        return self._response((TextBlock(step.text or ""),), "end_turn", clock)

    def _response(self, content: tuple[TextBlock | ToolUseBlock, ...], stop: str, clock: Stopwatch) -> ModelResponse:
        return ModelResponse(
            provider=self.name, model=self.model, content=content, stop_reason=stop,  # type: ignore[arg-type]
            usage=Usage(), request_id=None, latency_ms=clock.elapsed_ms,
        )
