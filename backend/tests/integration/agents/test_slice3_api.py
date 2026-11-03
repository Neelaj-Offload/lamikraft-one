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
