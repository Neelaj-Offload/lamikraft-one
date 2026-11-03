"""Grounding in live mode (ai-routing.md section 6) through the real Anthropic adapter over a fake transport:
the Haiku router runs only when the grammar does not match, Sonnet gets the advertised tools, and a money or
quantity figure in the final text that no tool output of this run produced is replaced by "see card"."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.agents.models import AiCallLog
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import Assistant, tool_calls
from tests.integration.agents.live_fake import (
    FakeClaude,
    is_router,
    live_mode,
    message,
    text,
    tool_results,
    tool_use,
)
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
QUESTION = "how is Nordhaus doing with us lately"


def _router(request_type: str = "data_or_action", **slots: Any) -> dict[str, Any]:
    payload = {"request_type": request_type, "domains": ["sales"], "think_harder": False,
               "slots": {"customer": "Nordhaus", "product": None, "quantity": None, "quantity_source": None,
                         "unit": None, "currency": None, "date": None, **slots}}
    return message([text(json.dumps(payload))], model="claude-haiku-5-5", input_tokens=300, output_tokens=60, cache_read=0)


def script(body: dict[str, Any]) -> dict[str, Any]:
    if is_router(body):
        return _router()
    results = tool_results(body)
    if not results:
        return message([{"type": "thinking", "thinking": "", "signature": "sig"},
                        tool_use("tu_1", "resolve_party", {"query": "Nordhaus"})], stop_reason="tool_use")
    return message([text("Nordhaus has open business worth EUR 9,999.00 across 7 quotes.")])


def test_numeric_claims_without_tool_source_are_stripped(meera: Assistant, world: World,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClaude(script)
    with live_mode(monkeypatch, fake):
        detail = meera.say(QUESTION)
    assert detail["run"]["status"] == "succeeded", detail
    assert tool_calls(detail) == ["resolve_party"]
    assert "9,999" not in detail["text"] and "see card" in detail["text"]
    route = detail["steps"][0]
    assert route["output"]["source"] == "haiku" and route["model_route"] == "claude-haiku-5-5"
    assert route["output"]["task_class"] == "orchestration"

    router_body, first, second = fake.bodies
    assert is_router(router_body) and router_body["output_config"]["effort"] == "low"
    assert first["model"] == "claude-sonnet-5-5" and first["tool_choice"] == {"type": "auto"}
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"]["effort"] == "medium"
    assert first["max_tokens"] == 8192 and {t["name"] for t in first["tools"]} >= {"resolve_party", "draft_quote"}
    # thinking blocks of this run are replayed unchanged; the assistant turn is appended, never edited
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][len(first["messages"])]["content"][0]["type"] == "thinking"

    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        rows = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.run_id == detail["run"]["id"]).order_by(AiCallLog.created_at)))
    assert [(r.workflow, r.provider, r.model) for r in rows] == [
        ("route", "anthropic", "claude-haiku-5-5"), ("orchestrate", "anthropic", "claude-sonnet-5-5"),
        ("orchestrate", "anthropic", "claude-sonnet-5-5")]
    assert rows[1].cache_read_tokens == 900 and rows[1].request_id == "req_fake_2"
    assert all(r.user_id == world.user_id(keys.USERS.MEERA) and r.correlation_id == detail["run"]["correlation_id"] for r in rows)
    assert detail["run"]["input_tokens_used"] == sum(r.input_tokens + r.cache_read_tokens for r in rows)


def test_grammar_match_skips_the_router_call(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClaude(lambda body: message([text("Opening quotes.")]))
    with live_mode(monkeypatch, fake):
        detail = meera.say("go to quotes")
    assert detail["run"]["status"] == "succeeded" and fake.bodies == [], "deterministic commands need no model"


def test_refusal_ends_with_deterministic_text_and_direct_controls(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(body: dict[str, Any]) -> dict[str, Any]:
        if is_router(body):
            return _router()
        return message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "x"})

    fake = FakeClaude(refuse)
    with live_mode(monkeypatch, fake):
        detail = meera.say(QUESTION)
    assert detail["run"]["error_code"] == "refusal"
    error = next(c for c in detail["cards"] if c["kind"] == "error")
    assert error["code"] == "refusal" and {link["path"] for link in error["direct_controls"]} >= {"/sales/quotes"}
    assert fake.headers[1].get("anthropic-beta") == "server-side-fallback-2026-07-01"
    assert fake.bodies[1]["fallbacks"] == "default"
    assert "anthropic-beta" not in fake.headers[0] or "fallback" not in fake.headers[0]["anthropic-beta"], "no Haiku fallbacks"
