"""The Anthropic adapter (ai-routing.md section 5.1): ``generate(ModelRequest) -> ModelResponse`` over the sync SDK.

- synchronous ``anthropic.Anthropic`` client, ``max_retries=2``, an explicit timeout per task class;
- ``tool_choice: auto`` always; write/proposal tools are sent ``strict: true`` within ``STRICT_TOOL_BUDGET``;
- adaptive thinking with an explicit ``output_config.effort``; no ``budget_tokens``, no assistant prefill;
- every content block is iterated by type; thinking blocks come back as ``OpaqueBlock`` and are replayed unchanged
  within the run;
- stop reasons: ``end_turn``, ``tool_use``, ``stop_sequence``, ``max_tokens`` (one retry with a higher cap),
  ``pause_turn`` (continued, bounded), ``refusal`` (``stop_details`` carried to the orchestrator);
- server-side refusal fallbacks (``fallbacks: "default"``, beta ``server-side-fallback-2026-07-01``) on Sonnet and
  Opus requests only — Haiku has none and Message Batches never carry ``fallbacks``;
- a typed exception chain (``NotFoundError`` → ``RateLimitError`` honouring ``retry-after`` → ``APIStatusError`` →
  ``APIConnectionError``) mapped onto ``ProviderError`` with the provider ``request-id`` kept;
- a circuit breaker: 5 failures in 2 minutes open the circuit for 60 seconds;
- prompt caching with a deterministic prefix (tools sorted by name, the versioned system prompt, ``cache_control`` on
  the system prompt and the last tool); volatile facts come after the last breakpoint.

Nothing here touches the database; the orchestrator logs usage (incl. ``cache_read_input_tokens``) per call.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.modules.agents.providers.base import (
    ModelRequest,
    ModelResponse,
    OpaqueBlock,
    ProviderError,
    Stopwatch,
    TaskClass,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)

PROVIDER_NAME = "anthropic"
PROVIDER_LABEL = "Claude"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: strict tool definitions allowed per request (write and proposal tools first, by name)
STRICT_TOOL_BUDGET = 16
MAX_RETRIES = 2
MAX_PAUSE_CONTINUATIONS = 3
#: a truncated reply is retried once with a higher cap, never above this
MAX_TOKENS_HARD_CEILING = 32_000
STOP_REASONS = frozenset({"end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "pause_turn"})

#: per task class (ai-routing.md section 2): default effort, max_tokens cap, request timeout in seconds
TASK_DEFAULTS: dict[str, tuple[str, int, float]] = {
    "routing": ("low", 1_024, 10.0),
    "phrasing": ("low", 1_200, 15.0),
    "orchestration": ("medium", 8_192, 60.0),
    "escalation": ("medium", 16_000, 90.0),
    "vision": ("low", 2_048, 20.0),
    "verify": ("low", 16, 10.0),
}


# ---- circuit breaker ---------------------------------------------------------------------------------------------
class CircuitBreaker:
    """Opens after ``threshold`` failures within ``window_seconds``; stays open ``open_seconds``; then half-open."""

    def __init__(
        self, *, threshold: int = 5, window_seconds: float = 120.0, open_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: list[float] = []
        self._opened_at: float | None = None

    def _prune(self, now: float) -> None:
        self._failures = [t for t in self._failures if now - t <= self.window_seconds]

    @property
    def state(self) -> str:
        with self._lock:
            now = self._clock()
            if self._opened_at is not None:
                return "open" if now - self._opened_at < self.open_seconds else "half_open"
            self._prune(now)
            return "closed"

    @property
    def recent_failures(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return len(self._failures)

    def allow(self) -> bool:
        return self.state != "open"

    def record_failure(self) -> None:
        with self._lock:
            now = self._clock()
            self._failures.append(now)
            self._prune(now)
            if len(self._failures) >= self.threshold:
                self._opened_at = now

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()
            self._opened_at = None

    def reset(self) -> None:
        self.record_success()

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "recent_failures": self.recent_failures, "threshold": self.threshold,
                "window_seconds": int(self.window_seconds), "open_seconds": int(self.open_seconds)}


BREAKER = CircuitBreaker()


def breaker_state() -> dict[str, Any]:
    return BREAKER.snapshot()


# ---- request rendering (pure) -------------------------------------------------------------------------------------
def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A strict-compatible copy of a JSON schema: every object closes ``additionalProperties`` and requires every
    property (optional fields stay nullable through their ``anyOf``/``null``)."""

    def walk(node: Any) -> Any:
        if isinstance(node, Mapping):
            out = {k: walk(v) for k, v in node.items()}
            if out.get("type") == "object" or "properties" in out:
                props = out.get("properties") or {}
                out["properties"] = {k: walk(v) for k, v in props.items()}
                out["required"] = sorted(props)
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(dict(schema))


