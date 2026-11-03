"""Slice 3: LLM phrasing of the briefing (validator, "Standard wording", fact-hash cache, pre-shift batch) and the
"Listen to my day" narration over a voice pin (stable order, phrased bodies, read-back values, voice ack)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select

from app.modules.agents import phrasing as agents_phrasing
from app.modules.agents.models import AiCallLog
from app.modules.agents.providers.base import ModelResponse, TextBlock
from app.modules.briefings import service
from app.modules.briefings.models import Briefing, VersionText
from app.modules.briefings.schemas import PinCreate, PinUpdate
from app.seed.world import keys
from tests.integration.briefings.test_versions_and_actions import new_message, today
from tests.integration.briefings.world import FakeWorld, d0, ist

pytestmark = pytest.mark.db


class FakePhraser:
    """A provider with the phrasing interface: ``answer(body) -> text`` (the body the model would see), or raises."""

    name = "anthropic"  # the call log only accepts known providers

    def __init__(self, answer: Callable[[dict[str, Any]], str]) -> None:
        self.answer = answer
        self.calls = 0
        self.bodies: list[dict[str, Any]] = []
        self.batches: dict[str, dict[str, Any]] = {}
        self.batch_ready = True

    def generate(self, request: Any) -> ModelResponse:
        self.calls += 1
        body = json.loads(request.messages[-1].content[0].text)
        self.bodies.append(body)
        return ModelResponse(provider="anthropic", model="claude-haiku-test", stop_reason="end_turn",
                             content=(TextBlock(json.dumps({"text": self.answer(body)})),))

    def submit_batch(self, requests: dict[str, Any]) -> str:
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches[batch_id] = {cid: self.generate(r) for cid, r in requests.items()}
        return batch_id

    def collect_batch(self, batch_id: str, *, wait_seconds: float = 0.0) -> dict[str, Any] | None:  # noqa: ARG002
        return self.batches.get(batch_id) if self.batch_ready else None


def reword(body: dict[str, Any]) -> str:
    """A well-behaved model: keeps every placeholder, changes the words around them."""
    return "In short: " + body["template"][0].lower() + body["template"][1:]


@contextmanager
def live(monkeypatch: pytest.MonkeyPatch, phraser: Any) -> Iterator[Any]:
    from app.modules.agents import providers

    monkeypatch.setattr(providers, "ai_mode", lambda: "live")
    monkeypatch.setattr(agents_phrasing, "_phraser", lambda: phraser)
    yield phraser


def texts(world: FakeWorld, briefing_id: Any) -> list[VersionText]:
    with world.uow() as uow:
        rows = list(uow.session.scalars(select(VersionText).where(VersionText.briefing_id == briefing_id)))
        for r in rows:
            uow.session.expunge(r)
        return rows


def phrase_calls(world: FakeWorld) -> int:
    with world.uow() as uow:
        return int(uow.session.scalar(select(func.count()).select_from(AiCallLog).where(AiCallLog.task_class == "phrasing")) or 0)


# ---- phrasing ---------------------------------------------------------------------------------------------------------
def test_demo_phrasing_runs_the_validated_path_and_is_labelled_demo(world: FakeWorld) -> None:
    first = today(world, keys.USERS.MEERA)
    assert first.ai_status == "not_used" and first.overview is not None  # deterministic text first, phrasing queued
    world.drain()
    view = today(world, keys.USERS.MEERA)
    assert view.ai_status == "demo" and view.overview is not None
    assert view.overview.sentence == view.overview.standard_sentence == keys.EXPECTED.MEERA_S1_SENTENCE
    assert view.overview.text_source == "llm"  # the Demo phraser's output passed the validator
    recs = [i.recommendation for i in view.items if i.recommendation is not None]
    assert recs and all(r.text and r.text_source == "llm" for r in recs)
    (row,) = texts(world, view.briefing_id)
    assert row.status == "ready" and row.ai_status == "demo" and set(row.narration) == {str(i.issue_id) for i in view.items}


def test_live_phrasing_rewords_without_changing_facts_and_caches_by_fact_hash(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    logged_before = phrase_calls(world)
    with live(monkeypatch, FakePhraser(reword)) as fake:
        v1 = today(world, keys.USERS.MEERA)
        world.drain()
        view = today(world, keys.USERS.MEERA)
        assert view.ai_status == "ok" and view.overview is not None and view.overview.text_source == "llm"
        assert view.overview.sentence == "In short: two customer replies need attention and one quote expires today."
        assert view.overview.standard_sentence == keys.EXPECTED.MEERA_S1_SENTENCE
        # the model never saw a count or an amount, only placeholders with labels
        assert all("value" not in f for b in fake.bodies for f in b["facts"] if f["kind"] in ("count", "money", "date"))
        calls_v1 = fake.calls
        assert calls_v1 == phrase_calls(world) - logged_before > 0  # every call is in the AI usage store
        # a new message makes version 2; only the texts whose facts changed are phrased again
        new_message(world, "MSG_MAISON_NEW", "MAISON", d0(9, 10))
        world.drain()
        v2 = today(world, keys.USERS.MEERA)
        assert v2.version == 2 and v2.briefing_id == v1.briefing_id and v2.ai_status == "ok"
        new_texts = fake.calls - calls_v1
        assert 0 < new_texts < calls_v1  # unchanged items hit the fact-hash cache
        assert len(texts(world, v1.briefing_id)) == 2  # one text row per version; phrasing made no version


def test_validator_rejection_shows_standard_wording(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    def invents(body: dict[str, Any]) -> str:
        return "You have 7 things to do in Mumbai."

    with live(monkeypatch, FakePhraser(invents)):
        today(world, keys.USERS.MEERA)
        world.drain()
        view = today(world, keys.USERS.MEERA)
    assert view.ai_status == "unavailable" and view.overview is not None
    assert view.overview.text_source == "template" and view.overview.sentence == keys.EXPECTED.MEERA_S1_SENTENCE
    assert all(i.recommendation.text_source == "template" for i in view.items if i.recommendation)


def test_pre_shift_batch_phrases_a_precomputed_briefing(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.briefings.jobs import precompute_company

    fake = FakePhraser(reword)
    fake.batch_ready = False
    with live(monkeypatch, fake):
        world.at(ist(2026, 10, 13, 9, 5))
        with world.uow() as uow:
            assert precompute_company(uow) == 8
        world.drain()
        with world.uow() as uow:
            pre = uow.session.scalars(select(Briefing).where(Briefing.user_id == world.refs[keys.USERS.MEERA],
                                                             Briefing.work_date == date(2026, 10, 13))).one()
            pre_id = pre.id
        (pending,) = texts(world, pre_id)
        assert pending.status == "pending" and pending.batch_id
        submitted = fake.calls
        fake.batch_ready = True
        world.at(ist(2026, 10, 13, 9, 7))  # the collect job is due a minute later
        world.drain()
        (done,) = texts(world, pre_id)
        assert done.status == "ready" and done.ai_status == "ok" and done.batch_id is None
        assert fake.calls == submitted  # collecting costs no new calls
        world.at(ist(2026, 10, 13, 9, 40))
        opened = today(world, keys.USERS.MEERA)
        assert opened.trigger == "precompute" and opened.ai_status == "ok" and opened.overview is not None
        assert opened.overview.sentence.startswith("In short: ")


# ---- Listen to my day -------------------------------------------------------------------------------------------------
def test_listen_script_keeps_the_pinned_order_and_reads_back_values(world: FakeWorld) -> None:
    v1 = today(world, keys.USERS.MEERA)
    world.drain()
    with world.uow(keys.USERS.MEERA) as uow:
        pin = service.create_pin(uow, v1.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
        script = service.pin_script(uow, pin.id)
    assert script.ai_status == "demo" and script.pinned_version == 1
    assert [s.kind for s in script.segments] == ["intro"] + ["item"] * len(pin.ordinal_map) + ["outro"]
    intro = script.segments[0]
    assert intro.lead.startswith("Good morning") and intro.text == keys.EXPECTED.MEERA_S1_SENTENCE
    items = script.segments[1:-1]
    assert [str(s.issue_id) for s in items] == [e["issue_id"] for e in pin.ordinal_map]
    assert items[1].lead.startswith("Second. ") and all(s.readback and s.readback[0] for s in items)
    assert all(s.text_source == "llm" and s.text.count(".") <= 3 for s in items)
    # a source change writes version 2 while the pin is active: the spoken list does not move
    new_message(world, "MSG_MAISON_NEW", "MAISON", d0(9, 10))
    world.drain()
    with world.uow(keys.USERS.MEERA) as uow:
        again = service.pin_script(uow, pin.id)
        assert [s.issue_id for s in again.segments] == [s.issue_id for s in script.segments]
        service.update_pin(uow, pin.id, PinUpdate(state="paused", position=2))
        service.update_pin(uow, pin.id, PinUpdate(state="active"))
        done = service.update_pin(uow, pin.id, PinUpdate(state="completed", position=len(script.segments) - 1))
    assert done.state == "completed"
    after = today(world, keys.USERS.MEERA)
    assert after.pin is None and after.version == 2 and after.last_ack is not None
    assert (after.last_ack.method, after.last_ack.version) == ("voice", 1)  # completion acknowledges what was heard


def test_listen_after_an_outage_speaks_the_template_wording(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.agents.providers.base import ProviderError

    def down(body: dict[str, Any]) -> str:
        raise ProviderError("The AI provider circuit is open.", code="circuit_open")

    with live(monkeypatch, FakePhraser(down)):
        v1 = today(world, keys.USERS.MEERA)
        world.drain()
        with world.uow(keys.USERS.MEERA) as uow:
            pin = service.create_pin(uow, v1.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
            script = service.pin_script(uow, pin.id)
    assert script.ai_status == "unavailable"
    assert all(s.text_source == "template" for s in script.segments)
    assert script.segments[1].text.endswith(".") and script.segments[0].text == keys.EXPECTED.MEERA_S1_SENTENCE


def test_rollover_ends_yesterdays_listening_and_phrases_the_new_day(world: FakeWorld) -> None:
    """Midnight/shift boundary: a pin from Monday's briefing does not hold Tuesday's list after the 04:00 rollover."""
    world.at(ist(2026, 10, 13, 3, 50))  # still Monday's work date (rollover 04:00)
    monday = today(world, keys.USERS.MEERA)
    with world.uow(keys.USERS.MEERA) as uow:
        service.create_pin(uow, monday.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
    world.at(ist(2026, 10, 13, 4, 5))
    tuesday = today(world, keys.USERS.MEERA)
    assert tuesday.work_date == date(2026, 10, 13) and tuesday.briefing_id != monday.briefing_id and tuesday.pin is None
    world.drain()
    assert today(world, keys.USERS.MEERA).ai_status == "demo"
