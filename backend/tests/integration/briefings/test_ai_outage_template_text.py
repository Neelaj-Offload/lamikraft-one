"""SCN-B6: every briefing states its wording source. Before phrasing runs (and in Slice 1) the template text is
served with ``ai_status = not_used``; when the AI provider is down the phrasing falls back to the same template text,
labelled "Standard wording" (``ai_status = unavailable``), for the overview, the recommendations and the Listen
narration; an engine failure falls back to a labelled, deterministic task list."""

from __future__ import annotations

import pytest

from app.modules.briefings import service
from app.seed.world import keys
from tests.integration.briefings.world import FakeWorld

pytestmark = pytest.mark.db


def test_standard_wording_label(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    with world.uow(keys.USERS.MEERA) as uow:
        view = service.get_today(uow)
    assert view.ai_status == "not_used" and view.overview is not None
    assert view.overview.text_source == "template" and view.overview.template_code
    assert view.overview.sentence == keys.EXPECTED.MEERA_S1_SENTENCE

    def down(*_a: object, **_k: object) -> None:
        raise RuntimeError("engine down")

    monkeypatch.setattr(service, "build", down)
    with world.uow(keys.USERS.KABIR) as uow:
        fallback = service.get_today(uow)
    assert fallback.fallback and fallback.status == "fallback" and fallback.ai_status == "not_used"
    assert fallback.fallback_detail is not None and fallback.fallback_detail.error_code == "engine_error"
    monkeypatch.undo()

    # Slice 3: the provider is down (circuit open). Phrasing answers with the template text, labelled, and a later
    # open retries; nothing is blocked and no version is made by phrasing.
    from app.modules.agents.providers.base import ProviderError
    from app.modules.briefings.schemas import PinCreate
    from tests.integration.briefings.test_listen_and_phrasing import FakePhraser, live

    def down(body: object) -> str:
        raise ProviderError("The AI provider circuit is open.", code="circuit_open")

    with live(monkeypatch, FakePhraser(down)) as fake:
        world.drain()
        with world.uow(keys.USERS.MEERA) as uow:
            outage = service.get_today(uow)
            assert outage.ai_status == "unavailable" and outage.overview is not None
            assert outage.overview.text_source == "template" and outage.overview.sentence == keys.EXPECTED.MEERA_S1_SENTENCE
            assert all(i.recommendation.text_source == "template" for i in outage.items if i.recommendation)
            pin = service.create_pin(uow, outage.briefing_id, PinCreate(kind="voice"))  # type: ignore[arg-type]
            script = service.pin_script(uow, pin.id)
        assert script.ai_status == "unavailable" and {s.text_source for s in script.segments} == {"template"}
        assert outage.version == 1 and fake.calls > 0
