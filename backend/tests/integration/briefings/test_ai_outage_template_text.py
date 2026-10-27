"""SCN-B6 (Slice-1 part): no model is involved; every briefing states its wording source (template) and
``ai_status = not_used``, and an engine failure falls back to a labelled, deterministic task list."""

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
