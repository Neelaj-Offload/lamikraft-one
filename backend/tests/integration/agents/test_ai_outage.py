"""Graceful AI outage (ai-routing.md sections 1.4 and 5.1): provider failures end runs with an ErrorCard and direct
controls; after 5 failures in 2 minutes the circuit opens and no request is sent; the deterministic grammar and
the briefing phrasing ("Standard wording") keep working; Settings → AI shows the provider failing."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from app.modules.agents import phrasing
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import API, Assistant, cards_of
from tests.integration.agents.live_fake import FakeClaude, live_mode
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"


def outage(body: dict[str, Any]) -> httpx2.Response:
    return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "overloaded"}},
                           headers={"request-id": "req_outage"})


def test_circuit_breaker_and_briefing_fallback(meera: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClaude(outage)
    with live_mode(monkeypatch, fake) as breaker:
        for _ in range(5):
            failed = meera.say(SCENARIO_C_TEXT)
            assert failed["run"]["status"] == "failed"
            card = cards_of(failed, "error")[0]
            assert card["message"].startswith("Assistant unavailable") and card["direct_controls"]
        assert breaker.state == "open" and len(fake.bodies) == 5

        blocked = meera.say(SCENARIO_C_TEXT)
        assert cards_of(blocked, "error")[0]["code"] == "circuit_open" and len(fake.bodies) == 5, "no request sent"

        command = meera.say("go to quotes")
        assert command["run"]["status"] == "succeeded" and cards_of(command, "record_link")[0]["path"] == "/sales/quotes"

        request = phrasing.PhraseRequest(
            template_code="briefing.quote_expiring", template="Quote {{a1}} expires soon.",
            facts=(phrasing.Fact("a1", "LK-QT-2026-0009", "text"),),
        )
        with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
            result = phrasing.phrase(uow, request)
        assert result.source == "template" and result.label == phrasing.STANDARD_WORDING
        assert result.text == "Quote LK-QT-2026-0009 expires soon." and result.failures == ("circuit_open",)

        status = meera.client.get(f"{API}/admin/ai/status", headers={"x-test-persona": keys.USERS.PRIYA}).json()
        assert status["provider"]["mode"] == "live" and status["provider"]["state"] == "failing"
        assert status["provider"]["circuit"]["state"] == "open" and status["provider"]["circuit"]["recent_failures"] >= 5
        usage = meera.client.get(f"{API}/admin/ai/usage", headers={"x-test-persona": keys.USERS.PRIYA}).json()
        assert any(f["request_id"] == "req_outage" for f in usage["failures"])
        assert usage["totals"]["errors"] >= 5
