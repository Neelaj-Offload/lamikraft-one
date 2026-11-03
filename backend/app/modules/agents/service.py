"""Agents service: conversations, turns, runs (own scope only), the trace writers the orchestrator uses, and the
polling view. Every read is filtered by the conversation owner (``user_id = actor.user_id``): another user's
conversation or run is a 404, never a 403, so existence is not revealed.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.modules.agents import providers, quotas, routing
from app.modules.agents.cards import Card, dump_cards
from app.modules.agents.events import (
    JOB_KIND,
    RUN_COMPLETED,
    RUN_FAILED,
    RunCompletedPayload,
    RunFailedPayload,
    payload,
)
from app.modules.agents.models import AiCallLog, Conversation, ObjectContext, Receipt, Run, RunStep, Turn
from app.modules.agents.policies import ASSISTANT_USE
from app.modules.agents.providers.base import ModelResponse
from app.modules.agents.providers.demo import PROVIDER_LABEL
from app.modules.agents.schemas import (
    ConversationCreate,
    ConversationOut,
    RunDetail,
    RunSummary,
    SelectedOption,
    StepOut,
    TurnAccepted,
    TurnCreate,
    TurnOut,
)
from app.platform.jobs import runtime as jobs_runtime
from app.platform.uow import UnitOfWork

STEP_BUDGET = 8
TIME_BUDGET_SECONDS = 45
HISTORY_TURNS = 8
UNDO_WINDOW_HOURS = 24
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def ingress_correlation_id(actor_correlation_id: str | None) -> str:
    """The trace id (design section 13): the request's UUIDv7 correlation id when it is one, else a fresh UUIDv7."""
    if actor_correlation_id and _UUID.match(actor_correlation_id.strip()):
        return actor_correlation_id.strip().lower()
    return str(uuid.uuid7())


def _require_use(uow: UnitOfWork) -> None:
    uow.actor.require(ASSISTANT_USE)
    if uow.actor.user_id is None:
        raise Forbidden(code="permission_denied", permission=ASSISTANT_USE)


# ---- own-scope reads ---------------------------------------------------------------------------------------------
def own_conversation(uow: UnitOfWork, conversation_id: uuid.UUID, *, for_update: bool = False) -> Conversation:
    _require_use(uow)
    stmt = select(Conversation).where(
        Conversation.company_id == uow.actor.company_id,
        Conversation.id == conversation_id,
        Conversation.user_id == uow.actor.user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="agents.conversation")
    return row


def own_run(uow: UnitOfWork, run_id: uuid.UUID, *, for_update: bool = False) -> Run:
    _require_use(uow)
    stmt = select(Run).where(Run.company_id == uow.actor.company_id, Run.id == run_id, Run.user_id == uow.actor.user_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="agents.run")
    return row


def turns_of(uow: UnitOfWork, conversation_id: uuid.UUID, *, limit: int | None = None) -> list[Turn]:
    stmt = select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.seq.desc())
    if limit:
        stmt = stmt.limit(limit)
    rows = list(uow.session.scalars(stmt))
    rows.reverse()
    return rows


def runs_of(uow: UnitOfWork, conversation_id: uuid.UUID) -> list[Run]:
    return list(uow.session.scalars(select(Run).where(Run.conversation_id == conversation_id).order_by(Run.created_at, Run.id)))


def steps_after(uow: UnitOfWork, run_id: uuid.UUID, after_seq: int) -> list[RunStep]:
    return list(uow.session.scalars(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.seq > after_seq).order_by(RunStep.seq)
    ))


def last_assistant_turn(uow: UnitOfWork, conversation_id: uuid.UUID) -> Turn | None:
    return uow.session.scalars(
        select(Turn).where(Turn.conversation_id == conversation_id, Turn.role == "assistant").order_by(Turn.seq.desc()).limit(1)
    ).first()


# ---- commands ----------------------------------------------------------------------------------------------------
def create_conversation(uow: UnitOfWork, data: ConversationCreate) -> Conversation:
    _require_use(uow)
    conversation = Conversation(
        id=uuid.uuid7(),
        user_id=uow.actor.user_id,
        channel=data.channel.value,
        title=data.title,
        status="active",
        last_activity_at=uow.now(),
        turn_count=0,
    )
    uow.add(conversation)
    uow.flush()
    return conversation


