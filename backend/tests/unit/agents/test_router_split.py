"""Split by request (ai-routing.md section 3) and the escalation rules (section 2): grammar first, then the Haiku
classifier; Opus only by rule, never chosen by the router for a single-domain request."""

from __future__ import annotations

import json

import pytest

from app.modules.agents import routing
from app.modules.agents.classify import (
    REQUEST_TYPES,
    Classification,
    clarification_failures,
    classify_deterministic,
    decide_escalation,
    expected_provider,
    parse_router_output,
    route_for,
    router_request,
)
from app.modules.agents.providers.base import ModelResponse, TextBlock


def _router_reply(payload: dict) -> ModelResponse:
    return ModelResponse(provider="anthropic", model="claude-haiku-5-5", stop_reason="end_turn",
                         content=(TextBlock(json.dumps(payload)),))


def test_request_types_route_to_expected_provider() -> None:
    live = {t: expected_provider(t, mode="live") for t in REQUEST_TYPES}  # type: ignore[arg-type]
    assert live == {"command": "none", "screen_question": "gemini", "visual_extraction": "gemini",
                    "data_or_action": "anthropic", "analysis": "anthropic", "out_of_scope": "none"}
    assert {expected_provider(t, mode="demo") for t in REQUEST_TYPES} == {"demo"}  # type: ignore[arg-type]
    assert route_for("analysis") == "escalation" and route_for("data_or_action") == "orchestration"


def test_routing_table_models_efforts_and_caps() -> None:
    table = routing.table_from()
    assert table.model_for("routing") == table.model_for("phrasing") == "claude-haiku-5-5"
    assert table.model_for("orchestration") == "claude-sonnet-5-5" and table.model_for("escalation") == "claude-opus-5-5"
    assert table.effort_for("orchestration") == "medium" and table.effort_for("escalation") == "medium"
    assert table.effort_for("routing") == "low"
    assert table.budget("orchestration") == {"steps": 8, "seconds": 45, "input_tokens": 120_000, "max_tokens": 8_192}
    assert table.budget("escalation") == {"steps": 10, "seconds": 90, "input_tokens": 200_000, "max_tokens": 16_000}
    assert routing.PHRASING_CAPS == {"phrasing": 600, "narration": 1_200, "explain": 800, "notification": 400}
    override = routing.table_from(routing.AiRoutingSetting.model_validate({"models": {"orchestrator": "claude-opus-5-5"}}))
    assert override.model_for("orchestration") == "claude-opus-5-5"


def test_router_request_is_haiku_low_effort_structured() -> None:
    request = router_request("quote 240 oak trays for Nordhaus", model="claude-haiku-5-5")
    assert request.task_class == "routing" and request.effort == "low" and request.max_tokens == 1_024
    assert request.output_schema is not None and request.output_schema["additionalProperties"] is False


def test_grammar_classifies_without_a_model() -> None:
    usual = classify_deterministic("Prepare Nordhaus's usual oak tray quote", selected_option=None)
    assert usual is not None and usual.request_type == "data_or_action" and usual.source == "grammar"
    assert classify_deterministic("anything", selected_option={"option_id": "x"}).detail == "clarification_answer"  # type: ignore[union-attr]
    what_if = classify_deterministic("what-if we move production and stock across teams next month", selected_option=None)
    assert what_if is not None and what_if.request_type == "analysis"


def test_router_output_is_validated_and_quantities_need_the_literal() -> None:
    good = parse_router_output(_router_reply({
        "request_type": "data_or_action", "domains": ["sales"], "think_harder": False,
        "slots": {"customer": "Nordhaus", "product": "oak tray", "quantity": "240", "quantity_source": "user_turn",
                  "unit": "pcs", "currency": "EUR", "date": None}}), text="quote 240 oak trays for Nordhaus")
    assert good.request_type == "data_or_action" and good.slots["quantity"] == "240" and good.source == "haiku"
    invented = parse_router_output(_router_reply({
        "request_type": "data_or_action", "domains": ["sales"], "think_harder": False,
        "slots": {"customer": None, "product": None, "quantity": "500", "quantity_source": "user_turn",
                  "unit": None, "currency": None, "date": None}}), text="quote some oak trays")
    assert invented.slots["quantity"] is None and invented.slots["quantity_source"] is None
    for bad in ("not json", json.dumps({"request_type": "launch_rockets"})):
        reply = ModelResponse(provider="anthropic", model="claude-haiku-5-5", stop_reason="end_turn", content=(TextBlock(bad),))
        assert parse_router_output(reply, text="x").request_type == "out_of_scope"


@pytest.mark.parametrize(("classification", "repeats", "escalate", "reason"), [
    (Classification("data_or_action", "usual", "grammar", domains=("sales",)), 0, False, None),
    (Classification("data_or_action", "usual", "grammar", domains=("sales", "catalogue")), 0, False, None),
    (Classification("data_or_action", "x", "haiku", domains=("sales", "warehouse")), 0, True, "multi_domain"),
    (Classification("data_or_action", "x", "grammar", think_harder=True), 0, True, "think_harder"),
    (Classification("data_or_action", "x", "grammar"), 2, True, "repeated_clarification"),
    (Classification("data_or_action", "x", "grammar"), 1, False, None),
    (Classification("analysis", "analysis_pattern", "grammar"), 0, True, "analysis"),
    (Classification("analysis", "haiku", "haiku", domains=("sales",)), 0, False, "escalation_guard"),
    (Classification("analysis", "haiku", "haiku", domains=("sales", "finance")), 0, True, "analysis"),
])
def test_escalation_only_by_rule(classification: Classification, repeats: int, escalate: bool, reason: str | None) -> None:
    decision = decide_escalation(classification, repeated_clarifications=repeats)
    assert (decision.escalate, decision.reason) == (escalate, reason)
    assert decision.task_class == ("escalation" if escalate else "orchestration")


def test_clarification_failures_count_consecutive_same_slot() -> None:
    runs = [{"clarification_slot": "customer"}, {"clarification_slot": "product"}, {"clarification_slot": "product"}]
    assert clarification_failures(runs, "product") == 2
    assert clarification_failures(runs, "customer") == 0 and clarification_failures(runs, None) == 0
