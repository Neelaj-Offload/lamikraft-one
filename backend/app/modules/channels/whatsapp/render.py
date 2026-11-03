"""Rendering an assistant turn (server-built cards) as a WhatsApp message: short text with the figures taken from
the card (never from model prose), up to three reply buttons. Costing is never rendered. Demo accounts prefix
"Demo:" so a simulated conversation is never mistaken for a connected one."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_TEXT = 1024
MAX_BUTTONS = 3
BUTTON_TITLE = 20


@dataclass(frozen=True)
class ButtonSpec:
    #: review -> a review link to the card's canonical path; open -> workspace link; option -> clarification choice
    kind: str
    title: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rendered:
    text: str
    buttons: list[ButtonSpec] = field(default_factory=list)
    #: a URL the text should carry when buttons cannot (templates, plain text)
    links: list[tuple[str, str]] = field(default_factory=list)


def money(value: Any, currency: str) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return f"{currency} {value}"
    quant = amount.quantize(Decimal("0.01"))
    return f"{currency} {quant:,}"


def quantity(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return str(amount.quantize(Decimal(1))) if amount == amount.to_integral_value() else str(amount.normalize())


def _quote_draft(card: dict[str, Any]) -> tuple[str, list[ButtonSpec]]:
    currency = str(card.get("currency") or "")
    lines = card.get("lines") or []
    parts: list[str] = []
    status = str(card.get("status") or "draft")
    number = card.get("quote_number")
    preview = bool(card.get("preview_only"))
    parts.append(("Preview" if preview else "Draft ready") + (f" ({number})" if number and not preview else "") + ".")
    for line in lines[:3]:
        name = line.get("product_name") or line.get("product_key") or "item"
        qty = quantity(line.get("quantity")) if line.get("quantity") is not None else "?"
        uom = line.get("uom") or ""
        unit = money(line["unit_price"], currency) if line.get("unit_price") is not None else None
        text = f"{qty} {uom} {name}".replace("  ", " ").strip()
        if unit:
            text += f" at {unit} each"
        parts.append(text + ".")
    if len(lines) > 3:
        parts.append(f"And {len(lines) - 3} more line(s).")
    totals = card.get("totals") or {}
    if totals.get("grand_total") is not None:
        parts.append(f"Total {money(totals['grand_total'], str(totals.get('currency') or currency))}.")
    if totals.get("minimum_status") == "BELOW":
        parts.append("Below the EUR minimum order value.")
    if card.get("requires_confirmation"):
        parts.append("This draft came from external content and needs your confirmation on the web.")
    parts.append(f"Status: {status}, not sent.")
    buttons: list[ButtonSpec] = []
    review = card.get("review") or {}
    if review.get("path") and card.get("quote_id"):
        buttons.append(ButtonSpec("review", "Review quote", {"path": review["path"], "target_type": "sales.quote", "target_id": str(card["quote_id"]), "version": card.get("version")}))
    buttons.append(ButtonSpec("open", "Open workspace", {"path": "/today"}))
    return " ".join(parts), buttons


def _clarification(card: dict[str, Any]) -> tuple[str, list[ButtonSpec]]:
    question = str(card.get("question") or "Which one did you mean?")
    buttons: list[ButtonSpec] = []
    for option in (card.get("options") or [])[:MAX_BUTTONS]:
        action = option.get("action") or {}
        title = str(option.get("label") or action.get("label") or option.get("ref") or "Option")
        buttons.append(ButtonSpec("option", title, {"slot": action.get("slot"), "value": action.get("value"), "label": title}))
    extra = len(card.get("options") or []) - len(buttons)
    if extra > 0:
        question += f" ({extra} more option(s) on the web.)"
    return question, buttons


def _error(card: dict[str, Any]) -> tuple[str, list[ButtonSpec]]:
    message = str(card.get("message") or "The assistant could not complete that.")
    buttons = [ButtonSpec("open", "Open workspace", {"path": "/today"})]
    draft = card.get("recoverable_draft") or {}
    if draft.get("path"):
        buttons.insert(0, ButtonSpec("review", str(draft.get("label") or "Open draft")[:BUTTON_TITLE], {"path": draft["path"]}))
    return message, buttons


def _receipt(card: dict[str, Any]) -> tuple[str, list[ButtonSpec]]:
    record = card.get("record") or {}
    buttons = [ButtonSpec("review", str(record.get("label") or "Open record")[:BUTTON_TITLE], {"path": record["path"]})] if record.get("path") else []
    return str(card.get("summary") or card.get("action") or "Done."), buttons


def render_turn(text: str | None, cards: list[dict[str, Any]], *, demo: bool, failed: bool = False) -> Rendered:
    body: str
    buttons: list[ButtonSpec] = []
    card = next((c for c in cards if c.get("kind") in ("quote_draft", "clarification", "error", "receipt", "record_link")), None)
    if card is None:
        body = (text or "").strip() or ("The assistant could not complete that; open the workspace to continue." if failed else "Done.")
        buttons = [ButtonSpec("open", "Open workspace", {"path": "/today"})]
    elif card["kind"] == "quote_draft":
        body, buttons = _quote_draft(card)
    elif card["kind"] == "clarification":
        body, buttons = _clarification(card)
    elif card["kind"] == "error":
        body, buttons = _error(card)
    elif card["kind"] == "receipt":
        body, buttons = _receipt(card)
    else:
        body = str(card.get("label") or text or "Open the record on the web.")
        buttons = [ButtonSpec("review", "Open record", {"path": card.get("path") or "/today"})]
    if demo and not body.startswith("Demo:"):
        body = f"Demo: {body}"
    return Rendered(text=body[:MAX_TEXT], buttons=[ButtonSpec(b.kind, b.title[:BUTTON_TITLE], b.data) for b in buttons[:MAX_BUTTONS]])


def plain(text: str, *, demo: bool) -> str:
    text = text.strip()
    if demo and not text.startswith("Demo:"):
        text = f"Demo: {text}"
    return text[:MAX_TEXT]


__all__ = ["BUTTON_TITLE", "MAX_BUTTONS", "MAX_TEXT", "ButtonSpec", "Rendered", "money", "plain", "quantity", "render_turn"]