def _offered_option(uow: UnitOfWork, conversation_id: uuid.UUID, option: SelectedOption) -> dict[str, Any]:
    """The option must be one the previous assistant turn offered on a ClarificationCard."""
    previous = last_assistant_turn(uow, conversation_id)
    for card in previous.cards if previous else []:
        if card.get("kind") != "clarification":
            continue
        for candidate in card.get("options") or []:
            action = candidate.get("action") or {}
            if action.get("slot") == option.slot and str(action.get("value")) == option.value:
                return {"slot": option.slot, "value": option.value, "label": action.get("label"), "data": action.get("data") or {}}
    raise ValidationFailed(
        "The selected option was not offered by the assistant's last question",
        code="option_not_offered",
        errors=[{"loc": ["body", "selected_option"], "msg": "not offered", "type": "option_not_offered"}],
    )


def create_turn(uow: UnitOfWork, conversation_id: uuid.UUID, data: TurnCreate) -> TurnAccepted:
    """Store the user turn, create the run and enqueue ``agent.run``; returns the accepted run (202)."""
    providers.check_configured()
    conversation = own_conversation(uow, conversation_id, for_update=True)
    if conversation.status != "active":
        raise ValidationFailed("The conversation is archived", code="conversation_archived")
    if data.client_utterance_id is not None:
        existing = uow.session.scalars(
            select(Turn).where(Turn.conversation_id == conversation.id, Turn.client_utterance_id == data.client_utterance_id)
        ).first()
        if existing is not None and existing.run_id is not None:
            run = uow.session.get(Run, existing.run_id)
            assert run is not None
            return TurnAccepted(run_id=run.id, turn_id=existing.id, conversation_id=conversation.id, status=run.status, replayed=True)  # type: ignore[arg-type]
    selected = _offered_option(uow, conversation.id, data.selected_option) if data.selected_option else None
    now = uow.now()
    conversation.turn_count += 1
    conversation.last_activity_at = now
    if conversation.title is None and data.text:
        conversation.title = data.text[:80]
    correlation_id = ingress_correlation_id(uow.actor.correlation_id)
    table = routing.resolve(uow)
    budget = table.budget("orchestration")
    # ai-routing.md section 7: quota checked before enqueue; over quota degrades to the deterministic path
    quota = quotas.check_orchestrator_quota(uow, table, conversation.user_id)
    turn = Turn(
        id=uuid.uuid7(),
        conversation_id=conversation.id,
        seq=conversation.turn_count,
        role="user",
        text=data.text,
        screen_context=data.context.for_storage() if data.context else None,
        selected_option=selected,
        cards=[],
        client_utterance_id=data.client_utterance_id,
        correlation_id=correlation_id,
    )
    run = Run(
        id=uuid.uuid7(),
        conversation_id=conversation.id,
        turn_id=turn.id,
        user_id=conversation.user_id,
        status="queued",
        trigger="clarification_answer" if selected else "user_turn",
        channel=conversation.channel,
        provider=providers.ai_mode() if providers.ai_mode() == "demo" else "anthropic",
        step_budget=budget["steps"],
        time_budget_seconds=budget["seconds"],
        input_token_budget=budget["input_tokens"],
        correlation_id=correlation_id,
        degraded_reason=None if quota.allowed else quota.reason,
    )
    turn.run_id = run.id
    uow.add(turn)
    uow.flush()  # the run's FK points at the turn (no relationship() declared, so flush order is explicit)
    uow.add(run)
    uow.flush()
    run.job_id = uow.enqueue(JOB_KIND, {"run_id": str(run.id)}, resource_type="agents.run", resource_id=run.id)
    return TurnAccepted(run_id=run.id, turn_id=turn.id, conversation_id=conversation.id, status="queued")  # type: ignore[arg-type]


def cancel_run(uow: UnitOfWork, run_id: uuid.UUID) -> Run:
    run = own_run(uow, run_id, for_update=True)
    now = uow.now()
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = now
        run.error_code = "cancelled"
    if run.status in ("running", "cancelled") and run.cancel_requested_at is None:
        run.cancel_requested_at = now
    if run.job_id is not None and run.status in ("running", "cancelled"):
        jobs_runtime.cancel(uow.session, run.job_id, uow.actor.user_id)
    return run


# ---- trace writers (used by the orchestrator, as the member) ----------------------------------------------------
def append_step(
    uow: UnitOfWork,
    run: Run,
    *,
    kind: str,
    name: str,
    input: Mapping[str, Any] | None = None,
    output: Mapping[str, Any] | None = None,
    is_error: bool = False,
    error_code: str | None = None,
    model_route: str | None = None,
    duration_ms: int = 0,
) -> RunStep:
    run.step_count += 1
    if kind == "tool_call":
        run.tool_call_count += 1
    if model_route:
        run.model_route = model_route
    step = RunStep(
        id=uuid.uuid7(),
        run_id=run.id,
        seq=run.step_count,
        kind=kind,
        name=name[:120],
        input=dict(input) if input is not None else None,
        output=dict(output) if output is not None else None,
        is_error=is_error,
        error_code=error_code,
        model_route=model_route,
        duration_ms=duration_ms,
        correlation_id=run.correlation_id,
        created_at=uow.now(),
    )
    uow.add(step)
    uow.flush()
    return step


