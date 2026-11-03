"""The phrasing service with the database (ai-routing.md section 7): fact-hash cache (unchanged facts never
regenerate), invalid model output falls back to "Standard wording" and is cached, outages are not cached, and the
Message Batches path returns results keyed by custom id with failed items on template text."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.agents import phrasing
from app.modules.agents.models import AiCallLog, PhrasingCache
from app.modules.agents.providers.base import ModelResponse, ProviderError, TextBlock
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.catalogue.world import World

pytestmark = pytest.mark.db


def _request(total: str = "EUR 5,760.00") -> phrasing.PhraseRequest:
    return phrasing.PhraseRequest(
        template_code="briefing.quote_expiring", template="Quote {{a1}} for {{a2}} ({{a3}}) expires soon.",
        facts=(phrasing.Fact("a1", "LK-QT-2026-0009", "text"), phrasing.Fact("a2", "Nordhaus Interiors", "name"),
               phrasing.Fact("a3", total, "money", currency="EUR")),
    )


class Scripted:
    name = "anthropic"

    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.text, self.error, self.calls = text, error, 0

    def generate(self, request: Any) -> ModelResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ModelResponse(provider="anthropic", model="claude-haiku-5-5", stop_reason="end_turn",
                             content=(TextBlock('{"text": "%s"}' % self.text),))


def _count(uow: UnitOfWork, model: Any) -> int:
    return int(uow.session.scalar(select(func.count()).select_from(model).where(model.company_id == uow.actor.company_id)))


def test_cache_validation_fallback_and_outage(world: World) -> None:
    actor = world.actor(keys.USERS.MEERA)
    good = Scripted("{{a2}}: quote {{a1}} ({{a3}}) is about to expire.")
    with UnitOfWork(actor) as uow:
        first = phrasing.phrase(uow, _request(), provider=good)
        again = phrasing.phrase(uow, _request(), provider=good)
        assert first.source == "model" and first.text == "Nordhaus Interiors: quote LK-QT-2026-0009 (EUR 5,760.00) is about to expire."
        assert again.cached and again.text == first.text and good.calls == 1
        assert _count(uow, PhrasingCache) == 1 and _count(uow, AiCallLog) == 1

        invented = Scripted("Quote {{a1}} for {{a2}} is worth 6000 euros and expires Friday.")
        bad = phrasing.phrase(uow, _request("EUR 6,000.00"), provider=invented)
        assert bad.source == "template" and bad.label == "Standard wording"
        assert bad.text == "Quote LK-QT-2026-0009 for Nordhaus Interiors (EUR 6,000.00) expires soon."
        assert "numeral_not_from_facts" in bad.failures and "new_date" in bad.failures

        down = Scripted(error=ProviderError("down", code="unreachable"))
        out = phrasing.phrase(uow, _request("EUR 7,000.00"), provider=down)
        assert out.source == "template" and out.failures == ("unreachable",)
        assert not phrasing.phrase(uow, _request("EUR 7,000.00"), provider=good).cached, "outages are not cached"


def test_demo_batch_keyed_by_custom_id(world: World) -> None:
    actor = world.actor(keys.USERS.MEERA)
    items = {"item-1": _request(), "item-2": _request("EUR 1,200.00")}
    with UnitOfWork(actor) as uow:
        phrasing.phrase(uow, items["item-1"])  # cached before the batch
        batch = phrasing.submit_batch(uow, items)
        assert set(batch.results) == {"item-1"} and set(batch.pending) == {"item-2"} and batch.batch_id
        results = phrasing.collect_batch(uow, batch, items)
    assert results is not None and set(results) == {"item-1", "item-2"}
    assert results["item-1"].cached and results["item-2"].source == "model"
    assert results["item-2"].text == "Quote LK-QT-2026-0009 for Nordhaus Interiors (EUR 1,200.00) expires soon."
