"""Scenario C through the API (fixtures.md section 11): Meera asks for Nordhaus's usual oak tray quote at D0.

202 -> the ``agent.run`` job is drained inline -> polling returns the steps and the QuoteDraftCard with the persisted
totals (EUR 5,760.00, recommended 216) for LK-QT-2026-0009, owned by Meera, status draft, event
``agents.run.completed`` emitted. Plus the ambiguity variant (ClarificationCard with exactly two options, no draft;
the chosen option completes the draft) and the follow-up "change it to 300" (EUR 7,200.00 from the engine).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.agents.models import AiCallLog, ObjectContext, Run
from app.modules.parties import service as parties
from app.modules.parties.schemas import PartyCreate
from app.platform.events.models import DomainEvent
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents import fake_sales
from tests.integration.agents.conftest import Assistant, cards_of, tool_calls
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db

SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"
EXPECTED_TOOLS = ["resolve_party", "find_usual_order", "resolve_price", "calculate_quote", "draft_quote"]


def _assert_scenario_c_card(card: dict, world: World) -> None:
    assert card["kind"] == "quote_draft" and card["provider_label"] == "Demo" and card["tainted"] is False
    assert card["quote_number"] == keys.QUOTES.SCENARIO_C_NEW and card["status"] == "draft"
    assert card["party_label"] == keys.PARTY_NAMES["NORDHAUS"] and card["currency"] == "EUR"
    assert len(card["lines"]) == 1
    line = card["lines"][0]
    assert line["product_key"] == keys.PRODUCTS.OAK_TRAY and Decimal(line["quantity"]) == Decimal(keys.EXPECTED.SCENARIO_C_QTY)
    assert Decimal(line["unit_price"]) == Decimal(keys.PRICES.OAK_TRAY_EUR)
    assert Decimal(line["line_total"]) == Decimal(keys.EXPECTED.SCENARIO_C_TOTAL)
    totals = card["totals"]
    assert Decimal(totals["grand_total"]) == Decimal(keys.EXPECTED.SCENARIO_C_TOTAL)
    assert totals["minimum_status"] == "MEETS" and totals["surcharge_applied"] is False
    assert totals["recommended_quantity"] == int(keys.EXPECTED.SCENARIO_D_RECOMMENDED_QTY)
    assert card["review"]["path"] == f"/sales/quotes/{card['quote_id']}"
    draft = fake_sales.STORE.quotes[uuid.UUID(card["quote_id"])]
    assert draft.owner_user_id == world.user_id(keys.USERS.MEERA) and draft.status == "draft" and draft.origin == "agent"


def test_agent_c_text_demo_usual_oak_tray_quote(meera: Assistant, world: World) -> None:
    response = meera.post_turn(SCENARIO_C_TEXT, context={"schema_version": 1, "route": {"path": "/today", "area": "today"}})
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "queued" and response.headers["location"].endswith(accepted["run_id"])
    queued = meera.poll(accepted["run_id"])
    assert queued["done"] is False and queued["run"]["status"] == "queued" and queued["cards"] == []

    from tests.support import drain

    drain()
    detail = meera.poll(accepted["run_id"])
    assert detail["done"] and detail["run"]["status"] == "succeeded", detail
    assert detail["run"]["provider"] == "demo" and detail["run"]["provider_label"] == "Demo" and detail["run"]["mode"] == "demo"
    assert tool_calls(detail) == EXPECTED_TOOLS
    assert all(not s["is_error"] for s in detail["steps"])
    assert detail["steps"][0]["kind"] == "route" and detail["steps"][0]["output"]["request_type"] == "data_or_action"
    assert "see card" not in detail["text"] and "5" not in detail["text"].replace("LK-QT-2026-0009", "")
    _assert_scenario_c_card(detail["cards"][0], world)

    # polling with after_seq returns only newer steps; the final text/card steps are last
    tail = meera.poll(accepted["run_id"], after_seq=detail["last_seq"] - 2)
    assert [s["seq"] for s in tail["steps"]] == [detail["last_seq"] - 1, detail["last_seq"]]
    assert tail["steps"][-1]["kind"] == "text"

    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(accepted["run_id"]))
        assert run is not None and run.tool_call_count == 5 and run.assistant_turn_id is not None and not run.tainted
        events = list(uow.session.scalars(select(DomainEvent).where(DomainEvent.aggregate_id == run.id)))
        assert [e.event_type for e in events] == ["agents.run.completed"]
        assert events[0].payload["status"] == "succeeded" and events[0].payload["user_id"] == str(run.user_id)
        assert events[0].payload["trigger"] == "user_turn"
        calls = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.run_id == run.id)))
        assert len(calls) == 6 and {c.provider for c in calls} == {"demo"}
        assert all(c.input_tokens == 0 and c.output_tokens == 0 and c.outcome == "ok" and c.latency_ms >= 0 for c in calls)
        context = list(uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id)))
        assert {(c.resource_type, c.origin) for c in context} >= {("parties.party", "tool"), ("sales.quote", "tool"), ("catalogue.product", "tool")}

    conversation = meera.conversation()
    assert [t["role"] for t in conversation["turns"]] == ["user", "assistant"]
    assert conversation["turns"][1]["cards"][0]["kind"] == "quote_draft"


def test_agent_c_hinglish_demo_grammar(meera: Assistant, world: World) -> None:
    detail = meera.say("Nordhaus ka usual oak tray quote bana do")
    assert detail["run"]["status"] == "succeeded" and tool_calls(detail) == EXPECTED_TOOLS
    _assert_scenario_c_card(detail["cards"][0], world)


def _create_nordhaus_logistik(world: World) -> uuid.UUID:
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        detail = parties.create_party(uow, PartyCreate(
            legal_name="Nordhaus Logistik AG", display_name="Nordhaus Logistik AG", country_code="CH",
            default_currency="EUR", customer_type="standard", roles=["customer"],  # type: ignore[arg-type]
            owner_user_id=world.user_id(keys.USERS.MEERA),
        ))
        return detail.id


def test_agent_c_ambiguous_customer_asks_one_question(meera: Assistant, world: World) -> None:
    other = _create_nordhaus_logistik(world)
    first = meera.say(SCENARIO_C_TEXT)
    assert first["run"]["status"] == "succeeded" and tool_calls(first) == ["resolve_party", "ask_clarification"]
    cards = cards_of(first, "clarification")
    assert len(cards) == 1 and len(first["cards"]) == 1
    card = cards[0]
    assert card["slot"] == "party" and card["provider_label"] == "Demo"
    assert len(card["options"]) == 2
    values = {o["action"]["value"] for o in card["options"]}
    assert values == {str(world.ref("NORDHAUS")), str(other)}
    assert all(o["action"]["kind"] == "select_option" and o["action"]["slot"] == "party" for o in card["options"])
    assert not [q for q in fake_sales.STORE.quotes.values() if q.status == "draft"], "no draft before the choice"

    chosen = next(o for o in card["options"] if o["action"]["value"] == str(world.ref("NORDHAUS")))
    second = meera.say("", selected_option={"slot": "party", "value": chosen["action"]["value"]})
    assert second["run"]["status"] == "succeeded" and second["run"]["trigger"] == "clarification_answer"
    assert tool_calls(second) == ["find_usual_order", "resolve_price", "calculate_quote", "draft_quote"]
    _assert_scenario_c_card(second["cards"][0], world)


def test_agent_c_option_must_have_been_offered(meera: Assistant, world: World) -> None:
    _create_nordhaus_logistik(world)
    meera.say(SCENARIO_C_TEXT)
    response = meera.post_turn("", selected_option={"slot": "party", "value": str(uuid.uuid7())})
    assert response.status_code == 422 and response.json()["code"] == "option_not_offered"


def test_agent_c_followup_change_it_to_300_uses_object_context(meera: Assistant, world: World) -> None:
    first = meera.say(SCENARIO_C_TEXT)
    card = first["cards"][0]
    line_id, quote_id = card["lines"][0]["line_id"], card["quote_id"]
    context = {
        "schema_version": 1,
        "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
        "focus": {"type": "sales.quote_line", "id": line_id, "version": 1},
        "records": [{"type": "sales.quote", "id": quote_id, "version": 1, "role": "primary"}],
        "visible_items": [{"ref": "i1", "list_key": "quote_lines", "ordinal": 1, "type": "sales.quote_line", "id": line_id, "version": 1}],
        "selection": ["i1"],
    }
    second = meera.say("change it to 300", context=context)
    assert second["run"]["status"] == "succeeded", second
    assert tool_calls(second) == ["revise_draft_line"]
    revised = cards_of(second, "quote_draft")[0]
    assert revised["quote_id"] == quote_id and Decimal(revised["lines"][0]["quantity"]) == Decimal("300")
    assert Decimal(revised["lines"][0]["line_total"]) == Decimal("7200.00")
    assert Decimal(revised["totals"]["grand_total"]) == Decimal("7200.00")
    assert cards_of(second, "receipt")[0]["action"] == "revise_draft_line"
    step = next(s for s in second["steps"] if s["kind"] == "tool_call" and s["name"] == "revise_draft_line")
    assert step["input"]["quantity_source"] == "user_turn" and step["input"]["line_id"] == line_id
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(second["run"]["id"]))
        context_rows = list(uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id)))
        assert {(c.resource_type, str(c.resource_id), c.origin) for c in context_rows} >= {
            ("sales.quote_line", line_id, "screen"), ("sales.quote", quote_id, "screen"), ("sales.quote", quote_id, "card"),
        }


def test_agent_c_followup_preview_when_no_revise_tool(meera: Assistant, world: World) -> None:
    first = meera.say(SCENARIO_C_TEXT)
    from app.registry import get_registry

    registry = get_registry()
    registry.tools[:] = [t for t in registry.tools if t.name != "revise_draft_line"]
    second = meera.say("change it to 300")
    assert second["run"]["status"] == "succeeded", second
    assert tool_calls(second) == ["calculate_quote"]
    preview = cards_of(second, "quote_draft")[0]
    assert preview["preview_only"] is True and preview["quote_id"] == first["cards"][0]["quote_id"]
    assert Decimal(preview["totals"]["grand_total"]) == Decimal("7200.00")
    assert Decimal(preview["lines"][0]["quantity"]) == Decimal("300")
