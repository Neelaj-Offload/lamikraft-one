"""Vision through the API (ai-routing.md sections 3, 4.2, 5.2, 6): masked captures stored restricted and purged,
instant screen answers from the re-read context with hand-off, extraction into a confirmation card, the mandatory
company switch, live mode failing visibly, and provider failures degrading to "Vision unavailable — enter details"."""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from app.core.clock import FrozenClock
from app.core.config import get_settings
from app.modules.agents.models import AiCallLog
from app.modules.agents.providers.demo_vision import DEMO_DELIVERY_NOTE
from app.modules.agents.providers.gemini_vision import GeminiVisionProvider
from app.modules.vision import service as vision
from app.modules.vision.models import VisionCapture, VisionRequest
from app.modules.vision.schemas import ScreenCaptureSetting
from app.platform.authz.context import ActorContext
from app.platform.files.models import FileObject
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.agents.conftest import Assistant
from tests.integration.catalogue.world import World, upload_file

pytestmark = pytest.mark.db
API = "/api/v1"


def _webp(width: int = 800, height: int = 500, color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "WEBP", quality=70)
    return buffer.getvalue()


def _capture(meera: Assistant, data: bytes, **params: object) -> httpx.Response:
    return meera.client.post(f"{API}/vision/screen-captures", params={k: str(v) for k, v in params.items()},
                             headers=meera.headers, files={"file": ("screen.webp", data, "image/webp")})


def _quote_context(world: World) -> dict:
    quote_id = str(world.ref("Q_NORDHAUS_DRAFT"))  # LK-QT-2026-0008
    return {"schema_version": 1, "route": {"path": "/sales/quotes/[quoteId]", "params": {"quoteId": quote_id}, "area": "sales"},
            "focus": {"type": "sales.quote", "id": quote_id}}


@pytest.fixture
def vision_world(meera: Assistant, media_storage: object) -> Assistant:
    return meera


def test_capabilities_demo_defaults(vision_world: Assistant) -> None:
    caps = vision_world.client.get(f"{API}/vision/capabilities", headers=vision_world.headers).json()
    assert caps["screen_capture_enabled"] is True and caps["screen_share"] == "ask"
    assert caps["provider_label"] == "Demo" and caps["mode"] == "demo" and caps["configured"] is True
    assert caps["max_capture_bytes"] == 1_572_864 and caps["max_edge_px"] == 1568


def test_masked_capture_is_restricted_deduplicated_and_bounded(vision_world: Assistant, world: World) -> None:
    conversation = vision_world.start()["id"]
    first = _capture(vision_world, _webp(), conversation_id=conversation, masked_count=3, route_path="/sales/quotes")
    assert first.status_code == 201, first.text
    body = first.json()
    again = _capture(vision_world, _webp(), conversation_id=conversation)
    assert again.status_code == 201 and again.json()["id"] == body["id"] and again.json()["deduplicated"] is True
    other_conversation = _capture(vision_world, _webp())
    assert other_conversation.json()["id"] != body["id"]
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        capture = uow.session.get(VisionCapture, uuid.UUID(body["id"]))
        assert capture is not None and capture.masked_count == 3
        obj = uow.session.get(FileObject, capture.file_id)
        assert obj is not None and obj.purpose == "screen_capture" and obj.restricted is True and obj.kind == "webp"
    too_big = _capture(vision_world, _webp(1600, 400))
    assert too_big.status_code == 422 and too_big.json()["code"] == "capture_too_large"
    jpeg = io.BytesIO()
    Image.new("RGB", (10, 10)).save(jpeg, "JPEG")
    wrong = _capture(vision_world, jpeg.getvalue())
    assert wrong.status_code == 422 and wrong.json()["code"] == "invalid_capture"
    # the generic upload endpoint cannot create screen captures
    generic = vision_world.client.post(f"{API}/files", params={"purpose": "screen_capture"}, headers=vision_world.headers,
                                       files={"file": ("s.webp", _webp(), "image/webp")})
    assert generic.status_code == 422


