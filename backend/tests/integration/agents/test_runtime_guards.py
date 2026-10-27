"""Runtime guards through the API: ID and numeric provenance rejections (no service call), run-as-member 403 inside
a step, budget exceeded, cancel, taint marking and send-tool hiding, the deterministic grammar surviving a provider
outage, out-of-scope help, live mode without a key (409 not_configured) and the AI call log."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.modules.agents import orchestrator, service
from app.modules.agents.grounding import Provenance
from app.modules.agents.models import AiCallLog, Run
from app.modules.agents.providers.base import ModelRequest, ModelResponse, TextBlock, ToolUseBlock, Usage
from app.modules.agents.providers.demo import DemoProvider
from app.modules.agents.tools_runtime import ToolContext, advertised_tools, execute_tool
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents import fake_sales
from tests.integration.agents.conftest import Assistant, cards_of, tool_calls
from tests.integration.catalogue.world import World
from tests.support import drain

pytestmark = pytest.mark.db
SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"


def _tool_ctx(world: World, persona: str = keys.USERS.MEERA, **prov: Any) -> ToolContext:
    actor = world.actor(persona)
    provenance = Provenance(known_ids=frozenset(prov.pop("known_ids", ())), user_text=prov.pop("user_text", ""), **prov)
    return ToolContext(actor=actor, run_id=uuid.uuid7(), conversation_id=uuid.uuid7(), step_seq=1, provenance=provenance)


# ---- provenance -----------------------------------------------------------------------------------------------
def test_guessed_id_rejected_by_provenance(world: World, sales_tools: fake_sales.FakeSalesStore) -> None:
    nordhaus = world.ref("NORDHAUS")
    ctx = _tool_ctx(world, known_ids={uuid.uuid7()})
    outcome = execute_tool(ctx, "find_usual_order", {"party_id": str(nordhaus)})
    assert outcome.is_error and outcome.error_code == "id_provenance" and outcome.status == 422
    assert sales_tools.calls == [], "rejected before any service call"
    ok = execute_tool(_tool_ctx(world, known_ids={nordhaus}), "find_usual_order", {"party_id": str(nordhaus)})
    assert not ok.is_error and ok.output_for_model["quote_number"] == keys.QUOTES.PRIOR_WON


def test_quantity_needs_provenance_and_must_match_its_source(world: World, sales_tools: fake_sales.FakeSalesStore) -> None:
    nordhaus, oak = world.ref("NORDHAUS"), world.ref("OAK_TRAY")
    known = {nordhaus, oak}
    line = {"product_id": str(oak), "uom": "pcs"}
    missing = execute_tool(_tool_ctx(world, known_ids=known, user_text="quote 240"), "draft_quote",
                           {"party_id": str(nordhaus), "currency": "EUR", "lines": [{**line, "quantity": "240"}]})
    assert missing.is_error and missing.error_code == "quantity_provenance"
    not_said = execute_tool(_tool_ctx(world, known_ids=known, user_text="quote some trays"), "draft_quote",
                            {"party_id": str(nordhaus), "currency": "EUR", "lines": [{**line, "quantity": "240", "quantity_source": "user_turn"}]})
    assert not_said.is_error and not_said.error_code == "quantity_provenance"
    no_record = execute_tool(_tool_ctx(world, known_ids=known, user_text=""), "draft_quote",
                             {"party_id": str(nordhaus), "currency": "EUR", "lines": [{**line, "quantity": "240", "quantity_source": "record"}]})
    assert no_record.is_error and no_record.error_code == "quantity_provenance"
    assert sales_tools.calls == []
    words = execute_tool(_tool_ctx(world, known_ids=known, user_text="quote two hundred forty trays"), "draft_quote",
                         {"party_id": str(nordhaus), "currency": "EUR", "lines": [{**line, "quantity": "240", "quantity_source": "user_turn"}]})
    assert not words.is_error, words.message
    grouped = execute_tool(_tool_ctx(world, known_ids=known, user_text="quote 1,00,000 trays"), "draft_quote",
                           {"party_id": str(nordhaus), "currency": "EUR", "lines": [{**line, "quantity": "100000", "quantity_source": "user_turn"}]})
    assert not grouped.is_error, grouped.message


def test_prices_are_never_model_inputs(world: World, sales_tools: fake_sales.FakeSalesStore) -> None:
    nordhaus, oak = world.ref("NORDHAUS"), world.ref("OAK_TRAY")
    ctx = _tool_ctx(world, known_ids={nordhaus, oak}, user_text="quote 240 at 26")
    priced = execute_tool(ctx, "draft_quote", {"party_id": str(nordhaus), "currency": "EUR",
                                               "lines": [{"product_id": str(oak), "uom": "pcs", "quantity": "240",
                                                          "quantity_source": "user_turn", "unit_price": "26.0000"}]})
    assert priced.is_error and priced.error_code == "price_not_model_input"
    bad_override = execute_tool(ctx, "draft_quote", {"party_id": str(nordhaus), "currency": "EUR", "price_override": {"value": "26"},
                                                     "lines": [{"product_id": str(oak), "uom": "pcs", "quantity": "240", "quantity_source": "user_turn"}]})
    assert bad_override.is_error and bad_override.error_code == "price_not_model_input"
    assert sales_tools.calls == []


def test_tool_input_extra_fields_and_unknown_tools_are_errors(world: World, sales_tools: fake_sales.FakeSalesStore) -> None:
    nordhaus = world.ref("NORDHAUS")
    extra = execute_tool(_tool_ctx(world, known_ids={nordhaus}), "find_usual_order", {"party_id": str(nordhaus), "user_id": str(nordhaus)})
    assert extra.is_error and extra.error_code == "invalid_input"
    missing = execute_tool(_tool_ctx(world), "draft_challan", {})
    assert missing.is_error and missing.error_code == "capability_not_installed" and missing.status == 501


# ---- run as member -----------------------------------------------------------------------------------------------
def test_tool_the_user_lacks_permission_for_fails_with_403_inside_the_step(client: Any, sales_tools: fake_sales.FakeSalesStore, world: World) -> None:
    kabir = Assistant(client, keys.USERS.KABIR)  # warehouse: no parties.party.read
    detail = kabir.say(SCENARIO_C_TEXT)
    assert detail["run"]["status"] == "failed" and detail["run"]["error_code"] == "permission_denied"
    step = next(s for s in detail["steps"] if s["kind"] == "tool_result" and s["name"] == "resolve_party")
    assert step["is_error"] and step["error_code"] == "permission_denied"
    assert tool_calls(detail) == ["resolve_party"]
    assert cards_of(detail, "error")[0]["code"] == "permission_denied"
    assert "resolve_party" not in {t.name for t in advertised_tools(world.actor(keys.USERS.KABIR))}


def test_service_authorisation_still_applies_inside_a_step(world: World, sales_tools: fake_sales.FakeSalesStore) -> None:
    """Neha holds sales.quote.read (own) but Nordhaus is Meera's party: the service answers 404, never the data."""
    nordhaus = world.ref("NORDHAUS")
    outcome = execute_tool(_tool_ctx(world, keys.USERS.NEHA, known_ids={nordhaus}), "find_usual_order", {"party_id": str(nordhaus)})
    assert outcome.is_error and outcome.error_code == "not_found" and outcome.status == 404