def is_strict_compatible(schema: Mapping[str, Any]) -> bool:
    """Every object in the schema closes additionalProperties and lists all of its properties as required."""

    def check(node: Any) -> bool:
        if isinstance(node, Mapping):
            if node.get("type") == "object" or "properties" in node:
                props = node.get("properties") or {}
                if node.get("additionalProperties") is not False or set(node.get("required") or []) != set(props):
                    return False
            return all(check(v) for v in node.values())
        if isinstance(node, list):
            return all(check(v) for v in node)
        return True

    return check(schema)


def render_tools(tools: Sequence[ToolSpec], strict_names: Iterable[str]) -> list[dict[str, Any]]:
    """Tools sorted by name (deterministic prefix); strict definitions within the budget; ``cache_control`` on the
    last tool."""
    strict = set(strict_names)
    out: list[dict[str, Any]] = []
    strict_used = 0
    for tool in sorted(tools, key=lambda t: t.name):
        definition: dict[str, Any] = {"name": tool.name, "description": tool.description}
        if tool.name in strict and strict_used < STRICT_TOOL_BUDGET:
            definition["input_schema"] = strict_schema(tool.input_schema)
            definition["strict"] = True
            strict_used += 1
        else:
            definition["input_schema"] = dict(tool.input_schema)
        out.append(definition)
    if out:
        out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