def test_company_switch_is_mandatory_and_off_by_default_in_live(vision_world: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    refused = _capture(vision_world, _webp())
    assert refused.status_code == 403 and refused.json()["code"] == "screen_capture_disabled"
    caps = vision_world.client.get(f"{API}/vision/capabilities", headers=vision_world.headers).json()
    assert caps["screen_capture_enabled"] is False and caps["configured"] is False and caps["mode"] == "live"


def test_screen_answer_uses_reread_context_and_hands_off_actions(vision_world: Assistant, world: World) -> None:
    capture = _capture(vision_world, _webp()).json()
    context = _quote_context(world)
    answer = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json={
        "capture_id": capture["id"], "question": "What is this screen?", "context": context})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] == "answered" and body["handoff"] is False and body["tainted"] is True
    assert "LK-QT-2026-0008" in body["text"] and body["provider_label"] == "Demo"
    handoff = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json={
        "capture_id": capture["id"], "question": "Change the quantity to 300", "context": context}).json()
    assert handoff["status"] == "handed_off" and handoff["handoff"] is True
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        request = uow.session.get(VisionRequest, uuid.UUID(body["request_id"]))
        assert request is not None and request.input_sha256 == capture["sha256"] and request.tainted is True
        log_row = uow.session.get(AiCallLog, request.call_log_id)
        assert log_row is not None and log_row.workflow == "vision" and log_row.task_class == "vision"
        assert capture["sha256"] not in json.dumps({c.name: str(getattr(log_row, c.name)) for c in AiCallLog.__table__.columns})


def test_unauthorised_context_and_foreign_captures_reveal_nothing(vision_world: Assistant, world: World) -> None:
    capture = _capture(vision_world, _webp()).json()
    other = vision_world.client.post(f"{API}/vision/screen-answers", headers={"x-test-persona": keys.USERS.ARJUN}, json={
        "capture_id": capture["id"], "question": "What is this?"})
    assert other.status_code == 404
    removed = vision_world.client.delete(f"{API}/vision/screen-captures/{capture['id']}", headers=vision_world.headers)
    assert removed.status_code == 200 and removed.json()["status"] == "purged"
    gone = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json={
        "capture_id": capture["id"], "question": "What is this?"})
    assert gone.status_code == 404 and gone.json()["code"] == "capture_not_attached"


def test_unsupported_figures_in_a_screen_answer_are_replaced(vision_world: Assistant, world: World,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.vision.contract import VisionAnswer

    class Inventive:
        name, label, model = "gemini", "Gemini", "gemini-3.8-flash"

        def answer_screen(self, *args: object) -> VisionAnswer:
            return VisionAnswer(text="The total is EUR 9,999.00 for 77 pcs.", needs_handoff=False, handoff_reason=None,
                                confidence=0.9, provider="gemini", model=self.model)

    monkeypatch.setattr(vision, "get_provider", lambda uow: Inventive())
    capture = _capture(vision_world, _webp()).json()
    body = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json={
        "capture_id": capture["id"], "question": "total?", "context": _quote_context(world)}).json()
    assert "9,999" not in body["text"] and "77" not in body["text"] and "see screen" in body["text"]