WORKFLOW_OF_TASK = {"orchestration": "orchestrate", "routing": "route", "escalation": "escalate", "phrasing": "phrase",
                    "verify": "verify", "vision": "vision"}


def log_call(
    uow: UnitOfWork, run: Run | None, *, step_seq: int | None, response: ModelResponse | None, task_class: str,
    error: Exception | None = None, provider: str = "demo", model: str = "", user_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
) -> AiCallLog:
    """One row per provider call in the single usage store (``agents_ai_call_log``); cost is never stored."""
    refusal = response is not None and response.stop_reason == "refusal"
    row = AiCallLog(
        id=uuid.uuid7(),
        run_id=run.id if run is not None else None,
        step_seq=step_seq,
        workflow=WORKFLOW_OF_TASK.get(task_class, "orchestrate"),
        provider=response.provider if response else provider,
        model=(response.model if response else model)[:80],
        task_class=task_class,
        input_tokens=response.usage.input_tokens if response else 0,
        output_tokens=response.usage.output_tokens if response else 0,
        cache_read_tokens=response.usage.cache_read_tokens if response else 0,
        cache_write_tokens=response.usage.cache_write_tokens if response else 0,
        latency_ms=response.latency_ms if response else 0,
        outcome="refusal" if refusal else ("ok" if error is None else "error"),
        error_type=(getattr(error, "code", None) or type(error).__name__) if error else None,
        request_id=(response.request_id if response else getattr(error, "request_id", None)),
        user_id=user_id if user_id is not None else (run.user_id if run is not None else None),
        correlation_id=correlation_id or (run.correlation_id if run is not None else None),
        created_at=uow.now(),
    )
    if run is not None and response is not None:
        run.input_tokens_used += response.usage.input_tokens + response.usage.cache_read_tokens
    uow.add(row)
    return row


# ---- receipts (design section 9 "Undo") --------------------------------------------------------------------------
def record_receipt(
    uow: UnitOfWork, run: Run, *, step_seq: int, action: str, summary: str, resource_type: str,
    resource_id: uuid.UUID, resource_version: int | None, undo_kind: str, undo_spec: Mapping[str, Any] | None,
) -> Receipt:
    receipt = Receipt(
        id=uuid.uuid7(), run_id=run.id, user_id=run.user_id, step_seq=step_seq, action=action[:80], summary=summary[:300],
        resource_type=resource_type[:80], resource_id=resource_id, resource_version=resource_version,
        undo_kind=undo_kind, undo_spec=dict(undo_spec) if undo_spec else None,
        undo_until=uow.now() + timedelta(hours=UNDO_WINDOW_HOURS) if undo_kind != "none" else None,
        status="active", correlation_id=run.correlation_id,
    )
    uow.add(receipt)
    uow.flush()
    return receipt


