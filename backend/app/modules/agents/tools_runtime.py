"""Tool execution for agent runs: ``ToolContext`` around the server-built actor, grounding before any service call,
permission checks as the member, one unit of work per call, redaction of outputs for the model.

Order of checks for every call (each failure is an ``is_error`` step, never an exception):
1. the tool is registered (else ``capability_not_installed``) and not hidden by taint;
2. provenance sidecars are stripped and verified (quantities, price override), prices are rejected as inputs;
3. every id in the input is one this run has seen (``id_provenance``);
4. the input validates against the ToolDef input model (``extra="forbid"``);
5. the actor holds the tool's permission (``permission_denied``, 403 semantics; services check again);
6. the handler runs as the member in its own transaction (draft tools with an idempotency key per step).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError, Forbidden
from app.core.logging import get_logger
from app.modules.agents.grounding import (
    GroundingError,
    Provenance,
    decimals_in,
    ground_input,
    is_untrusted,
    uuids_in,
)
from app.platform.authz.context import ActorContext
from app.platform.authz.redaction import redact
from app.platform.tools import ToolDef
from app.platform.uow import UnitOfWork

log = get_logger("lk.agents.tools")
META_TOOLS = frozenset({"ask_clarification"})
PRICE_OVERRIDE_PERMISSION = "sales.quote_price.override"


@dataclass(frozen=True)
class ToolContext:
    """What a tool call runs with: the member's context (never settable by the model) and the run's provenance."""

    actor: ActorContext
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    step_seq: int
    provenance: Provenance
    tainted: bool = False


@dataclass
class ToolOutcome:
    name: str
    input: dict[str, Any]
    is_error: bool
    error_code: str | None = None
    message: str | None = None
    status: int | None = None
    output_for_model: dict[str, Any] | None = None
    output_for_user: dict[str, Any] | None = None
    duration_ms: int = 0
    untrusted: bool = False
    effect: str | None = None

    @property
    def result_content(self) -> dict[str, Any]:
        """The ``tool_result`` block content the provider sees."""
        if self.is_error:
            return {"name": self.name, "ok": False, "error": {"code": self.error_code, "message": self.message}}
        return {"name": self.name, "ok": True, "output": self.output_for_model}

    @property
    def new_ids(self) -> set[uuid.UUID]:
        return uuids_in(self.output_for_model) if self.output_for_model is not None else set()

    @property
    def new_values(self) -> set[Any]:
        return decimals_in(self.output_for_model) if self.output_for_model is not None else set()


def registered_tools() -> dict[str, ToolDef]:
    from app.registry import get_registry

    return {t.name: t for t in get_registry().tools}


def hidden_when_tainted(tool: ToolDef) -> bool:
    """External-send tools are hidden for the rest of a tainted run."""
    return tool.name.startswith("send_") or (tool.effect == "propose" and "send" in tool.name)


def advertised_tools(actor: ActorContext, *, tainted: bool = False) -> list[ToolDef]:
    """Tools the model may be told about: registered, permitted for this actor, allowed under taint."""
    out = []
    for tool in sorted(registered_tools().values(), key=lambda t: t.name):
        if tool.permission and not actor.can(tool.permission):
            continue
        if tainted and hidden_when_tainted(tool):
            continue
        out.append(tool)
    return out


def _error(name: str, data: Mapping[str, Any], code: str, message: str, status: int | None, started: float) -> ToolOutcome:
    return ToolOutcome(
        name=name, input=dict(data), is_error=True, error_code=code, message=message[:500], status=status,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def execute_tool(ctx: ToolContext, name: str, raw_input: Mapping[str, Any]) -> ToolOutcome:
    started = time.perf_counter()
    tool = registered_tools().get(name)
    if tool is None:
        return _error(name, raw_input, "capability_not_installed", f"The capability {name!r} is not installed.", 501, started)
    if ctx.tainted and hidden_when_tainted(tool):
        return _error(name, raw_input, "tool_hidden_tainted", "External-send tools are hidden for a tainted run.", 403, started)
    try:
        grounded = ground_input(raw_input, ctx.provenance)
    except GroundingError as exc:
        return _error(name, raw_input, exc.code, exc.message, 422, started)
    try:
        data = tool.input_model.model_validate(grounded.data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        return _error(name, grounded.data, "invalid_input", f"Input does not match {name}: {problems}", 422, started)
    if tool.permission and not ctx.actor.can(tool.permission):
        return _error(name, grounded.data, "permission_denied", f"You do not hold {tool.permission}.", 403, started)
    if grounded.price_override is not None and not ctx.actor.can(PRICE_OVERRIDE_PERMISSION):
        return _error(name, grounded.data, "permission_denied", f"You do not hold {PRICE_OVERRIDE_PERMISSION}.", 403, started)
    needs_key = tool.requires_idempotency or tool.effect in ("draft", "propose")
    actor = ctx.actor.with_(
        agent_run_id=ctx.run_id,
        idempotency_key=f"agent:{ctx.run_id}:{ctx.step_seq}" if needs_key else None,
    )
    try:
        with UnitOfWork(actor) as uow:
            result = tool.handler(uow, data)
            for_model = redact(result, actor, for_model=True)
            for_user = redact(result, actor)
            model_dump = for_model.model_dump(mode="json") if isinstance(for_model, BaseModel) else dict(for_model)
            user_dump = for_user.model_dump(mode="json") if isinstance(for_user, BaseModel) else dict(for_user)
    except Forbidden as exc:
        return _error(name, data.model_dump(mode="json"), exc.code or "permission_denied", exc.detail, 403, started)
    except AppError as exc:
        return _error(name, data.model_dump(mode="json"), exc.code, exc.detail, exc.status, started)
    except Exception as exc:  # the step fails; the run decides what to do
        log.exception("agents.tool_failed", tool=name, run_id=str(ctx.run_id), error_type=type(exc).__name__)
        return _error(name, data.model_dump(mode="json"), "tool_failed", f"{type(exc).__name__}: {exc}", 500, started)
    return ToolOutcome(
        name=name,
        input=data.model_dump(mode="json"),
        is_error=False,
        output_for_model=model_dump,
        output_for_user=user_dump,
        duration_ms=int((time.perf_counter() - started) * 1000),
        untrusted=is_untrusted(model_dump),
        effect=tool.effect,
    )