def test_extraction_card_marks_uncertain_fields_for_confirmation(vision_world: Assistant, world: World) -> None:
    file_id = upload_file(world.actor(keys.USERS.MEERA), Path(DEMO_DELIVERY_NOTE).read_bytes(), "note.png")
    response = vision_world.client.post(f"{API}/vision/extractions", headers=vision_world.headers, json={"file_id": str(file_id)})
    assert response.status_code == 201, response.text
    card = response.json()
    assert card["kind"] == "extraction" and card["extraction_kind"] == "delivery_note" and card["tainted"] is True
    header = {f["key"]: f for f in card["header"]}
    assert header["document_number"]["value"] == "DN-4471" and header["document_number"]["needs_confirmation"] is False
    vehicle = header["vehicle_number"]
    assert vehicle["needs_confirmation"] is True and vehicle["value"] is None and vehicle["suggestion"] == "RJ19 GB 4471"
    roll = {f["key"]: f for f in card["lines"][2]["fields"]}
    assert roll["quantity"]["needs_confirmation"] is True and roll["quantity"]["value"] is None
    assert card["pending_confirmations"] == 2

    missing = vision_world.client.post(f"{API}/vision/extractions/{card['request_id']}/confirm", headers=vision_world.headers,
                                       json={"expected_version": card["version"], "header": {}, "lines": [{}, {}, {}]})
    assert missing.status_code == 422 and missing.json()["code"] == "confirmation_required"
    confirmed = vision_world.client.post(
        f"{API}/vision/extractions/{card['request_id']}/confirm", headers=vision_world.headers,
        json={"expected_version": card["version"], "header": {"vehicle_number": "RJ19 GB 4471"},
              "lines": [{}, {}, {"quantity": "2"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    done = confirmed.json()
    assert done["status"] == "confirmed" and done["pending_confirmations"] == 0
    assert {f["key"]: f["value"] for f in done["lines"][2]["fields"]}["quantity"] == "2"
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        payload = vision.untrusted_payload(uow, uuid.UUID(card["request_id"]))
    assert payload["untrusted"] is True and payload["source"] == "vision.extraction:delivery_note"
    twice = vision_world.client.post(f"{API}/vision/extractions/{card['request_id']}/confirm", headers=vision_world.headers,
                                     json={"expected_version": done["version"], "header": {}, "lines": [{}, {}, {}]})
    assert twice.status_code == 409


def test_unknown_image_in_demo_is_all_confirmation_fields(vision_world: Assistant, world: World) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "gray").save(buffer, "PNG")
    file_id = upload_file(world.actor(keys.USERS.MEERA), buffer.getvalue(), "photo.png")
    card = vision_world.client.post(f"{API}/vision/extractions", headers=vision_world.headers,
                                    json={"file_id": str(file_id), "kind": "handwritten_list"}).json()
    assert card["extraction_kind"] == "handwritten_list" and card["lines"] == []
    assert all(f["needs_confirmation"] and f["value"] is None for f in card["header"])


def test_live_mode_without_a_key_fails_visibly(vision_world: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    file_id = upload_file(world.actor(keys.USERS.MEERA), Path(DEMO_DELIVERY_NOTE).read_bytes(), "note.png")
    monkeypatch.setattr(get_settings(), "ai_mode", "live")
    monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr(""))
    response = vision_world.client.post(f"{API}/vision/extractions", headers=vision_world.headers, json={"file_id": str(file_id)})
    assert response.status_code == 409 and response.json()["code"] == "not_configured"


def test_provider_timeout_degrades_to_manual_entry(vision_world: Assistant, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = GeminiVisionProvider(api_key="test-key", model="gemini-3.8-flash",
                                    http_client=httpx.Client(transport=httpx.MockTransport(timeout)))
    monkeypatch.setattr(vision, "get_provider", lambda uow: provider)
    monkeypatch.setattr(vision, "capture_setting", lambda uow: ScreenCaptureSetting(enabled=True))
    capture = _capture(vision_world, _webp()).json()
    answer = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers,
                                      json={"capture_id": capture["id"], "question": "What is this?"}).json()
    assert answer["status"] == "unavailable" and answer["text"] == "Vision unavailable — enter details"
    file_id = upload_file(world.actor(keys.USERS.MEERA), Path(DEMO_DELIVERY_NOTE).read_bytes(), "note.png")
    card = vision_world.client.post(f"{API}/vision/extractions", headers=vision_world.headers,
                                    json={"file_id": str(file_id), "kind": "bill"}).json()
    assert card["status"] == "unavailable" and card["message"] == "Vision unavailable — enter details"
    assert all(f["needs_confirmation"] for f in card["header"])
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        rows = list(uow.session.scalars(select(AiCallLog).where(AiCallLog.workflow == "vision")))
    assert {r.outcome for r in rows} == {"error"} and {r.error_type for r in rows} == {"timeout"}


def test_daily_quota_stops_vision(vision_world: Assistant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "vision_quota", lambda uow: 1)
    capture = _capture(vision_world, _webp()).json()
    body = {"capture_id": capture["id"], "question": "What is this?"}
    assert vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json=body).status_code == 200
    over = vision_world.client.post(f"{API}/vision/screen-answers", headers=vision_world.headers, json=body)
    assert over.status_code == 409 and over.json()["code"] == "quota_exceeded"


def test_captures_are_purged_after_24_hours(vision_world: Assistant, world: World, media_storage: object,
                                             frozen_clock: FrozenClock) -> None:
    capture = _capture(vision_world, _webp()).json()
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        row = uow.session.get(VisionCapture, uuid.UUID(capture["id"]))
        assert row is not None and row.file_id is not None
        file_id = row.file_id
        key = uow.session.get(FileObject, file_id).storage_key  # type: ignore[union-attr]
    assert media_storage.exists(key)  # type: ignore[attr-defined]
    frozen_clock.advance(hours=23)
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        assert vision.purge_due(uow) == 0
    frozen_clock.advance(hours=1, minutes=1)
    with UnitOfWork(ActorContext.system(world.company_id)) as uow:
        assert vision.purge_due(uow) == 1
    with UnitOfWork(world.actor(keys.USERS.MEERA)) as uow:
        row = uow.session.get(VisionCapture, uuid.UUID(capture["id"]))
        assert row is not None and row.status == "purged" and row.file_id is None
        assert uow.session.get(FileObject, file_id) is None
    assert not media_storage.exists(key)  # type: ignore[attr-defined]
