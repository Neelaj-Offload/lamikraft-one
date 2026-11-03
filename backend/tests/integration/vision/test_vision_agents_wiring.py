"""Vision meets the agents runtime (Slice-3 stage-2 merge; voice-vision report section 4, integrator requests 2-3):
the router sends a screen question to the vision service when a masked screenshot is attached, a confirmed
extraction reaches a run only as untrusted data and taints it, live capture needs the recorded DPDP approval, the
routing table supplies the vision model and quota, and vision call-log rows carry their owner and trace id. Also: the
voice module is the WhatsApp channel's transcriber."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.modules.agents.models import AiCallLog, Run, Turn
from app.modules.agents.providers.demo_vision import DEMO_DELIVERY_NOTE
from app.modules.agents.routing import AI_ROUTING_KEY
from app.modules.vision import service as vision
from app.modules.vision.schemas import ScreenCaptureSetting
from app.platform.authz.context import ActorContext
from app.platform.org import service as org
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import Assistant
from tests.integration.catalogue.world import World, upload_file
from tests.support import drain

pytestmark = pytest.mark.db
API = "/api/v1"


def _webp() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 500), "white").save(buffer, "WEBP", quality=70)
    return buffer.getvalue()


def _capture(meera: Assistant, conversation_id: str) -> dict[str, Any]:
    response = meera.client.post(f"{API}/vision/screen-captures", params={"conversation_id": conversation_id},
                                 headers=meera.headers, files={"file": ("screen.webp", _webp(), "image/webp")})
    assert response.status_code == 201, response.text
    return response.json()


def _quote_context(world: World) -> dict[str, Any]:
    quote_id = str(world.ref("Q_NORDHAUS_DRAFT"))  # LK-QT-2026-0008
    return {"schema_version": 1, "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
            "focus": {"type": "sales.quote", "id": quote_id}}


def _set_routing(world: World, **changes: Any) -> None:
    with UnitOfWork(ActorContext.system(world.company_id, reason="test").with_(idempotency_key=None)) as uow:
        current = org.get_setting(uow, AI_ROUTING_KEY)
        value: dict[str, Any] = dict(current.value)
        for key, part in changes.items():
            value[key] = {**value.get(key, {}), **part}
        org.update_setting(uow, AI_ROUTING_KEY, value=value, expected_version=current.version, change_reason="test")


def _run_steps(detail: dict[str, Any]) -> list[str]:
    return [step["name"] for step in detail["steps"]]


@pytest.fixture
def vision_world(meera: Assistant, media_storage: object) -> Assistant:
    return meera


def test_router_sends_a_screen_question_with_an_attached_screenshot_to_vision(vision_world: Assistant, world: World) -> None:
    conversation = vision_world.start()["id"]
    _capture(vision_world, conversation)
    accepted = vision_world.post_turn("What is on my screen?", context=_quote_context(world))
    assert accepted.status_code == 202, accepted.text
    drain()
    detail = vision_world.poll(accepted.json()["run_id"])
    assert detail["run"]["status"] == "succeeded", detail
    assert "vision" in _run_steps(detail), [step["output"] for step in detail["steps"]]
    assert "LK-QT-2026-0008" in (detail["text"] or "")
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(accepted.json()["run_id"]))
        assert run is not None and run.tainted is True, "a screenshot answer is always tainted"


def test_a_screen_question_without_a_screenshot_stays_on_the_normal_path(vision_world: Assistant, world: World) -> None:
    vision_world.start()
    accepted = vision_world.post_turn("What is on my screen?", context=_quote_context(world))
    assert accepted.status_code == 202, accepted.text
    drain()
    detail = vision_world.poll(accepted.json()["run_id"])
    assert detail["run"]["status"] == "succeeded" and "vision" not in _run_steps(detail)


def test_a_confirmed_extraction_reaches_the_run_as_untrusted_data_and_taints_it(vision_world: Assistant, world: World) -> None:
    file_id = upload_file(world.actor(keys.USERS.MEERA), Path(DEMO_DELIVERY_NOTE).read_bytes(), "note.png")
    card = vision_world.client.post(f"{API}/vision/extractions", headers=vision_world.headers, json={"file_id": str(file_id)}).json()
    vision_world.start()
    early = vision_world.post_turn("Use the delivery note details", extraction_id=card["request_id"])
    assert early.status_code == 409 and early.json()["code"] == "confirmation_required"
    confirmed = vision_world.client.post(
        f"{API}/vision/extractions/{card['request_id']}/confirm", headers=vision_world.headers,
        json={"expected_version": card["version"], "header": {"vehicle_number": "RJ19 GB 4471"}, "lines": [{}, {}, {"quantity": "2"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    accepted = vision_world.post_turn("Use the delivery note details", extraction_id=card["request_id"])
    assert accepted.status_code == 202, accepted.text
    drain()
    vision_world.poll(accepted.json()["run_id"])
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        run = uow.session.get(Run, uuid.UUID(accepted.json()["run_id"]))
        assert run is not None and run.tainted is True
        turn = uow.session.get(Turn, run.turn_id)
        assert turn is not None and str(turn.vision_request_id) == card["request_id"]
    other = vision_world.client.post(f"{API}/agents/conversations/{vision_world.conversation_id}/turns", headers={"x-test-persona": keys.USERS.SAHIL},
                                     json={"text": "Use it", "extraction_id": card["request_id"]})
    assert other.status_code == 404, "another person's conversation and extraction reveal nothing"


def test_live_capture_needs_the_recorded_dpdp_approval(vision_world: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    monkeypatch.setattr(vision, "capture_setting", lambda uow: ScreenCaptureSetting(enabled=True))
    conversation = vision_world.start()["id"]
    refused = vision_world.client.post(f"{API}/vision/screen-captures", params={"conversation_id": conversation},
                                       headers=vision_world.headers, files={"file": ("s.webp", _webp(), "image/webp")})
    assert refused.status_code == 403 and refused.json()["code"] == "dpdp_approval_required"
    caps = vision_world.client.get(f"{API}/vision/capabilities", headers=vision_world.headers).json()
    assert caps["screen_capture_enabled"] is False
    _set_routing(world, dpdp={"approved": True, "approved_on": "2026-11-04", "approved_by": "Owner (test)"})
    allowed = vision_world.client.post(f"{API}/vision/screen-captures", params={"conversation_id": conversation},
                                       headers=vision_world.headers, files={"file": ("s.webp", _webp(), "image/webp")})
    assert allowed.status_code == 201, allowed.text
    assert vision_world.client.get(f"{API}/vision/capabilities", headers=vision_world.headers).json()["screen_capture_enabled"] is True


def test_the_routing_table_sets_the_vision_model_and_quota_and_the_call_log_names_its_owner(
    vision_world: Assistant, world: World,
) -> None:
    _set_routing(world, models={"vision": "gemini-3.6-flash"}, quotas={"vision_calls_per_user": 1})
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        assert vision.vision_model(uow) == "gemini-3.6-flash" and vision.vision_quota(uow) == 1
    conversation = vision_world.start()["id"]
    capture = _capture(vision_world, conversation)
    body = {"capture_id": capture["id"], "question": "What is this?"}
    first = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json=body)
    assert first.status_code == 200, first.text
    over = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json=body)
    assert over.status_code == 409 and over.json()["code"] == "quota_exceeded"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        rows = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.workflow == "vision")))
    assert len(rows) == 1 and rows[0].user_id == world.user_id(keys.USERS.MEERA) and rows[0].correlation_id


def test_the_voice_module_is_the_whatsapp_transcriber(vision_world: Assistant) -> None:
    from app.modules.channels.whatsapp import stt
    from app.modules.voice import service as voice_service

    assert stt._transcriber is voice_service.whatsapp_transcriber  # noqa: SLF001 - the registration seam itself
