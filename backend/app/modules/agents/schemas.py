"""Request and response models of the agents API, and the structured screen context (ai-routing.md section 4.1).

Money and quantities are ``DecimalStr``. The screen context is a hint only: it is validated here for shape and
size (<= 16 KB, <= 50 visible items), then every referenced record is re-read by ``context.ground_screen_context``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.money import DecimalStr
from app.modules.agents.cards import Card

MAX_TURN_TEXT = 4_000
MAX_CONTEXT_BYTES = 16 * 1024
MAX_VISIBLE_ITEMS = 50
MAX_RECORDS = 50


class ConversationChannel(StrEnum):
    WEB = "web"
    VOICE = "voice"
    WHATSAPP = "whatsapp"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class TurnRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TurnInputMode(StrEnum):
    """How a user turn arrived. ``wa_*`` modes belong to WhatsApp conversations only."""

    TEXT = "text"
    VOICE = "voice"
    WA_TEXT = "wa_text"
    WA_VOICE = "wa_voice"
    CARD_ACTION = "card_action"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"


class RunTrigger(StrEnum):
    USER_TURN = "user_turn"
    CLARIFICATION_ANSWER = "clarification_answer"


class StepKind(StrEnum):
    ROUTE = "route"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CARD = "card"
    TEXT = "text"
    HANDOFF = "handoff"


class ContextOrigin(StrEnum):
    SCREEN = "screen"
    TOOL = "tool"
    CARD = "card"


class ProviderName(StrEnum):
    DEMO = "demo"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class CallOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    REFUSAL = "refusal"


RequestType = Literal["command", "screen_question", "visual_extraction", "data_or_action", "analysis", "out_of_scope"]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
RefKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
ResourceType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]


# ---- screen context (section 4.1) -----------------------------------------------------------------------------
class RouteContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: Annotated[str, StringConstraints(max_length=300)]
    params: dict[str, Annotated[str, StringConstraints(max_length=200)]] = Field(default_factory=dict)
    area: Annotated[str, StringConstraints(max_length=40)] | None = None


class RecordRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: ResourceType
    id: uuid.UUID
    version: int | None = None
    role: Annotated[str, StringConstraints(max_length=40)] | None = None


class VisibleItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: RefKey
    list_key: Annotated[str, StringConstraints(max_length=80)]
    ordinal: int = Field(ge=1, le=10_000)
    type: ResourceType
    id: uuid.UUID
    version: int | None = None


class DraftContext(BaseModel):
    """The user's unsaved form input: never persisted from context, re-validated by the receiving service."""

    model_config = ConfigDict(extra="ignore")

    form_key: Annotated[str, StringConstraints(max_length=80)]
    record_ref: Annotated[str, StringConstraints(max_length=80)] | None = None
    dirty_fields: list[Annotated[str, StringConstraints(max_length=80)]] = Field(default_factory=list, max_length=100)
    values: dict[str, Any] = Field(default_factory=dict)


