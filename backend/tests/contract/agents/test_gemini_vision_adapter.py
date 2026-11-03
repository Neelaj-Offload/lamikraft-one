"""Gemini vision adapter over a fake transport (httpx.MockTransport through ``HttpOptions.httpx_client``): the
request shape (model in the URL, key in the header, JSON response schema, output caps, timeouts, no tools), the
parsed result, and every failure mapped to ``VisionUnavailable``. No network."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.modules.agents.providers.gemini_vision import GeminiVisionProvider
from app.modules.vision.contract import (
    EXTRACTION_MAX_OUTPUT_TOKENS,
    SCREEN_MAX_OUTPUT_TOKENS,
    ScreenFacts,
    VisionUnavailable,
    extraction_schema,
)

MODEL = "gemini-3.8-flash"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c49444154789c63f8ffff3f"
    "0005fe02fe0def46b80000000049454e44ae426082"
)


def _reply(payload: Any, *, finish: str = "STOP", status: int = 200) -> httpx.Response:
    body = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(payload) if not isinstance(payload, str) else payload}]},
                        "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 1290, "candidatesTokenCount": 42},
        "responseId": "resp-abc",
        "modelVersion": MODEL,
    }
    return httpx.Response(status, json=body)


def _provider(handler: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]) -> GeminiVisionProvider:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return GeminiVisionProvider(api_key="test-key", model=MODEL, http_client=httpx.Client(transport=httpx.MockTransport(record)))


def test_screen_answer_request_shape_and_result() -> None:
    seen: list[httpx.Request] = []
    provider = _provider(lambda r: _reply({"answer": "The quote list for Nordhaus.", "needs_data_or_action": False,
                                           "confidence": 0.86}), seen)
    answer = provider.answer_screen(PNG, "image/png", "What is this screen?",
                                    ScreenFacts("/sales/quotes", "sales", ({"type": "sales.quote", "label": "LK-QT-2026-0008"},)))
    assert answer.text == "The quote list for Nordhaus." and answer.needs_handoff is False
    assert (answer.input_tokens, answer.output_tokens, answer.request_id) == (1290, 42, "resp-abc")
    (request,) = seen
    assert str(request.url).endswith(f"/models/{MODEL}:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json" and config["maxOutputTokens"] == SCREEN_MAX_OUTPUT_TOKENS
    assert config["responseJsonSchema"]["required"] == ["answer", "needs_data_or_action", "confidence"]
    # proto3 JSON accepts both spellings; SDK 2.29.0 sends the nested field in snake case
    thinking = config["thinkingConfig"]
    assert thinking.get("thinkingLevel", thinking.get("thinking_level")) == "LOW" and config["temperature"] == 0
    assert "tools" not in body and "toolConfig" not in body  # read-only: no function calling
    parts = body["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType" if "mimeType" in parts[0]["inlineData"] else "mime_type"] == "image/png"
    assert json.loads(parts[1]["text"])["screen"]["records"][0]["label"] == "LK-QT-2026-0008"
    assert "opaque blocks" in body["systemInstruction"]["parts"][0]["text"]


def test_screen_answer_hand_off_flag() -> None:
    provider = _provider(lambda r: _reply({"answer": "That needs the assistant.", "needs_data_or_action": True,
                                           "reason": "creates a quote", "confidence": 0.9}), [])
    answer = provider.answer_screen(PNG, "image/png", "make a quote", ScreenFacts(None, None))
    assert answer.needs_handoff is True and answer.handoff_reason == "creates a quote"


def test_extraction_parses_fields_and_keeps_missing_ones_empty() -> None:
    seen: list[httpx.Request] = []
    payload = {
        "header": {"document_number": {"value": "PO-77", "confidence": 0.95}, "currency": {"value": None, "confidence": 0.7},
                   "unexpected": {"value": "x", "confidence": 1}},
        "lines": [{"description": {"value": "Oak tray", "confidence": 0.9}, "quantity": {"value": "240", "confidence": 1.4}}],
    }
    provider = _provider(lambda r: _reply(payload), seen)
    result = provider.extract(PNG, "image/png", "purchase_order")
    assert result.kind == "purchase_order" and result.detected_kind is None
    assert result.header["document_number"].value == "PO-77" and result.header["document_number"].confidence == 0.95
    assert result.header["currency"].value is None and result.header["currency"].confidence == 0.0
    assert result.header["buyer_name"].value is None and "unexpected" not in result.header
    assert result.lines[0]["quantity"].confidence == 1.0 and result.lines[0]["uom"].value is None
    config = json.loads(seen[0].content)["generationConfig"]
    assert config["maxOutputTokens"] == EXTRACTION_MAX_OUTPUT_TOKENS
    assert config["responseJsonSchema"] == extraction_schema("purchase_order")
    assert config["mediaResolution"] == "MEDIA_RESOLUTION_HIGH"


def test_extraction_without_a_kind_classifies_first() -> None:
    seen: list[httpx.Request] = []
    replies = iter([_reply({"kind": "bill"}), _reply({"header": {}, "lines": []})])
    provider = _provider(lambda r: next(replies), seen)
    result = provider.extract(PNG, "image/png", None)
    assert result.kind == "bill" and result.detected_kind == "bill" and len(seen) == 2
    assert result.input_tokens == 2 * 1290


@pytest.mark.parametrize(
    ("handler", "code"),
    [
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), "timeout"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)), "connection"),
        (lambda r: httpx.Response(429, json={"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}), "http_429"),
        (lambda r: httpx.Response(503, json={"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}), "http_503"),
        (lambda r: _reply({"answer": "x"}, finish="SAFETY"), "finish_safety"),
        (lambda r: _reply("not json"), "unparseable"),
        (lambda r: _reply({"answer": "", "needs_data_or_action": False, "confidence": 0}), "empty_answer"),
    ],
)
def test_failures_become_vision_unavailable(handler: Callable[[httpx.Request], httpx.Response], code: str) -> None:
    provider = _provider(handler, [])
    with pytest.raises(VisionUnavailable) as caught:
        provider.answer_screen(PNG, "image/png", "What is this?", ScreenFacts(None, None))
    assert caught.value.code == code and str(caught.value) == "Vision unavailable — enter details"


def test_missing_key_is_not_configured() -> None:
    with pytest.raises(VisionUnavailable) as caught:
        GeminiVisionProvider(api_key="", model=MODEL)
    assert caught.value.code == "not_configured"


def test_timeouts_are_eight_and_twenty_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GeminiVisionProvider(api_key="k", model=MODEL)
    timeouts: list[int] = []
    original = provider._client

    def spy(seconds: int) -> Any:
        timeouts.append(seconds)
        return original(seconds)

    monkeypatch.setattr(provider, "_client", spy)
    transport = httpx.MockTransport(lambda r: _reply({"answer": "ok", "needs_data_or_action": False, "confidence": 1}))
    provider._http_client = httpx.Client(transport=transport)
    provider.answer_screen(PNG, "image/png", "q", ScreenFacts(None, None))
    provider._http_client = httpx.Client(transport=httpx.MockTransport(lambda r: _reply({"header": {}, "lines": []})))
    provider.extract(PNG, "image/png", "delivery_note")
    assert timeouts == [8, 20]
    client = original(8)
    assert client._api_client._http_options.timeout == 8_000
