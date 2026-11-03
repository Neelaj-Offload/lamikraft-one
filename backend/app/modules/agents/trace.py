"""The trace view (design section 13): one UUIDv7 ``correlation_id`` from ingress through turn → run → steps →
AI calls → receipts → outbox events and audit entries.

``GET /api/v1/traces/{correlation_id}`` returns a **redacted** timeline: names, kinds, statuses, error codes,
model routes, token counts, durations and ids — never turn text, tool inputs/outputs, prompts or card bodies.
Visible to participants (the owner of a run in the trace) and to holders of ``audit.trace.read`` (MFA); anyone else
gets a 404 so the existence of a trace is not revealed.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select

from app.core.errors import NotFound
from app.modules.agents.models import AiCallLog, Receipt, Run, RunStep, Turn
from app.modules.agents.policies import TRACE_READ
from app.modules.agents.schemas import TraceEntry, TraceOut
from app.platform.uow import UnitOfWork

MAX_ENTRIES = 500
_CORRELATION = re.compile(r"^[A-Za-z0-9._:\-]{8,64}$")


def _not_found() -> NotFound:
    return NotFound(code="not_found", resource_type="trace")


def _platform_rows(uow: UnitOfWork, correlation_id: str) -> list[TraceEntry]:
    """Outbox events and audit entries carrying the same correlation id (company-scoped)."""
    from app.platform.audit.models import AuditLog
    from app.platform.events.models import DomainEvent

    company_id = uow.actor.company_id
    entries: list[TraceEntry] = []
    for evt in uow.session.scalars(
        select(DomainEvent).where(DomainEvent.company_id == company_id, DomainEvent.correlation_id == correlation_id)
        .order_by(DomainEvent.seq).limit(MAX_ENTRIES)
    ):
        entries.append(TraceEntry(
            at=evt.occurred_at, kind="event", name=evt.event_type, status="dispatched" if evt.dispatched_at else "pending",
            actor_user_id=evt.actor_user_id, ref_type=evt.aggregate_type, ref_id=str(evt.aggregate_id) if evt.aggregate_id else None,
            detail={"event_id": str(evt.id), "aggregate_version": evt.aggregate_version, "actor_type": evt.actor_type},
        ))
    for row in uow.session.scalars(
        select(AuditLog).where(AuditLog.company_id == company_id, AuditLog.correlation_id == correlation_id)
        .order_by(AuditLog.occurred_at, AuditLog.id).limit(MAX_ENTRIES)
    ):
        entries.append(TraceEntry(
            at=row.occurred_at, kind="audit", name=row.action, status=row.outcome, actor_user_id=row.actor_user_id,
            ref_type=row.resource_type, ref_id=str(row.resource_id) if row.resource_id else None,
            detail={"audit_id": str(row.id), "actor_type": row.actor_type},
        ))
    return entries


def _run_entries(run: Run) -> list[TraceEntry]:
    out = [TraceEntry(
        at=run.created_at, kind="run", name="agent.run", status="queued", actor_user_id=run.user_id,
        ref_type="agents.run", ref_id=str(run.id),
        detail={"trigger": run.trigger, "channel": run.channel, "provider": run.provider, "job_id": str(run.job_id) if run.job_id else None},
    )]
    if run.finished_at is not None:
        out.append(TraceEntry(
            at=run.finished_at, kind="run", name="agent.run.finished", status=run.status, actor_user_id=run.user_id,
            ref_type="agents.run", ref_id=str(run.id),
            detail={"request_type": run.request_type, "model_route": run.model_route, "error_code": run.error_code,
                    "steps": run.step_count, "tool_calls": run.tool_call_count, "elapsed_ms": run.elapsed_ms,
                    "tainted": run.tainted, "degraded_reason": run.degraded_reason,
                    "input_tokens_used": run.input_tokens_used, "input_token_budget": run.input_token_budget},
        ))
    return out


def get_trace(uow: UnitOfWork, correlation_id: str) -> TraceOut:
    actor = uow.actor
    if actor.user_id is None or not _CORRELATION.match(correlation_id or ""):
        raise _not_found()
    company_id = actor.company_id
    runs = list(uow.session.scalars(
        select(Run).where(Run.company_id == company_id, Run.correlation_id == correlation_id).order_by(Run.created_at)
    ))
    participant = any(r.user_id == actor.user_id for r in runs)
    auditor = actor.can(TRACE_READ)
    if not runs or not (participant or auditor):
        raise _not_found()
    run_ids = [r.id for r in runs]
    entries: list[TraceEntry] = []
    for turn in uow.session.scalars(
        select(Turn).where(Turn.company_id == company_id, Turn.correlation_id == correlation_id).order_by(Turn.created_at, Turn.seq)
    ):
        entries.append(TraceEntry(
            at=turn.created_at, kind="turn", name=f"turn.{turn.role}", ref_type="agents.turn", ref_id=str(turn.id),
            detail={"seq": turn.seq, "text_length": len(turn.text or ""), "cards": [c.get("kind") for c in (turn.cards or []) if isinstance(c, dict)],
                    "has_screen_context": turn.screen_context is not None},
        ))
    for run in runs:
        entries.extend(_run_entries(run))
    for step in uow.session.scalars(
        select(RunStep).where(RunStep.run_id.in_(run_ids)).order_by(RunStep.run_id, RunStep.seq)
    ):
        entries.append(TraceEntry(
            at=step.created_at, kind="step", name=step.name, status="error" if step.is_error else "ok",
            ref_type="agents.run_step", ref_id=f"{step.run_id}:{step.seq}",
            detail={"seq": step.seq, "step_kind": step.kind, "error_code": step.error_code, "model_route": step.model_route,
                    "duration_ms": step.duration_ms},
        ))
    for call in uow.session.scalars(
        select(AiCallLog).where(AiCallLog.run_id.in_(run_ids)).order_by(AiCallLog.created_at)
    ):
        entries.append(TraceEntry(
            at=call.created_at, kind="ai_call", name=f"{call.provider}:{call.workflow}", status=call.outcome,
            ref_type="agents.ai_call_log", ref_id=str(call.id),
            detail={"model": call.model, "task_class": call.task_class, "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens, "cache_read_tokens": call.cache_read_tokens,
                    "cache_write_tokens": call.cache_write_tokens, "latency_ms": call.latency_ms,
                    "error_type": call.error_type, "request_id": call.request_id, "step_seq": call.step_seq},
        ))
    for receipt in uow.session.scalars(select(Receipt).where(Receipt.run_id.in_(run_ids)).order_by(Receipt.created_at)):
        entries.append(TraceEntry(
            at=receipt.created_at, kind="receipt", name=receipt.action, status=receipt.status, actor_user_id=receipt.user_id,
            ref_type=receipt.resource_type, ref_id=str(receipt.resource_id),
            detail={"receipt_id": str(receipt.id), "undo_kind": receipt.undo_kind,
                    "undo_until": receipt.undo_until.isoformat() if receipt.undo_until else None,
                    "undone_at": receipt.undone_at.isoformat() if receipt.undone_at else None},
        ))
    entries.extend(_platform_rows(uow, correlation_id))
    entries.sort(key=_order)
    return TraceOut(correlation_id=correlation_id, access="participant" if participant else "auditor",
                    run_ids=run_ids, entries=entries[:MAX_ENTRIES], redacted=True)


_KIND_ORDER = {"turn": 0, "run": 1, "step": 2, "ai_call": 3, "receipt": 4, "event": 5, "audit": 6}


def _order(entry: TraceEntry) -> tuple[datetime, int, str]:
    return entry.at, _KIND_ORDER.get(entry.kind, 9), entry.name


__all__ = ["MAX_ENTRIES", "get_trace"]
