"""The deterministic command grammar and the Demo request grammar against the English + Hinglish fixtures."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import BACKEND_DIR
from app.modules.agents.providers.demo import parse_request
from app.modules.agents.providers.demo_intents import NAV_TARGETS, parse_command

FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "demo_intents"


def _load(name: str) -> list[dict]:
    return json.loads(Path(FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load("commands.json"), ids=lambda c: c["text"])
def test_deterministic_commands_need_no_model(case: dict) -> None:
    command = parse_command(case["text"])
    assert command is not None, case["text"]
    assert command.kind == case["kind"] and command.language == case["language"]
    if "ordinal" in case:
        assert command.ordinal == case["ordinal"]
    if "until" in case:
        assert command.until == case["until"]
    if "target" in case:
        assert command.target == case["target"] and command.path == case["path"]
    assert parse_request(case["text"]) is None or case["kind"] == "today_overview", "commands never reach the router"


@pytest.mark.parametrize(
    "text", ["Prepare Nordhaus's usual oak tray quote", "change it to 300", "hello", "", "open sesame", "what is this"]
)
def test_non_commands_fall_through_to_the_router(text: str) -> None:
    assert parse_command(text) is None


@pytest.mark.parametrize("case", _load("requests.json"), ids=lambda c: c["text"])
def test_request_grammar_and_slot_extraction(case: dict) -> None:
    intent = parse_request(case["text"])
    if case["kind"] is None:
        assert intent is None
        return
    assert intent is not None, case["text"]
    assert intent.kind == case["kind"] and intent.language == case["language"]
    if "party" in case:
        assert intent.party_query == case["party"] and intent.product_words == case["product"]
        assert intent.currency == case["currency"] and intent.usual
    if "quantity" in case:
        assert intent.quantity == (Decimal(case["quantity"]) if case["quantity"] else None)


def test_navigation_targets_are_canonical_paths() -> None:
    assert all(path.startswith("/") for _, path in NAV_TARGETS.values())
    assert NAV_TARGETS["quotes"] == ("quotes", "/sales/quotes") and NAV_TARGETS["today"] == ("today", "/today")


def test_long_or_empty_text_is_never_a_command() -> None:
    assert parse_command("") is None and parse_command("open " * 60) is None
