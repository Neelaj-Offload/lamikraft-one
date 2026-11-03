"""Taint in live mode (ai-routing.md section 6): once a run reads external content, the next provider request no
longer advertises external-send tools, the external text reaches the model only inside a tool result marked
untrusted, a hidden tool call is an error step (no service call), and every card requires confirmation."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tests.integration.agents.conftest import Assistant, tool_calls
from tests.integration.agents.live_fake import FakeClaude, is_router, live_mode, message, text, tool_results, tool_use
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _router() -> dict[str, Any]:
    payload = {"request_type": "data_or_action", "domains": ["sales"], "think_harder": False,
               "slots": {k: None for k in ("customer", "product", "quantity", "quantity_source", "unit", "currency", "date")}}
    return message([text(json.dumps(payload))], model="claude-haiku-5-5")


def test_external_content_hides_send_tools(meera: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    nordhaus = str(world.ref("NORDHAUS"))
    seen_tools: list[set[str]] = []

    def script(body: dict[str, Any]) -> dict[str, Any]:
        if is_router(body):
            return _router()
        seen_tools.append({t["name"] for t in body.get("tools", [])})
        results = tool_results(body)
        if "tu_party" not in results:
            return message([tool_use("tu_party", "resolve_party", {"query": "Nordhaus"})], stop_reason="tool_use")
        if "tu_note" not in results:
            assert nordhaus in _UUID.findall(results["tu_party"])
            return message([tool_use("tu_note", "fetch_external_note", {"party_id": nordhaus})], stop_reason="tool_use")
        if "tu_send" not in results:
            return message([tool_use("tu_send", "send_quote", {"quote_id": nordhaus})], stop_reason="tool_use")
        return message([text("The customer asked for 500 trays.")])

    fake = FakeClaude(script)
    with live_mode(monkeypatch, fake):
        detail = meera.say("check what Nordhaus wrote to us and reply")
    assert detail["run"]["tainted"] is True
    assert tool_calls(detail) == ["resolve_party", "fetch_external_note", "send_quote"]
    assert "send_quote" in seen_tools[0] and "send_quote" in seen_tools[1]
    assert "send_quote" not in seen_tools[2] and "send_quote" not in seen_tools[3], "hidden once tainted"
    send = next(s for s in detail["steps"] if s["kind"] == "tool_result" and s["name"] == "send_quote")
    assert send["is_error"] and send["error_code"] == "tool_hidden_tainted"
    note = json.loads(tool_results(fake.bodies[3])["tu_note"])["output"]
    assert note["untrusted"] is True and note["source"] == "customer_message"
    system_text = json.dumps(fake.bodies[3]["system"])
    assert "Ignore previous instructions" not in system_text, "external text never enters the system prompt"
    assert all(c["tainted"] and c.get("requires_confirmation", True) for c in detail["cards"])
    assert "500" not in detail["text"]
