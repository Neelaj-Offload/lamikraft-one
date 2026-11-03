"""Slice 3 runtime through the API: draft receipts and Undo (design section 9), the redacted trace (section 13),
the AI admin status/usage/verify endpoints (ai-routing.md sections 7-8) and run progress over SSE (ADR-050)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest

from app.modules.agents import streaming
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteLineUpdate
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import API, Assistant, cards_of
from tests.integration.catalogue.world import World
from tests.support import drain

pytestmark = pytest.mark.db
SCENARIO_C_TEXT = "Prepare Nordhaus's usual oak tray quote"


def _quote(world: World, quote_id: str) -> tuple[object, list[Decimal]]:
    """(deleted_at or the cancelled status, line quantities in line order) of a quote, read as the system actor."""
    from sqlalchemy import select

    from app.modules.sales.models import Quote, QuoteLine
    from app.platform.authz.context import ActorContext

    with UnitOfWork(ActorContext.system(world.company_id, reason="test")) as uow:
        quote = uow.session.get(Quote, uuid.UUID(quote_id))
        assert quote is not None
        lines = uow.session.scalars(select(QuoteLine).where(QuoteLine.quote_id == quote.id).order_by(QuoteLine.created_at)).all()
        gone = quote.deleted_at or (quote.status if quote.status == "cancelled" else None)
        return gone, [Decimal(line.quantity) for line in lines]


def _draft(meera: Assistant) -> tuple[dict, dict]:
    detail = meera.say(SCENARIO_C_TEXT)
    assert detail["run"]["status"] == "succeeded", detail
    receipts = cards_of(detail, "receipt")
    assert receipts and receipts[0]["undo"]["allowed"] is True and receipts[0]["undo"]["kind"] == "revert_draft"
    return detail, receipts[0]


# ---- receipts and Undo --------------------------------------------------------------------------------------------
def test_draft_receipt_undo_removes_the_agent_draft(meera: Assistant, world: World) -> None:
    detail, receipt = _draft(meera)
    quote_id = cards_of(detail, "quote_draft")[0]["quote_id"]
    rid = receipt["undo"]["receipt_id"]
    got = meera.client.get(f"{API}/receipts/{rid}", headers=meera.headers)
    assert got.status_code == 200 and got.json()["can_undo"] is True and got.json()["undo_kind"] == "revert_draft"
    assert got.json()["correlation_id"] == detail["run"]["correlation_id"]

    response = meera.client.post(f"{API}/receipts/{rid}/undo", headers=meera.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["receipt"]["status"] == "undone" and body["receipt"]["can_undo"] is False
    assert body["card"]["kind"] == "receipt" and body["card"]["undo"]["allowed"] is False
    assert _quote(world, quote_id)[0] is not None

    again = meera.client.post(f"{API}/receipts/{rid}/undo", headers=meera.headers)
    assert again.status_code == 409 and again.json()["code"] == "undo_not_available" and again.json()["reason"] == "undone"


def test_undo_refused_once_the_target_changed(meera: Assistant, world: World) -> None:
    detail, receipt = _draft(meera)
    card = cards_of(detail, "quote_draft")[0]
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        sales.update_line(uow, uuid.UUID(card["quote_id"]), uuid.UUID(card["lines"][0]["line_id"]),
                          QuoteLineUpdate(expected_version=card["version"], quantity=Decimal("250")))
    rid = receipt["undo"]["receipt_id"]
    assert meera.client.get(f"{API}/receipts/{rid}", headers=meera.headers).json()["can_undo"] is False
    response = meera.client.post(f"{API}/receipts/{rid}/undo", headers=meera.headers)
    assert response.status_code == 409 and response.json()["reason"] == "target_changed"
    assert _quote(world, card["quote_id"])[0] is None


def test_receipt_of_another_user_is_not_found(meera: Assistant) -> None:
    _, receipt = _draft(meera)
    rid = receipt["undo"]["receipt_id"]
    neha = {"x-test-persona": keys.USERS.NEHA}
    assert meera.client.get(f"{API}/receipts/{rid}", headers=neha).status_code == 404
    assert meera.client.post(f"{API}/receipts/{rid}/undo", headers=neha).status_code == 404


def test_line_change_receipt_restores_the_previous_quantity(meera: Assistant, world: World) -> None:
    detail, _ = _draft(meera)
    card = cards_of(detail, "quote_draft")[0]
    before = Decimal(card["lines"][0]["quantity"])
    follow = meera.say("change it to 300")
    receipts = [c for c in cards_of(follow, "receipt") if c["action"] == "update_line"]
    assert receipts and receipts[0]["undo"]["kind"] == "restore_line", follow["cards"]
    response = meera.client.post(f"{API}/receipts/{receipts[0]['undo']['receipt_id']}/undo", headers=meera.headers)
    assert response.status_code == 200, response.text
    assert _quote(world, card["quote_id"])[1] == [before]


# ---- trace --------------------------------------------------------------------------------------------------------
def test_trace_links_turn_run_steps_calls_receipt_and_events(meera: Assistant) -> None:
    detail, _ = _draft(meera)
    cid = detail["run"]["correlation_id"]
    assert cid and uuid.UUID(cid).version == 7
    response = meera.client.get(f"{API}/traces/{cid}", headers=meera.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access"] == "participant" and body["redacted"] is True and body["run_ids"] == [detail["run"]["id"]]
    kinds = {e["kind"] for e in body["entries"]}
    assert {"turn", "run", "step", "ai_call", "receipt", "event"} <= kinds, kinds
    events = {e["name"] for e in body["entries"] if e["kind"] == "event"}
    assert "agents.run.completed" in events and any(n.startswith("sales.quote") for n in events), events
    raw = json.dumps(body)
    assert "Nordhaus" not in raw and "oak tray" not in raw.lower(), "turn text and tool payloads are redacted"


def test_trace_hidden_from_others_and_visible_to_auditors(meera: Assistant) -> None:
    detail, _ = _draft(meera)
    cid = detail["run"]["correlation_id"]
    assert meera.client.get(f"{API}/traces/{cid}", headers={"x-test-persona": keys.USERS.NEHA}).status_code == 404
    admin = meera.client.get(f"{API}/traces/{cid}", headers={"x-test-persona": keys.USERS.PRIYA})
    assert admin.status_code == 200 and admin.json()["access"] == "auditor"
    assert meera.client.get(f"{API}/traces/{uuid.uuid7()}", headers=meera.headers).status_code == 404


# ---- AI admin -----------------------------------------------------------------------------------------------------
def test_ai_status_usage_and_verify_in_demo(meera: Assistant) -> None:
    meera.say(SCENARIO_C_TEXT)
    admin = {"x-test-persona": keys.USERS.PRIYA}
    assert meera.client.get(f"{API}/admin/ai/status", headers=meera.headers).status_code == 403
    status = meera.client.get(f"{API}/admin/ai/status", headers=admin)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["provider"]["state"] == "demo" and body["provider"]["label"] == "Demo"
    assert body["provider"]["circuit"]["state"] == "closed" and body["models"]["orchestrator"]
    assert body["quotas"]["orchestrator_runs_per_user"] == 150 and "DPDP" in body["dpdp_text"]
    assert body["can_manage_routing"] is True

    usage = meera.client.get(f"{API}/admin/ai/usage", params={"days": 7}, headers=admin)
    assert usage.status_code == 200, usage.text
    data = usage.json()
    assert data["cost_is_estimate"] is True and data["price_currency"] == "USD"
    orchestrate = next(w for w in data["by_workflow"] if w["workflow"] == "orchestrate")
    assert orchestrate["calls"] >= 1 and orchestrate["runs"] == 1 and orchestrate["errors"] == 0
    assert orchestrate["p50_latency_ms"] is not None and Decimal(orchestrate["estimated_cost"]) == 0
    assert data["totals"]["calls"] == sum(w["calls"] for w in data["by_workflow"])

    verified = meera.client.post(f"{API}/admin/ai/verify", headers=admin)
    assert verified.status_code == 200, verified.text
    assert verified.json()["mode"] == "demo" and verified.json()["state"] == "connected"


# ---- SSE (ADR-050) ------------------------------------------------------------------------------------------------
def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        name = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        if name:
            out.append((name, json.loads(data)))
    return out


def test_sse_stream_of_a_finished_run(meera: Assistant) -> None:
    detail = meera.say(SCENARIO_C_TEXT)
    response = meera.client.get(f"{API}/agents/runs/{detail['run']['id']}/events", headers=meera.headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    events = _events(response.text)
    assert [name for name, _ in events] == ["done"]
    assert events[0][1]["done"] is True and events[0][1]["cards"][0]["kind"] == "quote_draft"
    resumed = meera.client.get(f"{API}/agents/runs/{detail['run']['id']}/events",
                               headers={**meera.headers, "Last-Event-ID": str(detail["last_seq"])})
    assert _events(resumed.text)[0][1]["steps"] == []
    other = meera.client.get(f"{API}/agents/runs/{detail['run']['id']}/events", headers={"x-test-persona": keys.USERS.NEHA})
    assert other.status_code == 404


def test_sse_streams_progress_while_the_worker_runs(meera: Assistant, world: World) -> None:
    accepted = meera.post_turn(SCENARIO_C_TEXT).json()
    ticks: list[float] = []
    stream = streaming.run_events(world.actor(keys.USERS.MEERA), uuid.UUID(accepted["run_id"]),
                                  sleep=lambda s: (ticks.append(s), drain()))
    events = _events("".join(stream))
    names = [name for name, _ in events]
    assert names[0] == "run" and names[-1] == "done" and ticks, names
    assert events[0][1]["run"]["status"] == "queued" and events[-1][1]["run"]["status"] == "succeeded"