class BriefingPin(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pin_id: uuid.UUID
    version: int | None = None


class Viewport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    width: int = Field(ge=0, le=20_000)
    height: int = Field(ge=0, le=20_000)


class ScreenContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal[1] = 1
    captured_at: datetime | None = None
    route: RouteContext | None = None
    focus: RecordRef | None = None
    records: list[RecordRef] = Field(default_factory=list, max_length=MAX_RECORDS)
    visible_items: list[VisibleItem] = Field(default_factory=list, max_length=MAX_VISIBLE_ITEMS)
    selection: list[RefKey] = Field(default_factory=list, max_length=MAX_VISIBLE_ITEMS)
    filters: dict[str, Any] = Field(default_factory=dict)
    draft: DraftContext | None = None
    briefing_pin: BriefingPin | None = None
    viewport: Viewport | None = None

    @model_validator(mode="after")
    def _size(self) -> ScreenContext:
        size = len(json.dumps(self.model_dump(mode="json"), separators=(",", ":")).encode())
        if size > MAX_CONTEXT_BYTES:
            raise ValueError(f"screen context is {size} bytes; the limit is {MAX_CONTEXT_BYTES} (trim to the focused list)")
        return self

    def for_storage(self) -> dict[str, Any]:
        """The context as stored on the turn: draft values are the user's input and are never persisted."""
        data = self.model_dump(mode="json")
        if data.get("draft"):
            data["draft"]["values"] = {}
        return data


# ---- requests ------------------------------------------------------------------------------------------------
class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: ConversationChannel = ConversationChannel.WEB
    title: Short | None = None


class SelectedOption(BaseModel):
    """A ClarificationCard option the user chose; must have been offered by the previous assistant turn."""

    model_config = ConfigDict(extra="forbid")

    slot: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(max_length=MAX_TURN_TEXT)] = ""
    context: ScreenContext | None = None
    selected_option: SelectedOption | None = None
    client_utterance_id: uuid.UUID | None = None
    input_mode: TurnInputMode = TurnInputMode.TEXT
    #: a confirmed vision extraction (``POST /vision/extractions/{id}/confirm``) the run may use; the run is tainted
    extraction_id: uuid.UUID | None = None

    @field_validator("text")
    @classmethod
    def _not_blank_without_option(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _text_or_option(self) -> TurnCreate:
        if not self.text and self.selected_option is None:
            raise ValueError("text is required unless an option is selected")
        return self


# ---- responses -----------------------------------------------------------------------------------------------
class TurnOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: TurnRole
    text: str
    cards: list[Card]
    run_id: uuid.UUID | None
    selected_option: dict[str, Any] | None
    input_mode: TurnInputMode = TurnInputMode.TEXT
    #: a correction after submission names the earlier user turn it corrects (voice)
    corrects_turn_id: uuid.UUID | None = None
    extraction_id: uuid.UUID | None = None
    created_at: datetime


class RunSummary(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    assistant_turn_id: uuid.UUID | None
    status: RunStatus
    trigger: RunTrigger
    channel: str
    provider: ProviderName
    provider_label: str
    mode: str
    model_route: str | None
    request_type: str | None
    tainted: bool
    error_code: str | None
    error_message: str | None
    step_count: int
    tool_call_count: int
    step_budget: int
    time_budget_seconds: int
    elapsed_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    #: Slice 3: the trace id, quota degradation and the input-token budget
    correlation_id: str | None = None
    degraded_reason: str | None = None
    input_token_budget: int = 0
    input_tokens_used: int = 0


class StepOut(BaseModel):
    seq: int
    kind: StepKind
    name: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    is_error: bool
    error_code: str | None
    model_route: str | None
    duration_ms: int
    at: datetime


class RunDetail(BaseModel):
    """The polling payload: run status, steps after ``after_seq`` and, once finished, the assistant text and cards."""

    run: RunSummary
    steps: list[StepOut]
    after_seq: int
    last_seq: int
    done: bool
    text: str | None
    cards: list[Card]


class TurnAccepted(BaseModel):
    run_id: uuid.UUID
    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    status: RunStatus
    replayed: bool = False


# ---- Slice 3: receipts, trace, admin ----------------------------------------------------------------------------
class ReceiptOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    step_seq: int
    action: str
    summary: str
    resource_type: str
    resource_id: uuid.UUID
    resource_version: int | None
    undo_kind: str
    undo_until: datetime | None
    status: str
    undone_at: datetime | None
    correlation_id: str | None
    created_at: datetime
    #: server-decided: active, within the window and the target unchanged
    can_undo: bool


class UndoResult(BaseModel):
    receipt: ReceiptOut
    #: what the undo did, as a card the composer can show
    card: Card


class TraceEntry(BaseModel):
    """One redacted timeline entry: kinds ``turn``, ``run``, ``step``, ``ai_call``, ``receipt``, ``event``, ``audit``."""

    at: datetime
    kind: str
    name: str
    status: str | None = None
    actor_user_id: uuid.UUID | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class TraceOut(BaseModel):
    correlation_id: str
    #: ``participant`` (own run) or ``auditor`` (``audit.trace.read``)
    access: str
    run_ids: list[uuid.UUID]
    entries: list[TraceEntry]
    redacted: bool = True


class AiProviderStatus(BaseModel):
    mode: str
    provider: str
    label: str
    #: demo | verified | failing | not_verified | misconfigured
    state: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    last_error_code: str | None
    circuit: dict[str, Any]
    readiness: str


class AiStatusOut(BaseModel):
    provider: AiProviderStatus
    models: dict[str, str]
    effort: dict[str, str]
    budgets: dict[str, dict[str, int]]
    quotas: dict[str, int]
    price_currency: str
    prices: list[dict[str, Any]]
    dpdp: dict[str, Any]
    dpdp_text: str
    can_manage_routing: bool


class AiWorkflowUsage(BaseModel):
    workflow: str
    calls: int
    runs: int
    errors: int
    refusals: int
    #: 0..1 as a DecimalStr (two decimals of a percentage are shown client-side from this)
    error_rate: DecimalStr
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    #: estimated at report time from the price table; None when a model has no price row
    estimated_cost: DecimalStr | None


class AiFailure(BaseModel):
    at: datetime
    workflow: str
    provider: str
    model: str
    outcome: str
    error_type: str | None
    request_id: str | None
    run_id: uuid.UUID | None
    correlation_id: str | None


class AiUsageOut(BaseModel):
    window_days: int
    window_from: datetime
    window_to: datetime
    price_currency: str
    cost_is_estimate: bool = True
    totals: AiWorkflowUsage
    by_workflow: list[AiWorkflowUsage]
    by_model: list[dict[str, Any]]
    failures: list[AiFailure]


class AiVerifyCheck(BaseModel):
    key: str
    mode: str
    state: str
    verified_at: datetime | None
    last_error_code: str | None
    details: dict[str, Any] | None


class AiVerifyOut(AiVerifyCheck):
    """The ``ai.anthropic`` result at the top level (Slice 3 shape) plus ``ai.gemini`` (vision) when registered."""

    vision: AiVerifyCheck | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    channel: ConversationChannel
    title: str | None
    status: ConversationStatus
    provider_label: str
    mode: str
    last_activity_at: datetime
    created_at: datetime
    version: int
    turns: list[TurnOut]
    runs: list[RunSummary]


__all__ = [
    "MAX_CONTEXT_BYTES",
    "MAX_TURN_TEXT",
    "MAX_VISIBLE_ITEMS",
    "BriefingPin",
    "CallOutcome",
    "ContextOrigin",
    "ConversationChannel",
    "ConversationCreate",
    "ConversationOut",
    "ConversationStatus",
    "DraftContext",
    "ProviderName",
    "RecordRef",
    "RequestType",
    "RouteContext",
    "RunDetail",
    "RunStatus",
    "RunSummary",
    "RunTrigger",
    "ReceiptOut",
    "ScreenContext",
    "TraceEntry",
    "TraceOut",
    "UndoResult",
    "AiFailure",
    "AiProviderStatus",
    "AiStatusOut",
    "AiUsageOut",
    "AiVerifyOut",
    "AiWorkflowUsage",
    "SelectedOption",
    "StepKind",
    "StepOut",
    "TurnAccepted",
    "TurnCreate",
    "TurnOut",
    "TurnRole",
    "VisibleItem",
    "Viewport",
]
