"""Provider-neutral model interface: ``generate(ModelRequest) -> ModelResponse`` over typed content blocks.

The orchestrator never sees provider payloads. A request carries the system text, the message history (user and
assistant turns; tool results travel as ``ToolResultBlock`` inside user messages, first and alone, as the Anthropic
Messages API requires), the advertised tools and structured ``context`` facts the adapter renders into its prompt
(the Demo provider reads them directly). A response is a list of content blocks iterated **by type** — never
``content[0]`` — plus the stop reason and usage. The Slice-3 Anthropic adapter maps these onto the SDK.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant"]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "refusal", "pause_turn"]
TaskClass = Literal["routing", "orchestration", "phrasing", "escalation", "vision", "verify"]
Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResultBlock:
    tool_use_id: str
    name: str
    content: Mapping[str, Any]
    is_error: bool = False


@dataclass(frozen=True)
class OpaqueBlock:
    """A provider block the orchestrator does not interpret (thinking, redacted_thinking, fallback markers).

    Passed back unchanged within the same run so the provider's reasoning stays valid; never persisted into the
    conversation history (a new run starts from redacted text history, ai-routing.md section 5.1).
    """

    type: str
    payload: Mapping[str, Any]


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | OpaqueBlock


@dataclass(frozen=True)
class Message:
    role: Role
    content: tuple[ContentBlock, ...]

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    effect: str


@dataclass(frozen=True)
class ModelRequest:
    task_class: TaskClass
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    model: str | None = None
    max_tokens: int = 1024
    #: structured facts (selected option, re-read focus, last cards, advertised tool names ...)
    context: Mapping[str, Any] = field(default_factory=dict)
    #: explicit ``output_config.effort`` (ai-routing.md section 2); None lets the adapter pick the class default
    effort: Effort | None = None
    #: a JSON schema the answer must follow (routing classifier, phrasing); the adapter maps it to structured output
    output_schema: Mapping[str, Any] | None = None
    #: names of tools whose definitions are sent strict (write/proposal tools), within the strict-tool budget
    strict_tools: frozenset[str] = frozenset()

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tools)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    content: tuple[TextBlock | ToolUseBlock | OpaqueBlock, ...]
    stop_reason: StopReason
    usage: Usage = Usage()
    request_id: str | None = None
    latency_ms: int = 0
    #: ``stop_details`` of a refusal ({category, explanation}); None otherwise
    stop_details: Mapping[str, Any] | None = None
    #: true when the provider served the reply through a server-side fallback model
    fallback_used: bool = False

    def iter_blocks(self) -> Iterator[TextBlock | ToolUseBlock | OpaqueBlock]:
        yield from self.content

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


class ProviderError(Exception):
    """A provider could not answer (outage, quota, refusal); the orchestrator degrades to deterministic paths."""

    def __init__(
        self, message: str, *, code: str = "provider_unavailable", request_id: str | None = None,
        retry_after_seconds: int | None = None, status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        self.status = status


class Provider(Protocol):
    name: str  # demo | anthropic | gemini (agents_ai_call_log.provider)
    label: str  # shown on every card ("Demo")

    def generate(self, request: ModelRequest) -> ModelResponse: ...


def tool_results(messages: Sequence[Message]) -> list[ToolResultBlock]:
    """Every tool result in the conversation so far, in order."""
    return [b for m in messages for b in m.content if isinstance(b, ToolResultBlock)]


def latest_user_text(messages: Sequence[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.text.strip():
            return message.text
    return ""


class Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
