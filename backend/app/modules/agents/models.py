"""Agent tables (prefix ``agents_``): conversations, turns, runs, run steps, object context and the AI call log.

``agents_run_step`` and ``agents_ai_call_log`` are append-only (trigger in the migration). Every table is a tenant
table with forced RLS. Redacted tool inputs/outputs are stored as JSONB written through Pydantic models in the
service; the raw screen context is stored without the user's draft values (they are never persisted from context).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, TenantEntity, TenantMixin, VersionMixin

CONVERSATION_CHANNELS = ("web", "voice", "whatsapp")
#: how a user turn arrived (design agent_voice_whatsapp.md: agents_turn.input_mode); assistant turns are "text"
TURN_INPUT_MODES = ("text", "voice", "wa_text", "wa_voice", "card_action")
CONVERSATION_STATUSES = ("active", "archived")
TURN_ROLES = ("user", "assistant")
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "budget_exceeded", "cancelled")
RUN_TRIGGERS = ("user_turn", "clarification_answer")
STEP_KINDS = ("route", "tool_call", "tool_result", "card", "text", "handoff")
CONTEXT_ORIGINS = ("screen", "tool", "card")
PROVIDERS = ("demo", "anthropic", "gemini")
CALL_OUTCOMES = ("ok", "error", "refusal")
WORKFLOWS = ("orchestrate", "route", "escalate", "phrase", "verify", "vision")
RECEIPT_STATUSES = ("active", "undone", "expired", "target_changed")
UNDO_KINDS = ("revert_draft", "restore_line", "none")


class Conversation(TenantEntity, VersionMixin, Base):
    __tablename__ = "agents_conversation"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: the next user turn sequence number (turns are numbered 1..n per conversation)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("channel IN ('web','voice','whatsapp')", name="channel_values"),
        CheckConstraint("status IN ('active','archived')", name="status_values"),
        Index("ix_agents_conversation_owner", "company_id", "user_id", "last_activity_at"),
    )


class Turn(TenantEntity, Base):
    __tablename__ = "agents_turn"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_conversation.id", ondelete="RESTRICT"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: validated screen context (docs/architecture/ai-routing.md section 4.1) without draft values
    screen_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: a ClarificationCard option chosen by the user ({slot, value, label})
    selected_option: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: server-built cards of an assistant turn (list of card JSON with a ``kind`` discriminator)
    cards: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    #: the run that produced (assistant) or was triggered by (user) this turn
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    client_utterance_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    #: UUIDv7 created at ingress (Slice 3 trace); the run, steps, call-log rows and receipts carry the same value
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: one of TURN_INPUT_MODES; WhatsApp turns carry wa_text / wa_voice / card_action (Slice-3 stage-1 merge, 0018)
    input_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="text", server_default="text")

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="role_values"),
        CheckConstraint("input_mode IN ('text','voice','wa_text','wa_voice','card_action')", name="input_mode_values"),
        Index("uq_agents_turn_seq", "conversation_id", "seq", unique=True),
        Index("ix_agents_turn_run", "run_id"),
    )


class Run(TenantEntity, Base):
    __tablename__ = "agents_run"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_conversation.id", ondelete="RESTRICT"), nullable=False
    )
    #: the user turn that triggered the run
    turn_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_turn.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    trigger: Mapped[str] = mapped_column(String(30), nullable=False, default="user_turn")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="demo")
    #: the model route of the last step (per-step routes live on the steps)
    model_route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    time_budget_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tainted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: the assistant turn written when the run finished
    assistant_turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: input-token budget of the task class (ai-routing.md section 2) and what the provider calls consumed
    input_token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=120_000)
    input_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: set at enqueue when the run may only use deterministic paths (``quota_exceeded``), ai-routing.md section 7
    degraded_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','budget_exceeded','cancelled')", name="status_values"
        ),
        Index("ix_agents_run_correlation", "correlation_id"),
        CheckConstraint("trigger IN ('user_turn','clarification_answer')", name="trigger_values"),
        CheckConstraint("provider IN ('demo','anthropic','gemini')", name="provider_values"),
        Index("ix_agents_run_conversation", "conversation_id", "created_at"),
        Index("ix_agents_run_status", "company_id", "status", "created_at"),
        Index("uq_agents_run_turn", "turn_id", unique=True),
    )


class RunStep(IdMixin, TenantMixin, Base):
    """The tool receipt: one row per orchestrator step, redacted input and output, never updated."""

    __tablename__ = "agents_run_step"
    __append_only__ = True

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_run.id", ondelete="RESTRICT"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('route','tool_call','tool_result','card','text','handoff')", name="kind_values"
        ),
        Index("uq_agents_run_step_seq", "run_id", "seq", unique=True),
    )


class ObjectContext(IdMixin, TenantMixin, Base):
    """Records a run may reference: re-read screen refs (visible ones only), tool outputs and card actions."""

    __tablename__ = "agents_object_context"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_run.id", ondelete="RESTRICT"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    ref_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    list_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("origin IN ('screen','tool','card')", name="origin_values"),
        Index("ix_agents_object_context_run", "run_id", "resource_type", "resource_id"),
    )


class AiCallLog(IdMixin, TenantMixin, Base):
    """The single AI usage store (docs/PLAN.md ``ai_call_log``): one row per provider call, append-only.

    Cost is computed at report time from the configurable price table (Slice 3); never stored as money.
    """

    __tablename__ = "agents_ai_call_log"
    __append_only__ = True

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_run.id", ondelete="RESTRICT"), nullable=True
    )
    step_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow: Mapped[str] = mapped_column(String(30), nullable=False, default="orchestrate")
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    task_class: Mapped[str] = mapped_column(String(40), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: the user whose quota the call counts against (None for system/batch workflows)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("provider IN ('demo','anthropic','gemini')", name="provider_values"),
        CheckConstraint("outcome IN ('ok','error','refusal')", name="outcome_values"),
        Index("ix_agents_ai_call_log_usage", "company_id", "workflow", "created_at"),
        Index("ix_agents_ai_call_log_run", "run_id"),
        Index("ix_agents_ai_call_log_user_day", "company_id", "user_id", "created_at"),
    )


class Receipt(TenantEntity, VersionMixin, Base):
    """A draft receipt (design section 9 "Undo"): what an agent step wrote and how to revert it for 24 hours.

    ``undo_spec`` is server-built from the tool output (never model text): ``revert_draft`` archives the agent-created
    draft; ``restore_line`` puts the prior quantity back as a new version. Undo is refused once the target changed.
    """

    __tablename__ = "agents_receipt"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents_run.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    step_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    #: the target's row version right after the step; undo requires it to be unchanged
    resource_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    undo_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    undo_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    undo_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','undone','expired','target_changed')", name="status_values"),
        CheckConstraint("undo_kind IN ('revert_draft','restore_line','none')", name="undo_kind_values"),
        Index("ix_agents_receipt_run", "run_id", "step_seq"),
        Index("ix_agents_receipt_target", "company_id", "resource_type", "resource_id"),
    )


class PhrasingCache(IdMixin, TenantMixin, Base):
    """Phrased sentences keyed by the fact hash (facts + template version + language); unchanged items never
    regenerate (ai-routing.md section 7)."""

    __tablename__ = "agents_phrasing_cache"

    fact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template_code: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``model`` (validated model output) or ``template`` (the deterministic text, labelled "Standard wording")
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("source IN ('model','template')", name="source_values"),
        Index("uq_agents_phrasing_cache_hash", "company_id", "fact_hash", unique=True),
    )


__all__ = ["AiCallLog", "Conversation", "ObjectContext", "PhrasingCache", "Receipt", "Run", "RunStep", "Turn"]
