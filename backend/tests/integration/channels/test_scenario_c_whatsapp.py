"""Scenario C over the WhatsApp demo (design §18 step 7): Meera links her number, asks for Nordhaus's usual oak tray
quote by WhatsApp text (and by voice note), the same agents turn runs as on the web, and the reply carries the
card's figures with "Review quote" and "Open workspace" buttons. "Review quote" answers with a 15-minute review
link that only Meera can resolve, and it redirects to the canonical quote screen."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.modules.agents.models import Run, Turn
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World
from tests.integration.channels.conftest import API, WhatsApp

pytestmark = pytest.mark.db

SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"


def _assert_draft_reply(reply: str) -> None:
    assert reply.startswith("Demo: Draft ready (LK-QT-2026-0009).")
    assert "EUR 24.00 each." in reply and "Total EUR 5,760.00." in reply and reply.endswith("Status: draft, not sent.")


def test_c_whatsapp_text_drafts_the_quote_and_review_link_redirects(
    wa: WhatsApp, world: World, sales_tools: object, client: TestClient,
) -> None:
    identity = wa.enrol(keys.USERS.MEERA)
    wa.text(wa.wa_id(keys.USERS.MEERA), SCENARIO_C_TEXT)
    messages = wa.messages(identity.id)
    inbound = next(m for m in messages if m["direction"] == "inbound" and m["body"] == SCENARIO_C_TEXT)
    assert inbound["input_mode"] == "wa_text" and inbound["run_id"] is not None
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, inbound["run_id"])
        assert run is not None and run.status == "succeeded" and run.channel == "whatsapp" and run.user_id == world.user_id(keys.USERS.MEERA)
        # the message's input mode reaches the agents turn (Slice-3 stage-1 merge, migration 0018)
        turn = uow.session.get(Turn, run.turn_id)
        assert turn is not None and turn.input_mode == "wa_text"
    reply = next(m for m in wa.messages(identity.id, "outbound") if m["run_id"] == inbound["run_id"])
    _assert_draft_reply(reply["body"])
    assert reply["simulated"] and reply["status"] == "read"
    titles = [b["title"] for b in reply["buttons"]]
    assert titles == ["Review quote", "Open workspace"]

    review_button = reply["buttons"][0]["id"]
    wa.button(wa.wa_id(keys.USERS.MEERA), review_button)
    link_reply = wa.replies(identity.id)[-1]
    assert "/r/" in link_reply and "15 minutes" in link_reply
    token = link_reply.rsplit("/r/", 1)[1].strip()

    other = client.post(f"{API}/review-links/{token}/resolve", json={}, headers={"x-test-persona": keys.USERS.NEHA})
    assert other.status_code == 403 and other.json()["code"] == "review_link_wrong_user"
    resolved = client.post(f"{API}/review-links/{token}/resolve", json={}, headers={"x-test-persona": keys.USERS.MEERA})
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["redirect_path"].startswith("/sales/quotes/") and body["target_type"] == "sales.quote" and body["purpose"] == "view"

    # the same button cannot be used twice
    wa.button(wa.wa_id(keys.USERS.MEERA), review_button)
    assert wa.replies(identity.id)[-1] == "Demo: That button was already used."


def test_c_whatsapp_voice_note_echoes_the_transcript_and_drafts(wa: WhatsApp, world: World, sales_tools: object, client: TestClient) -> None:
    identity = wa.enrol(keys.USERS.MEERA)
    response = client.post(f"{API}/channels/whatsapp/demo/inbound", json={"audio_fixture": "oak_tray_quote"}, headers={"x-test-persona": keys.USERS.MEERA})
    assert response.status_code == 202, response.text
    from tests.support import drain

    drain()
    replies = wa.replies(identity.id)
    assert any(r == f"Demo: I heard (Demo transcript): “{SCENARIO_C_TEXT}”" for r in replies), replies
    _assert_draft_reply(replies[-1])
    voice = next(m for m in wa.messages(identity.id, "inbound") if m["type"] == "audio")
    assert voice["input_mode"] == "wa_voice" and voice["body"] == SCENARIO_C_TEXT
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, voice["run_id"])
        assert run is not None
        turn = uow.session.get(Turn, run.turn_id)
        assert turn is not None and turn.input_mode == "wa_voice"


def test_c_simulator_thread_shows_the_conversation_with_the_demo_label(wa: WhatsApp, world: World, sales_tools: object, client: TestClient) -> None:
    headers = {"x-test-persona": keys.USERS.MEERA}
    enrol = client.post(f"{API}/channels/whatsapp/enrolments", json={}, headers=headers)
    assert enrol.status_code == 201, enrol.text
    code = enrol.json()["code"]
    assert enrol.json()["wa_me_link"].endswith(f"?text=LINK%20{code}") and enrol.json()["mode"] == "demo"
    assert client.post(f"{API}/channels/whatsapp/demo/inbound", json={"text": f"LINK {code}"}, headers=headers).status_code == 202
    from tests.support import drain

    drain()
    assert client.post(f"{API}/channels/whatsapp/demo/inbound", json={"text": SCENARIO_C_TEXT}, headers=headers).status_code == 202
    drain()
    thread = client.get(f"{API}/channels/whatsapp/demo/thread", headers=headers)
    assert thread.status_code == 200, thread.text
    data = thread.json()
    assert data["label_text"] == "Demo — not connected" and data["identity"]["status"] == "active"
    bodies = [m["body"] for m in data["messages"]]
    assert "LINK ••••••••" in bodies and SCENARIO_C_TEXT in bodies
    assert bodies[-1].startswith("Demo: Draft ready") and data["messages"][-1]["simulated"] is True
    assert data["messages"][-1]["provider_message_id"] is None  # provider ids are admin-only
