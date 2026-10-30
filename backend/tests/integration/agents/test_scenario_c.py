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

from app.modules.agents import context as agents_context
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
    draft = fake_sales.quote_view(card["quote_id"])
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
    assert not fake_sales.drafts(), "no draft before the choice"

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


def _quote_screen(quote_id: str, line_id: str) -> dict:
    return {
        "schema_version": 1,
        "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
        "focus": {"type": "sales.quote_line", "id": line_id, "version": 1},
        "records": [{"type": "sales.quote", "id": quote_id, "version": 1, "role": "primary"}],
        "visible_items": [{"ref": "i1", "list_key": "quote_lines", "ordinal": 1, "type": "sales.quote_line", "id": line_id, "version": 1}],
        "selection": ["i1"],
    }


def test_agent_c_followup_change_it_to_300_uses_object_context(meera: Assistant, world: World) -> None:
    """Sales ships no revise tool: the engine recalculates (calculate_quote) and the change is applied through
    ``sales.service.update_line_command``; the card shows the persisted figures (300 x 24.0000 = EUR 7,200.00)."""
    first = meera.say(SCENARIO_C_TEXT)
    card = first["cards"][0]
    line_id, quote_id = card["lines"][0]["line_id"], card["quote_id"]
    drafted_version = fake_sales.quote_view(quote_id).version
    assert card["version"] == drafted_version
    second = meera.say("change it to 300", context=_quote_screen(quote_id, line_id))
    assert second["run"]["status"] == "succeeded", second
    assert tool_calls(second) == ["calculate_quote", "sales.update_line"]
    assert all(not s["is_error"] for s in second["steps"])
    calc = next(s for s in second["steps"] if s["kind"] == "tool_call" and s["name"] == "calculate_quote")
    assert calc["input"]["lines"][0]["quantity_source"] == "user_turn" and calc["input"]["lines"][0]["line_key"] == line_id
    revised = cards_of(second, "quote_draft")[0]
    assert revised["preview_only"] is False and revised["quote_id"] == quote_id and revised["version"] == drafted_version + 1
    assert Decimal(revised["lines"][0]["quantity"]) == Decimal("300")
    assert Decimal(revised["lines"][0]["line_total"]) == Decimal("7200.00")
    assert Decimal(revised["totals"]["grand_total"]) == Decimal("7200.00")
    assert cards_of(second, "receipt")[0]["action"] == "update_line"
    view = fake_sales.quote_view(quote_id)
    assert view.version == drafted_version + 1 and view.status == "draft"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(second["run"]["id"]))
        context_rows = list(uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id)))
        # the line comes in through the screen focus (sales.quote_line reader) and the card, the quote through both
        assert {(c.resource_type, str(c.resource_id), c.origin) for c in context_rows} >= {
            ("sales.quote", quote_id, "screen"), ("sales.quote", quote_id, "card"), ("sales.quote_line", line_id, "card"),
            ("sales.quote_line", line_id, "screen"),
        }


def test_agent_c_followup_is_a_preview_when_sales_service_is_absent(meera: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    first = meera.say(SCENARIO_C_TEXT)
    drafted_version = fake_sales.quote_view(first["cards"][0]["quote_id"]).version
    original = agents_context.optional_module
    monkeypatch.setattr(agents_context, "optional_module", lambda path: None if path.startswith("app.modules.sales") else original(path))
    second = meera.say("change it to 300")
    assert second["run"]["status"] == "succeeded", second
    assert tool_calls(second) == ["calculate_quote"]
    preview = cards_of(second, "quote_draft")[0]
    assert preview["preview_only"] is True and preview["quote_id"] == first["cards"][0]["quote_id"]
    assert Decimal(preview["totals"]["grand_total"]) == Decimal("7200.00")
    assert Decimal(preview["lines"][0]["quantity"]) == Decimal("300")
    assert fake_sales.quote_view(preview["quote_id"]).version == drafted_version, "nothing written"


def test_agent_c_followup_stale_card_keeps_the_preview(meera: Assistant, world: World) -> None:
    """The draft changed after the card was shown: the optimistic update is refused and nothing is overwritten."""
    first = meera.say(SCENARIO_C_TEXT)
    card = first["cards"][0]
    from app.modules.sales import service as sales
    from app.modules.sales.schemas import QuoteLineUpdate

    actor = world.actor(keys.USERS.MEERA).with_(idempotency_key=str(uuid.uuid7()))
    with UnitOfWork(actor) as uow:  # someone edits the draft in the workspace meanwhile
        sales.update_line_command(
            uow, uuid.UUID(card["quote_id"]), uuid.UUID(card["lines"][0]["line_id"]),
            QuoteLineUpdate(expected_version=card["version"], quantity="250"),
        )
    second = meera.say("change it to 300")
    assert second["run"]["status"] == "succeeded", second
    result = next(s for s in second["steps"] if s["kind"] == "tool_result" and s["name"] == "sales.update_line")
    assert result["is_error"] and result["error_code"] == "version_conflict"
    assert cards_of(second, "quote_draft")[0]["preview_only"] is True and not cards_of(second, "receipt")