def own_receipt(uow: UnitOfWork, receipt_id: uuid.UUID, *, for_update: bool = False) -> Receipt:
    _require_use(uow)
    stmt = select(Receipt).where(Receipt.company_id == uow.actor.company_id, Receipt.id == receipt_id, Receipt.user_id == uow.actor.user_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = uow.session.scalars(stmt).first()
    if row is None:
        raise NotFound(code="not_found", resource_type="agents.receipt")
    return row


def add_object_context(uow: UnitOfWork, run: Run, refs: Sequence[Any]) -> None:
    existing = {
        (r.resource_type, r.resource_id, r.origin)
        for r in uow.session.scalars(select(ObjectContext).where(ObjectContext.run_id == run.id))
    }
    for ref in refs:
        key = (ref.resource_type, ref.resource_id, ref.origin)
        if key in existing:
            continue
        existing.add(key)
        uow.add(ObjectContext(
            id=uuid.uuid7(), run_id=run.id, resource_type=ref.resource_type[:80], resource_id=ref.resource_id,
            version=ref.version, origin=ref.origin, ref_key=ref.ref_key, list_key=ref.list_key, ordinal=ref.ordinal,
            label=(ref.label or None) and str(ref.label)[:200], created_at=uow.now(),
        ))


def finish_run(
    uow: UnitOfWork, run: Run, *, status: str, text: str, cards: list[Card], error_code: str | None = None,
    error_message: str | None = None, elapsed_ms: int | None = None,
) -> Turn:
    """Write the assistant turn with its cards, close the run and emit the completed/failed event."""
    conversation = uow.session.get(Conversation, run.conversation_id)
    assert conversation is not None
    now = uow.now()
    conversation.turn_count += 1
    conversation.last_activity_at = now
    turn = Turn(
        id=uuid.uuid7(), conversation_id=conversation.id, seq=conversation.turn_count, role="assistant", text=text,
        cards=dump_cards(cards), run_id=run.id, correlation_id=run.correlation_id,
    )
    uow.add(turn)
    run.status = status
    run.finished_at = now
    run.error_code = error_code
    run.error_message = (error_message or None) and str(error_message)[:500]
    run.assistant_turn_id = turn.id
    run.elapsed_ms = elapsed_ms
    uow.flush()
    if status == "succeeded":
        uow.emit(RUN_COMPLETED, aggregate_id=run.id, payload=payload(RunCompletedPayload(
            run_id=run.id, conversation_id=run.conversation_id, user_id=run.user_id, trigger=run.trigger, status=status,
        )))
    else:
        uow.emit(RUN_FAILED, aggregate_id=run.id, payload=payload(RunFailedPayload(
            run_id=run.id, conversation_id=run.conversation_id, error_code=error_code or status,
        )))
    return turn


# ---- views -------------------------------------------------------------------------------------------------------
def _mode() -> str:
    return providers.ai_mode()


def run_summary(run: Run) -> RunSummary:
    return RunSummary(
        id=run.id, conversation_id=run.conversation_id, turn_id=run.turn_id, assistant_turn_id=run.assistant_turn_id,
        status=run.status, trigger=run.trigger, channel=run.channel, provider=run.provider,  # type: ignore[arg-type]
        provider_label=PROVIDER_LABEL if run.provider == "demo" else providers.provider_label(), mode=_mode(),
        model_route=run.model_route, request_type=run.request_type, tainted=run.tainted, error_code=run.error_code,
        error_message=run.error_message, step_count=run.step_count, tool_call_count=run.tool_call_count,
        step_budget=run.step_budget, time_budget_seconds=run.time_budget_seconds, elapsed_ms=run.elapsed_ms,
        started_at=run.started_at, finished_at=run.finished_at, created_at=run.created_at,
        correlation_id=run.correlation_id, degraded_reason=run.degraded_reason,
        input_token_budget=run.input_token_budget, input_tokens_used=run.input_tokens_used,
    )


def _turn_out(turn: Turn) -> TurnOut:
    return TurnOut(
        id=turn.id, seq=turn.seq, role=turn.role, text=turn.text, cards=turn.cards, run_id=turn.run_id,  # type: ignore[arg-type]
        selected_option=turn.selected_option, created_at=turn.created_at,
    )


def _step_out(step: RunStep) -> StepOut:
    return StepOut(
        seq=step.seq, kind=step.kind, name=step.name, input=step.input, output=step.output, is_error=step.is_error,  # type: ignore[arg-type]
        error_code=step.error_code, model_route=step.model_route, duration_ms=step.duration_ms, at=step.created_at,
    )


def get_run(uow: UnitOfWork, run_id: uuid.UUID, *, after_seq: int = 0) -> RunDetail:
    run = own_run(uow, run_id)
    steps = steps_after(uow, run.id, after_seq)
    done = run.status in ("succeeded", "failed", "budget_exceeded", "cancelled")
    text: str | None = None
    cards: list[Any] = []
    if run.assistant_turn_id is not None:
        turn = uow.session.get(Turn, run.assistant_turn_id)
        if turn is not None:
            text, cards = turn.text, turn.cards
    return RunDetail(
        run=run_summary(run), steps=[_step_out(s) for s in steps], after_seq=after_seq,
        last_seq=max([after_seq, *[s.seq for s in steps]]), done=done, text=text, cards=cards,
    )


def get_conversation(uow: UnitOfWork, conversation_id: uuid.UUID) -> ConversationOut:
    conversation = own_conversation(uow, conversation_id)
    return ConversationOut(
        id=conversation.id, channel=conversation.channel, title=conversation.title, status=conversation.status,  # type: ignore[arg-type]
        provider_label=providers.provider_label(), mode=_mode(), last_activity_at=conversation.last_activity_at,
        created_at=conversation.created_at, version=conversation.version,
        turns=[_turn_out(t) for t in turns_of(uow, conversation.id)],
        runs=[run_summary(r) for r in runs_of(uow, conversation.id)],
    )