def render_system(request: ModelRequest) -> list[dict[str, Any]]:
    """The versioned system prompt is the cached breakpoint; the volatile facts follow it uncached."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]
    if request.context:
        facts = json.dumps(request.context, sort_keys=True, default=str, ensure_ascii=False)
        blocks.append({"type": "text", "text": f"Context facts (server-verified, JSON):\n{facts}"})
    return blocks


def render_messages(messages: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        content: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                if block.text:
                    content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)})
            elif isinstance(block, ToolResultBlock):
                content.append({
                    "type": "tool_result", "tool_use_id": block.tool_use_id,
                    "content": json.dumps(block.content, default=str, ensure_ascii=False), "is_error": block.is_error,
                })
            elif isinstance(block, OpaqueBlock):
                content.append(dict(block.payload))
        if content:
            out.append({"role": message.role, "content": content})
    return out


def model_family(model: str) -> str:
    lowered = model.lower()
    for family in ("haiku", "sonnet", "opus"):
        if family in lowered:
            return family
    return "other"


def supports_server_fallback(model: str) -> bool:
    return model_family(model) in ("sonnet", "opus")


def build_params(request: ModelRequest, model: str, max_tokens: int) -> dict[str, Any]:
    """The Messages API body for a request (deterministic for equal inputs; what the contract test inspects)."""
    effort = request.effort or TASK_DEFAULTS.get(request.task_class, ("medium", 8192, 60.0))[0]
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": render_system(request),
        "messages": render_messages(request.messages),
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
    if request.output_schema is not None:
        params["output_config"]["format"] = {"type": "json_schema", "schema": dict(request.output_schema)}
    if request.tools:
        params["tools"] = render_tools(request.tools, request.strict_tools)
        params["tool_choice"] = {"type": "auto"}
    return params


def default_model(task_class: TaskClass, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return {
        "routing": settings.model_phrasing, "phrasing": settings.model_phrasing, "verify": settings.model_phrasing,
        "escalation": settings.model_escalation, "vision": settings.model_vision,
    }.get(task_class, settings.model_orchestrator)


# ---- response mapping -------------------------------------------------------------------------------------------
def _block_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, Mapping):
        return dict(block)
    dump = getattr(block, "model_dump", None)
    return dump(mode="json", exclude_none=True) if dump else dict(vars(block))


def parse_content(content: Sequence[Any]) -> tuple[list[TextBlock | ToolUseBlock | OpaqueBlock], bool]:
    """Typed blocks in order (never ``content[0]``); the flag says whether a ``fallback`` marker was present."""
    blocks: list[TextBlock | ToolUseBlock | OpaqueBlock] = []
    fallback = False
    for raw in content:
        data = _block_dict(raw)
        kind = str(data.get("type") or "")
        if kind == "text":
            blocks.append(TextBlock(str(data.get("text") or "")))
        elif kind == "tool_use":
            blocks.append(ToolUseBlock(id=str(data["id"]), name=str(data["name"]), input=dict(data.get("input") or {})))
        elif kind == "fallback":
            fallback = True
            blocks.append(OpaqueBlock(type=kind, payload=data))
        else:  # thinking, redacted_thinking, server tool blocks: replayed unchanged, never interpreted
            blocks.append(OpaqueBlock(type=kind or "unknown", payload=data))
    return blocks, fallback


def parse_usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    data = _block_dict(usage)
    return Usage(
        input_tokens=int(data.get("input_tokens") or 0), output_tokens=int(data.get("output_tokens") or 0),
        cache_read_tokens=int(data.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(data.get("cache_creation_input_tokens") or 0),
    )


def _fallback_in_usage(usage: Any) -> bool:
    data = _block_dict(usage) if usage is not None else {}
    return any((_block_dict(i).get("type") == "fallback_message") for i in (data.get("iterations") or []))


def to_response(message: Any, *, latency_ms: int, request_id: str | None) -> ModelResponse:
    blocks, fallback = parse_content(list(getattr(message, "content", None) or []))
    stop_reason = str(getattr(message, "stop_reason", None) or "end_turn")
    if stop_reason == "model_context_window_exceeded":
        raise ProviderError("The request exceeded the model context window.", code="context_window_exceeded",
                            request_id=request_id)
    if stop_reason not in STOP_REASONS:
        stop_reason = "end_turn"
    details = getattr(message, "stop_details", None)
    usage = getattr(message, "usage", None)
    return ModelResponse(
        provider=PROVIDER_NAME, model=str(getattr(message, "model", "") or ""), content=tuple(blocks),
        stop_reason=stop_reason, usage=parse_usage(usage), request_id=request_id, latency_ms=latency_ms,  # type: ignore[arg-type]
        stop_details=_block_dict(details) if details is not None and stop_reason == "refusal" else None,
        fallback_used=fallback or _fallback_in_usage(usage),
    )


def _retry_after(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def map_exception(exc: Exception) -> ProviderError:
    """Most specific first: NotFoundError → RateLimitError → APIStatusError → APIConnectionError."""
    import anthropic

    request_id = getattr(exc, "request_id", None)
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError(f"Model or endpoint not found: {exc.message}", code="model_not_found", request_id=request_id, status=404)
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("The provider is rate limiting requests.", code="rate_limited", request_id=request_id,
                             retry_after_seconds=_retry_after(getattr(exc, "response", None)), status=429)
    if isinstance(exc, anthropic.APIStatusError):
        status = int(getattr(exc, "status_code", 0) or 0)
        code = "provider_overloaded" if status == 529 else ("provider_request_rejected" if 400 <= status < 500 else "provider_error")
        return ProviderError(f"Provider error {status}: {exc.message}", code=code, request_id=request_id, status=status)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("The provider could not be reached.", code="provider_unreachable", request_id=request_id)
    return ProviderError(f"{type(exc).__name__}: {exc}", code="provider_unavailable", request_id=request_id)


# ---- the provider ------------------------------------------------------------------------------------------------
@dataclass
class AnthropicProvider:
    """Live Claude adapter. ``client`` is injectable (tests pass an SDK client over a fake HTTP transport)."""

    client: Any = None
    settings: Settings | None = None
    breaker: CircuitBreaker = field(default_factory=lambda: BREAKER)
    name: str = PROVIDER_NAME
    label: str = PROVIDER_LABEL
    #: the last request body sent (inspection in tests and the trace), never logged with user text elsewhere
    last_params: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.settings = self.settings or get_settings()
        if self.client is None:
            import anthropic

            key = self.settings.anthropic_api_key.get_secret_value()
            if not key:
                raise ProviderError("ANTHROPIC_API_KEY is not configured.", code="not_configured")
            self.client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES, timeout=TASK_DEFAULTS["orchestration"][2])

    @property
    def model(self) -> str:
        return default_model("orchestration", self.settings)

    def model_for(self, task_class: TaskClass, requested: str | None = None) -> str:
        return requested or default_model(task_class, self.settings)

    def _options(self, model: str, *, batch: bool = False) -> dict[str, Any]:
        if batch or not supports_server_fallback(model):
            return {}
        return {"extra_headers": {"anthropic-beta": FALLBACK_BETA}, "extra_body": {"fallbacks": "default"}}

    def _call(self, params: dict[str, Any], timeout: float) -> tuple[Any, str | None]:
        model = str(params["model"])
        try:
            message = self.client.with_options(timeout=timeout, max_retries=MAX_RETRIES).messages.create(
                **params, **self._options(model)
            )
        except Exception as exc:
            mapped = map_exception(exc)
            self.breaker.record_failure()
            raise mapped from exc
        self.breaker.record_success()
        return message, getattr(message, "_request_id", None)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self.breaker.allow():
            raise ProviderError("The AI provider circuit is open after repeated failures; try again shortly.",
                                code="circuit_open")
        effort, cap, timeout = TASK_DEFAULTS.get(request.task_class, TASK_DEFAULTS["orchestration"])
        model = self.model_for(request.task_class, request.model)
        max_tokens = min(request.max_tokens or cap, cap)
        clock = Stopwatch()
        params = build_params(request, model, max_tokens)
        self.last_params = params
        message, request_id = self._call(params, timeout)
        response = to_response(message, latency_ms=clock.elapsed_ms, request_id=request_id)
        if response.stop_reason == "max_tokens" and max_tokens < MAX_TOKENS_HARD_CEILING:
            retry = dict(params, max_tokens=min(max_tokens * 2, MAX_TOKENS_HARD_CEILING))
            self.last_params = retry
            message, request_id = self._call(retry, timeout)
            response = to_response(message, latency_ms=clock.elapsed_ms, request_id=request_id)
        continuations = 0
        while response.stop_reason == "pause_turn" and continuations < MAX_PAUSE_CONTINUATIONS:
            continuations += 1
            resumed = dict(params)
            resumed["messages"] = [*params["messages"], {"role": "assistant", "content": [_block_dict(b) for b in message.content]}]
            self.last_params = resumed
            message, request_id = self._call(resumed, timeout)
            response = to_response(message, latency_ms=clock.elapsed_ms, request_id=request_id)
        return response

    # ---- Message Batches (pre-shift phrasing; no fallbacks on batch requests) --------------------------------------
    def submit_batch(self, requests: Mapping[str, ModelRequest]) -> str:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        if not self.breaker.allow():
            raise ProviderError("The AI provider circuit is open.", code="circuit_open")
        items = []
        for custom_id, request in requests.items():
            _, cap, _ = TASK_DEFAULTS.get(request.task_class, TASK_DEFAULTS["phrasing"])
            params = build_params(request, self.model_for(request.task_class, request.model), min(request.max_tokens or cap, cap))
            items.append(Request(custom_id=custom_id, params=MessageCreateParamsNonStreaming(**params)))  # type: ignore[typeddict-item]
        try:
            batch = self.client.messages.batches.create(requests=items)
        except Exception as exc:
            self.breaker.record_failure()
            raise map_exception(exc) from exc
        return str(batch.id)

    def collect_batch(self, batch_id: str, *, wait_seconds: float = 0.0, poll_seconds: float = 5.0,
                      sleep: Callable[[float], None] = time.sleep) -> dict[str, ModelResponse | ProviderError] | None:
        """Results keyed by ``custom_id`` (any order), or None while the batch is still processing."""
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                batch = self.client.messages.batches.retrieve(batch_id)
            except Exception as exc:
                raise map_exception(exc) from exc
            if batch.processing_status == "ended":
                break
            if time.monotonic() >= deadline:
                return None
            sleep(poll_seconds)
        out: dict[str, ModelResponse | ProviderError] = {}
        for item in self.client.messages.batches.results(batch_id):
            result = item.result
            if result.type == "succeeded":
                out[item.custom_id] = to_response(result.message, latency_ms=0, request_id=getattr(result.message, "_request_id", None))
            else:
                out[item.custom_id] = ProviderError(f"batch item {result.type}", code=f"batch_{result.type}")
        return out

    # ---- verification (Graph-like: a minimal real call) ----------------------------------------------------------
    def verify(self) -> dict[str, Any]:
        from app.modules.agents.providers.base import Message

        request = ModelRequest(
            task_class="verify", system="verify.v1\nReply with the single word OK.", max_tokens=8, effort="low",
            messages=(Message(role="user", content=(TextBlock("Reply with the single word OK."),)),),
        )
        response = self.generate(request)
        return {"model": response.model, "request_id": response.request_id, "latency_ms": response.latency_ms,
                "text": response.text.strip()[:20]}


__all__ = [
    "BREAKER",
    "FALLBACK_BETA",
    "STRICT_TOOL_BUDGET",
    "TASK_DEFAULTS",
    "AnthropicProvider",
    "CircuitBreaker",
    "breaker_state",
    "build_params",
    "default_model",
    "is_strict_compatible",
    "map_exception",
    "parse_content",
    "render_tools",
    "strict_schema",
    "supports_server_fallback",
    "to_response",
]