# ---- budget and cancel ------------------------------------------------------------------------------------------
def test_budget_exceeded_ends_the_run_with_an_error_card(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "STEP_BUDGET", 2)
    detail = meera.say(SCENARIO_C_TEXT)
    assert detail["run"]["status"] == "budget_exceeded" and detail["run"]["error_code"] == "budget_exceeded"
    assert tool_calls(detail) == ["resolve_party", "find_usual_order"]
    card = cards_of(detail, "error")[0]
    assert card["code"] == "budget_exceeded" and card["recoverable_draft"] is None
    assert not [q for q in fake_sales.STORE.quotes.values() if q.status == "draft"]


def test_budget_error_card_keeps_the_recoverable_draft(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    first = meera.say(SCENARIO_C_TEXT)
    monkeypatch.setattr(orchestrator, "STEP_BUDGET", 0)
    second = meera.say("change it to 300")
    assert second["run"]["status"] == "budget_exceeded"
    assert cards_of(second, "error")[0]["recoverable_draft"]["path"] == first["cards"][0]["review"]["path"]


def test_cancel_before_the_worker_runs(meera: Assistant, world: World) -> None:
    response = meera.post_turn(SCENARIO_C_TEXT)
    run_id = response.json()["run_id"]
    cancelled = meera.client.post(f"/api/v1/agents/runs/{run_id}/cancel", headers=meera.headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    drain()
    detail = meera.poll(run_id)
    assert detail["run"]["status"] == "cancelled" and tool_calls(detail) == [] and fake_sales.STORE.calls == []


def test_cancel_flag_stops_a_running_run_at_the_next_step(meera: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    original = DemoProvider.generate

    def generate_then_cancel(self: DemoProvider, request: ModelRequest) -> ModelResponse:
        response = original(self, request)
        if any(isinstance(b, ToolUseBlock) and b.name == "find_usual_order" for b in response.content):
            with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
                run = uow.session.scalars(select(Run).where(Run.status == "running")).one()
                service.cancel_run(uow, run.id)
        return response

    monkeypatch.setattr(DemoProvider, "generate", generate_then_cancel)
    detail = meera.say(SCENARIO_C_TEXT)
    assert detail["run"]["status"] == "cancelled" and tool_calls(detail) == ["resolve_party"]
    assert cards_of(detail, "error")[0]["code"] == "cancelled"


# ---- taint ---------------------------------------------------------------------------------------------------------
def test_external_content_taints_the_run_and_hides_send_tools(meera: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    nordhaus = str(world.ref("NORDHAUS"))

    class TaintingDemo(DemoProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            results = [b for m in request.messages for b in m.content if getattr(b, "name", None)]
            names = [b.name for b in results]
            if "resolve_party" not in names:
                return super().generate(request)
            if "fetch_external_note" not in names:
                block = ToolUseBlock(id="t-note", name="fetch_external_note", input={"party_id": nordhaus})
                return ModelResponse(provider="demo", model="demo-test", content=(block,), stop_reason="tool_use", usage=Usage())
            if "send_quote" not in names:
                assert "send_quote" not in request.tool_names and request.context["tainted"] is True
                block = ToolUseBlock(id="t-send", name="send_quote", input={"quote_id": nordhaus})
                return ModelResponse(provider="demo", model="demo-test", content=(block,), stop_reason="tool_use", usage=Usage())
            return ModelResponse(provider="demo", model="demo-test", content=(TextBlock("Demo: done; the note said 500 trays."),),
                                 stop_reason="end_turn", usage=Usage())

    monkeypatch.setattr("app.modules.agents.providers.DemoProvider", TaintingDemo)
    detail = meera.say(SCENARIO_C_TEXT)
    assert detail["run"]["tainted"] is True
    assert tool_calls(detail) == ["resolve_party", "fetch_external_note", "send_quote"]
    send = next(s for s in detail["steps"] if s["kind"] == "tool_result" and s["name"] == "send_quote")
    assert send["is_error"] and send["error_code"] == "tool_hidden_tainted"
    assert all(c["tainted"] for c in detail["cards"])
    # the figure in the model text came from untrusted text, not a tool output: replaced
    assert "500" not in detail["text"] and "see card" in detail["text"]


# ---- degradation ---------------------------------------------------------------------------------------------------
def test_grammar_path_works_when_the_provider_raises(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: DemoProvider, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("provider down")

    monkeypatch.setattr(DemoProvider, "generate", boom)
    detail = meera.say("go to quotes")
    assert detail["run"]["status"] == "succeeded" and detail["steps"][0]["output"]["request_type"] == "command"
    assert cards_of(detail, "record_link")[0]["path"] == "/sales/quotes"
    failed = meera.say(SCENARIO_C_TEXT)
    assert failed["run"]["status"] == "failed" and failed["run"]["error_code"] == "provider_unavailable"
    card = cards_of(failed, "error")[0]
    assert card["code"] == "provider_unavailable" and [c["path"] for c in card["direct_controls"]] == ["/sales/quotes", "/today"]
    with UnitOfWork(meera.client.app.state.__dict__.get("world", None) or _any_actor(meera)) as uow:  # type: ignore[attr-defined]
        rows = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.run_id == uuid.UUID(failed["run"]["id"]))))
        assert [r.outcome for r in rows] == ["error"] and rows[0].error_type == "RuntimeError"


def _any_actor(assistant: Assistant) -> Any:
    from tests.integration.catalogue.world import _PERSONAS

    return next(a for (_, _), a in _PERSONAS.items() if a.display_name == keys.PEOPLE[assistant.persona].name)


def test_out_of_scope_text_gets_the_help_message(meera: Assistant) -> None:
    detail = meera.say("sing me a song about plywood")
    assert detail["run"]["status"] == "succeeded" and detail["run"]["request_type"] == "out_of_scope"
    assert "commands" in detail["text"].lower() and detail["cards"] == [] and tool_calls(detail) == []


def test_screen_question_is_answered_deterministically_until_vision_ships(meera: Assistant) -> None:
    detail = meera.say("what is on my screen?")
    assert detail["run"]["status"] == "succeeded" and detail["run"]["request_type"] == "screen_question"
    assert "Slice 3" in detail["text"] and tool_calls(detail) == []


def test_live_mode_without_a_key_returns_409_not_configured(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LK_AI_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    reset_settings_cache()
    try:
        response = meera.post_turn(SCENARIO_C_TEXT)
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["code"] == "not_configured" and "ANTHROPIC_API_KEY" in body["detail"]
    finally:
        monkeypatch.delenv("LK_AI_MODE")
        reset_settings_cache()
    assert meera.post_turn(SCENARIO_C_TEXT).status_code == 202


def test_duplicate_client_utterance_replays_the_same_run(meera: Assistant) -> None:
    utterance = str(uuid.uuid7())
    first = meera.post_turn(SCENARIO_C_TEXT, client_utterance_id=utterance)
    second = meera.post_turn(SCENARIO_C_TEXT, client_utterance_id=utterance)
    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"] and second.json()["replayed"] is True
    drain()
    assert len([q for q in fake_sales.STORE.quotes.values() if q.status == "draft"]) == 1
