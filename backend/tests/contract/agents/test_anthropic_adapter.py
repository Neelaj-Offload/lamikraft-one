"""The Anthropic adapter against a fake HTTP transport (ai-routing.md section 5.1): never needs a key or the network.

The SDK client is built over an ``httpx2.MockTransport`` so the exact request body and headers the adapter sends
are inspected, and every documented stop reason, the typed exception chain (with ``retry-after``), the circuit
breaker and the prompt-cache prefix are exercised."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from app.modules.agents.providers import anthropic as adapter
from app.modules.agents.providers.anthropic import (
    AnthropicProvider,
    CircuitBreaker,
    build_params,
    is_strict_compatible,
    strict_schema,
)
from app.modules.agents.providers.base import (
    Message,
    ModelRequest,
    OpaqueBlock,
    ProviderError,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)

Handler = Callable[[httpx2.Request], httpx2.Response]


def _message(content: list[dict[str, Any]], stop_reason: str = "end_turn", **extra: Any) -> dict[str, Any]:
    return {
        "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": content,
        "stop_reason": stop_reason, "stop_sequence": None, "stop_details": None,
        "usage": {"input_tokens": 120, "output_tokens": 9, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20},
        **extra,
    }


def _provider(handler: Handler, *, breaker: CircuitBreaker | None = None) -> tuple[AnthropicProvider, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    client = anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(record)))
    return AnthropicProvider(client=client, breaker=breaker or CircuitBreaker()), seen


def _json(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json=body, headers={"request-id": "req_test_1", **(headers or {})})


def _tools() -> tuple[ToolSpec, ...]:
    read_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    draft_schema = {
        "type": "object", "properties": {"party_id": {"type": "string"}, "lines": {"type": "array", "items": {
            "type": "object", "properties": {"quantity": {"type": "string"}, "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}}}}},
        "required": ["party_id"],
    }
    return (
        ToolSpec(name="resolve_party", description="Find a party", input_schema=read_schema, effect="read"),
        ToolSpec(name="draft_quote", description="Draft a quote", input_schema=draft_schema, effect="draft"),
    )


def _request(task_class: str = "orchestration", **kw: Any) -> ModelRequest:
    base: dict[str, Any] = dict(
        task_class=task_class, system="system.v1\nFacts come from tools.",
        messages=(Message(role="user", content=(TextBlock("Prepare the usual quote"),)),),
        tools=_tools(), strict_tools=frozenset({"draft_quote"}), max_tokens=8192,
        context={"tainted": False, "tools": ["draft_quote", "resolve_party"]},
    )
    base.update(kw)
    return ModelRequest(**base)


# ---- request shape ------------------------------------------------------------------------------------------------
def test_request_shape_tool_choice_auto_strict_tools_adaptive_thinking_and_cache_prefix() -> None:
    provider, seen = _provider(lambda _r: _json(200, _message([{"type": "text", "text": "Done."}])))
    provider.generate(_request())
    body = json.loads(seen[0].content)
    assert body["tool_choice"] == {"type": "auto"}
    assert body["thinking"] == {"type": "adaptive"} and "budget_tokens" not in json.dumps(body)
    assert body["output_config"] == {"effort": "medium"}
    assert body["max_tokens"] == 8192
    names = [t["name"] for t in body["tools"]]
    assert names == sorted(names) == ["draft_quote", "resolve_party"], "tools sorted by name for a deterministic prefix"
    draft, read = body["tools"]
    assert draft["strict"] is True and is_strict_compatible(draft["input_schema"])
    assert "strict" not in read and read.get("cache_control") == {"type": "ephemeral"}, "cache_control on the last tool"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"} and body["system"][0]["text"].startswith("system.v1")
    assert "cache_control" not in body["system"][1] and "Context facts" in body["system"][1]["text"]
    assert body["messages"][-1]["role"] == "user"
    assert seen[0].headers["anthropic-beta"] == adapter.FALLBACK_BETA and body["fallbacks"] == "default"
    assert "Prepare the usual quote" not in body["system"][0]["text"], "volatile text never enters the cached prefix"


def test_haiku_requests_carry_no_fallbacks_and_structured_output_goes_in_output_config() -> None:
    provider, seen = _provider(lambda _r: _json(200, _message([{"type": "text", "text": "{\"request_type\": \"command\"}"}])))
    schema = {"type": "object", "properties": {"request_type": {"type": "string"}}, "required": ["request_type"], "additionalProperties": False}
    provider.generate(_request("routing", tools=(), strict_tools=frozenset(), max_tokens=512, model="claude-haiku-5-5", effort="low", output_schema=schema))
    body = json.loads(seen[0].content)
    assert "fallbacks" not in body and "anthropic-beta" not in seen[0].headers
    assert body["model"] == "claude-haiku-5-5" and body["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert body["max_tokens"] == 512 and "tools" not in body and "tool_choice" not in body


def test_max_tokens_is_capped_per_task_class() -> None:
    params = build_params(_request("orchestration", max_tokens=50_000), "claude-sonnet-5-5", min(50_000, adapter.TASK_DEFAULTS["orchestration"][1]))
    assert params["max_tokens"] == 8192


def test_strict_schema_closes_every_object_and_requires_every_property() -> None:
    strict = strict_schema(_tools()[1].input_schema)
    assert is_strict_compatible(strict)
    assert strict["required"] == ["lines", "party_id"] and strict["additionalProperties"] is False
    item = strict["properties"]["lines"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["note", "quantity"]
    assert not is_strict_compatible(_tools()[1].input_schema)


def test_strict_budget_is_respected() -> None:
    tools = tuple(ToolSpec(name=f"draft_{i:02d}", description="d", input_schema={"type": "object", "properties": {}}, effect="draft") for i in range(adapter.STRICT_TOOL_BUDGET + 3))
    rendered = adapter.render_tools(tools, {t.name for t in tools})
    assert sum(1 for t in rendered if t.get("strict")) == adapter.STRICT_TOOL_BUDGET


# ---- block iteration, stop reasons and fallbacks -----------------------------------------------------------------
def test_block_iteration_stop_reasons_and_fallbacks() -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Looking up the customer."},
        {"type": "tool_use", "id": "toolu_1", "name": "resolve_party", "input": {"query": "Nordhaus"}},
    ]
    provider, _ = _provider(lambda _r: _json(200, _message(content, "tool_use")))
    response = provider.generate(_request())
    kinds = [type(b).__name__ for b in response.iter_blocks()]
    assert kinds == ["OpaqueBlock", "TextBlock", "ToolUseBlock"], "iterated by type, never content[0]"
    assert response.stop_reason == "tool_use" and response.text == "Looking up the customer."
    assert response.usage.cache_read_tokens == 100 and response.usage.cache_write_tokens == 20
    assert response.request_id == "req_test_1" and response.provider == "anthropic"
    tool = next(b for b in response.content if isinstance(b, ToolUseBlock))
    assert tool.input == {"query": "Nordhaus"}

    # thinking blocks are replayed unchanged within the run (append-only), tool results as tool_result blocks
    follow_up = _request(messages=(
        Message(role="user", content=(TextBlock("Prepare the usual quote"),)),
        Message(role="assistant", content=tuple(response.content)),
        Message(role="user", content=(ToolResultBlock(tool_use_id="toolu_1", name="resolve_party", content={"ok": True}),)),
    ))
    provider2, seen2 = _provider(lambda _r: _json(200, _message([{"type": "text", "text": "Done."}])))
    provider2.generate(follow_up)
    body = json.loads(seen2[0].content)
    assistant = body["messages"][1]["content"]
    assert assistant[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert body["messages"][2]["content"][0]["type"] == "tool_result" and body["messages"][2]["content"][0]["tool_use_id"] == "toolu_1"


def test_refusal_carries_stop_details_and_fallback_marker_is_detected() -> None:
    refusal = _message([], "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"})
    provider, _ = _provider(lambda _r: _json(200, refusal))
    response = provider.generate(_request())
    assert response.stop_reason == "refusal" and response.stop_details == {"type": "refusal", "category": "cyber", "explanation": "declined"}
    assert list(response.iter_blocks()) == []

    served = _message([{"type": "fallback", "from": {"model": "claude-sonnet-5-5"}, "to": {"model": "claude-opus-4-8"}}, {"type": "text", "text": "ok"}])
    served["usage"]["iterations"] = [{"type": "fallback_message", "model": "claude-opus-4-8"}]
    provider2, _ = _provider(lambda _r: _json(200, served))
    out = provider2.generate(_request())
    assert out.fallback_used is True and out.text == "ok" and isinstance(out.content[0], OpaqueBlock)


def test_max_tokens_truncation_is_retried_once_with_a_higher_cap() -> None:
    answers = iter([_message([{"type": "text", "text": "partial"}], "max_tokens"), _message([{"type": "text", "text": "complete"}])])
    provider, seen = _provider(lambda _r: _json(200, next(answers)))
    response = provider.generate(_request(max_tokens=4096))
    assert response.text == "complete" and len(seen) == 2
    assert json.loads(seen[0].content)["max_tokens"] == 4096 and json.loads(seen[1].content)["max_tokens"] == 8192


def test_pause_turn_is_continued_with_the_assistant_turn_appended_and_bounded() -> None:
    paused = _message([{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}}], "pause_turn")
    answers = iter([paused, _message([{"type": "text", "text": "resumed"}])])
    provider, seen = _provider(lambda _r: _json(200, next(answers)))
    response = provider.generate(_request())
    assert response.text == "resumed" and len(seen) == 2
    second = json.loads(seen[1].content)["messages"]
    assert second[-1]["role"] == "assistant" and second[-1]["content"][0]["type"] == "server_tool_use"

    always_paused, _ = _provider(lambda _r: _json(200, paused))
    out = always_paused.generate(_request())
    assert out.stop_reason == "pause_turn", "bounded: gives up after MAX_PAUSE_CONTINUATIONS"


def test_context_window_exceeded_is_a_provider_error() -> None:
    provider, _ = _provider(lambda _r: _json(200, _message([], "model_context_window_exceeded")))
    with pytest.raises(ProviderError) as info:
        provider.generate(_request())
    assert info.value.code == "context_window_exceeded"


# ---- typed exception chain and the circuit breaker ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "headers", "code", "retry_after"),
    [
        (404, {}, "model_not_found", None),
        (429, {"retry-after": "7"}, "rate_limited", 7),
        (529, {}, "provider_overloaded", None),
        (500, {}, "provider_error", None),
        (400, {}, "provider_request_rejected", None),
    ],
)
def test_typed_exception_chain_with_retry_after_and_request_id(status: int, headers: dict[str, str], code: str, retry_after: int | None) -> None:
    body = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    provider, _ = _provider(lambda _r: _json(status, body, headers))
    with pytest.raises(ProviderError) as info:
        provider.generate(_request())
    assert info.value.code == code and info.value.retry_after_seconds == retry_after and info.value.status == status
    assert info.value.request_id == "req_test_1"
    assert isinstance(info.value.__cause__, anthropic.APIStatusError)


def test_connection_errors_map_to_unreachable() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    provider, _ = _provider(fail)
    with pytest.raises(ProviderError) as info:
        provider.generate(_request())
    assert info.value.code == "provider_unreachable" and isinstance(info.value.__cause__, anthropic.APIConnectionError)


def test_circuit_breaker_opens_after_five_failures_in_two_minutes_for_sixty_seconds() -> None:
    now = [1_000.0]
    breaker = CircuitBreaker(clock=lambda: now[0])
    body = {"type": "error", "error": {"type": "api_error", "message": "down"}}
    provider, seen = _provider(lambda _r: _json(500, body), breaker=breaker)
    for _ in range(5):
        with pytest.raises(ProviderError):
            provider.generate(_request())
    # the SDK retries 5xx twice (max_retries=2), so five failed calls are fifteen HTTP attempts
    assert breaker.state == "open" and len(seen) == 15
    with pytest.raises(ProviderError) as info:
        provider.generate(_request())
    assert info.value.code == "circuit_open" and len(seen) == 15, "no provider call while the circuit is open"
    now[0] += 61
    assert breaker.state == "half_open"
    ok, _ = _provider(lambda _r: _json(200, _message([{"type": "text", "text": "back"}])), breaker=breaker)
    assert ok.generate(_request()).text == "back" and breaker.state == "closed"

    stale = CircuitBreaker(clock=lambda: now[0])
    for _ in range(4):
        stale.record_failure()
    now[0] += 121
    stale.record_failure()
    assert stale.state == "closed", "failures older than the window do not count"


def test_batch_requests_carry_no_fallbacks_and_results_are_keyed_by_custom_id() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        if request.url.path.endswith("/batches") and request.method == "POST":
            return _json(200, {"id": "msgbatch_1", "type": "message_batch", "processing_status": "in_progress", "request_counts": {"processing": 2, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}, "created_at": "2026-10-12T00:00:00Z", "expires_at": "2026-10-13T00:00:00Z", "ended_at": None, "cancel_initiated_at": None, "archived_at": None, "results_url": None})
        if request.url.path.endswith("/batches/msgbatch_1"):
            return _json(200, {"id": "msgbatch_1", "type": "message_batch", "processing_status": "ended", "request_counts": {"processing": 0, "succeeded": 2, "errored": 0, "canceled": 0, "expired": 0}, "created_at": "2026-10-12T00:00:00Z", "expires_at": "2026-10-13T00:00:00Z", "ended_at": "2026-10-12T00:10:00Z", "cancel_initiated_at": None, "archived_at": None, "results_url": "https://api.anthropic.com/v1/messages/batches/msgbatch_1/results"})
        lines = [
            json.dumps({"custom_id": "b", "result": {"type": "succeeded", "message": _message([{"type": "text", "text": "second"}])}}),
            json.dumps({"custom_id": "a", "result": {"type": "errored", "error": {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}}}),
        ]
        return httpx2.Response(200, content="\n".join(lines).encode(), headers={"content-type": "application/x-jsonl"})

    provider, _ = _provider(handler)
    batch_id = provider.submit_batch({"a": _request("phrasing", tools=(), strict_tools=frozenset(), max_tokens=600),
                                      "b": _request("phrasing", tools=(), strict_tools=frozenset(), max_tokens=600)})
    created = json.loads(calls[0].content)
    assert batch_id == "msgbatch_1" and all("fallbacks" not in r["params"] for r in created["requests"])
    assert "anthropic-beta" not in calls[0].headers
    results = provider.collect_batch(batch_id, wait_seconds=1, sleep=lambda _s: None)
    assert results is not None and results["b"].text == "second" and isinstance(results["a"], ProviderError)  # type: ignore[union-attr]
