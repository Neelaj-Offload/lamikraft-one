"""Live mode against a scripted fake Claude (no key, no network): the real Anthropic adapter and SDK client over an
``httpx2.MockTransport``. Every request body is captured so tests can assert what reached the provider.

Usage::

    fake = FakeClaude(script)
    with live_mode(monkeypatch, fake):
        detail = meera.say("...")
    fake.bodies  # every JSON request body, in order
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import anthropic
import httpx2
import pytest

from app.core.config import reset_settings_cache
from app.modules.agents.providers import anthropic as adapter

Script = Callable[[dict[str, Any]], "dict[str, Any] | httpx2.Response"]


def message(content: list[dict[str, Any]], *, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5",
            input_tokens: int = 1200, output_tokens: int = 40, cache_read: int = 900, cache_write: int = 0,
            stop_details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None, "stop_details": stop_details,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_input_tokens": cache_read,
                  "cache_creation_input_tokens": cache_write},
    }


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool_use(block_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": payload}


def tool_results(body: dict[str, Any]) -> dict[str, str]:
    """``tool_use_id -> content text`` of every tool_result block in a request body."""
    out: dict[str, str] = {}
    for msg in body.get("messages", []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    inner = "".join(b.get("text", "") for b in inner if isinstance(b, dict))
                out[str(block.get("tool_use_id"))] = str(inner)
    return out


def is_router(body: dict[str, Any]) -> bool:
    return "format" in (body.get("output_config") or {}) and str(body.get("model", "")).startswith("claude-haiku")


class FakeClaude:
    def __init__(self, script: Script) -> None:
        self.script = script
        self.bodies: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.bodies.append(body)
        self.headers.append(dict(request.headers))
        out = self.script(body)
        if isinstance(out, httpx2.Response):
            return out
        return httpx2.Response(200, json=out, headers={"request-id": f"req_fake_{len(self.bodies)}"})

    def raw(self) -> str:
        return json.dumps(self.bodies)


@contextmanager
def live_mode(monkeypatch: pytest.MonkeyPatch, fake: FakeClaude, *,
              breaker: adapter.CircuitBreaker | None = None) -> Iterator[adapter.CircuitBreaker]:
    """``LK_AI_MODE=live`` with a test key; ``get_provider`` builds the real adapter over the fake transport."""
    breaker = breaker or adapter.CircuitBreaker()
    client = anthropic.Anthropic(api_key="test-key", max_retries=0,
                                 http_client=httpx2.Client(transport=httpx2.MockTransport(fake.handle)))
    real = adapter.AnthropicProvider
    monkeypatch.setenv("LK_AI_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(adapter, "MAX_RETRIES", 0)
    monkeypatch.setattr(adapter, "AnthropicProvider", lambda *a, **k: real(client=client, breaker=breaker))
    reset_settings_cache()
    try:
        yield breaker
    finally:
        monkeypatch.undo()
        reset_settings_cache()


__all__ = ["FakeClaude", "is_router", "live_mode", "message", "text", "tool_results", "tool_use"]
