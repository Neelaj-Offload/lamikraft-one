"""AI administration (ai-routing.md sections 7–8): provider status, usage from ``agents_ai_call_log`` and verification.

- ``status``: mode, provider state (Demo / Verified at / Failing / Not verified / Misconfigured), the circuit state,
  the effective routing table, quotas, the price table and the DPDP gate as text.
- ``usage``: per-workflow and per-model calls, distinct runs, errors and refusals, p50/p95 latency, tokens incl.
  cache read/write, failures with request ids. Cost is **estimated at report time** from the price table in the
  ``ai_routing`` setting; it is never stored as money and a model without a price row shows no estimate.
- ``verify``: the ``ai.anthropic`` verification routine (deterministic in demo, a minimal real call in live),
  recorded through the platform integration status (``system.integration.manage``).

The circuit breaker lives in the worker process, so the status derives the circuit from the call log with the
same rule (5 failures in 2 minutes opens it for 60 seconds) and adds the local snapshot when one exists.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select

from app.modules.agents import providers, routing
from app.modules.agents.models import AiCallLog
from app.modules.agents.policies import AI_ROUTING_MANAGE, AI_USAGE_READ
from app.modules.agents.schemas import (
    AiFailure,
    AiProviderStatus,
    AiStatusOut,
    AiUsageOut,
    AiVerifyOut,
    AiWorkflowUsage,
)
from app.platform.uow import UnitOfWork

INTEGRATION_KEY = "ai.anthropic"
BREAKER_FAILURES, BREAKER_WINDOW_S, BREAKER_OPEN_S = 5, 120, 60
MAX_WINDOW_DAYS = 90
MAX_FAILURES = 25


def _integration(uow: UnitOfWork) -> Any:
    from app.platform.system.service import effective_statuses

    return next((s for s in effective_statuses(uow) if s.key == INTEGRATION_KEY), None)


def circuit_from_log(uow: UnitOfWork) -> dict[str, Any]:
    now = uow.now()
    rows = list(uow.session.scalars(
        select(AiCallLog.created_at).where(
            AiCallLog.company_id == uow.actor.company_id, AiCallLog.provider != "demo", AiCallLog.outcome == "error",
            AiCallLog.created_at >= now - timedelta(seconds=BREAKER_WINDOW_S),
        ).order_by(AiCallLog.created_at.desc())
    ))
    state = "closed"
    if len(rows) >= BREAKER_FAILURES and (now - rows[0]).total_seconds() < BREAKER_OPEN_S:
        state = "open"
    out: dict[str, Any] = {"state": state, "recent_failures": len(rows), "window_seconds": BREAKER_WINDOW_S,
                           "open_seconds": BREAKER_OPEN_S, "source": "call_log"}
    if providers.ai_mode() == "live":
        from app.modules.agents.providers.anthropic import breaker_state

        out["process"] = breaker_state()
    return out


def _dpdp_text(table: routing.RoutingTable) -> str:
    dpdp = table.dpdp
    if dpdp.approved:
        parts = [f"Approved on {dpdp.approved_on}" if dpdp.approved_on else "Approved"]
        if dpdp.approved_by:
            parts.append(f"by {dpdp.approved_by}")
        if dpdp.decision_ref:
            parts.append(f"({dpdp.decision_ref})")
        text = " ".join(parts) + "."
        if dpdp.scope:
            text += f" Scope: {dpdp.scope}"
        return text
    if table.mode == "live":
        return ("Not recorded. Live AI is running without a recorded DPDP approval; record the owner's approval, date "
                "and scope before using live AI in production.")
    return ("Not recorded. Demo mode sends nothing to Anthropic or Google; live AI stays off in production until the "
            "owner records approval under India's DPDP Act.")


def provider_status(uow: UnitOfWork) -> AiProviderStatus:
    mode = providers.ai_mode()
    integration = _integration(uow)
    circuit = circuit_from_log(uow)
    verified_at = getattr(integration, "verified_at", None)
    last_checked_at = getattr(integration, "last_checked_at", None)
    error_code = getattr(integration, "last_error_code", None)
    if mode != "live":
        state = "demo"
    elif providers.key_missing():
        state, error_code = "misconfigured", "secret_missing"
    elif circuit["state"] == "open" or getattr(integration, "state", None) == "error":
        state = "failing"
    elif verified_at is not None:
        state = "verified"
    else:
        state = "not_verified"
    return AiProviderStatus(
        mode=mode, provider="demo" if mode != "live" else "anthropic", label=providers.provider_label(), state=state,
        verified_at=verified_at, last_checked_at=last_checked_at, last_error_code=error_code, circuit=circuit,
        readiness=providers.readiness(),
    )


def get_status(uow: UnitOfWork) -> AiStatusOut:
    uow.actor.require(AI_USAGE_READ)
    table = routing.resolve(uow)
    data = table.as_dict()
    return AiStatusOut(
        provider=provider_status(uow), models=data["models"], effort=data["effort"], budgets=data["budgets"],
        quotas=data["quotas"], price_currency=data["price_currency"], prices=data["prices"], dpdp=data["dpdp"],
        dpdp_text=_dpdp_text(table), can_manage_routing=uow.actor.can(AI_ROUTING_MANAGE),
    )


def _rate(part: int, whole: int) -> Decimal:
    return (Decimal(part) / Decimal(whole)).quantize(Decimal("0.0001")) if whole else Decimal("0")


def _cost(table: routing.RoutingTable, rows: list[dict[str, Any]]) -> Decimal | None:
    """Sum of per-model estimates; None when any model with tokens has no price row (no partial guess)."""
    total = Decimal("0")
    for row in rows:
        tokens = row["input_tokens"] + row["output_tokens"] + row["cache_read_tokens"] + row["cache_write_tokens"]
        if row["provider"] == "demo" or tokens == 0:
            continue
        estimate = table.estimate_usd(row["model"], input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
                                      cache_read=row["cache_read_tokens"], cache_write=row["cache_write_tokens"])
        if estimate is None:
            return None
        total += estimate
    return total.quantize(Decimal("0.000001"))


def get_usage(uow: UnitOfWork, *, days: int = 7) -> AiUsageOut:
    uow.actor.require(AI_USAGE_READ)
    days = max(1, min(int(days), MAX_WINDOW_DAYS))
    table = routing.resolve(uow)
    now = uow.now()
    start = now - timedelta(days=days)
    base = (AiCallLog.company_id == uow.actor.company_id, AiCallLog.created_at >= start, AiCallLog.created_at <= now)
    err = func.sum(case((AiCallLog.outcome == "error", 1), else_=0))
    ref = func.sum(case((AiCallLog.outcome == "refusal", 1), else_=0))
    group = list(uow.session.execute(
        select(
            AiCallLog.workflow, AiCallLog.provider, AiCallLog.model, func.count(), func.count(AiCallLog.run_id.distinct()),
            err, ref, func.sum(AiCallLog.input_tokens), func.sum(AiCallLog.output_tokens),
            func.sum(AiCallLog.cache_read_tokens), func.sum(AiCallLog.cache_write_tokens),
        ).where(*base).group_by(AiCallLog.workflow, AiCallLog.provider, AiCallLog.model)
    ))
    rows = [
        {"workflow": w, "provider": p, "model": m, "calls": int(c), "runs": int(r), "errors": int(e or 0),
         "refusals": int(f or 0), "input_tokens": int(i or 0), "output_tokens": int(o or 0),
         "cache_read_tokens": int(cr or 0), "cache_write_tokens": int(cw or 0)}
        for w, p, m, c, r, e, f, i, o, cr, cw in group
    ]
    pct = select(
        AiCallLog.workflow,
        func.percentile_cont(0.5).within_group(AiCallLog.latency_ms),
        func.percentile_cont(0.95).within_group(AiCallLog.latency_ms),
        func.count(AiCallLog.run_id.distinct()),
    ).where(*base).group_by(AiCallLog.workflow)
    latency = {w: (p50, p95, int(runs)) for w, p50, p95, runs in uow.session.execute(pct)}
    totals_pct = uow.session.execute(select(
        func.percentile_cont(0.5).within_group(AiCallLog.latency_ms),
        func.percentile_cont(0.95).within_group(AiCallLog.latency_ms),
        func.count(AiCallLog.run_id.distinct()),
    ).where(*base)).one()

    def summarise(name: str, subset: list[dict[str, Any]], p50: Any, p95: Any, runs: int) -> AiWorkflowUsage:
        calls = sum(r["calls"] for r in subset)
        errors = sum(r["errors"] for r in subset)
        return AiWorkflowUsage(
            workflow=name, calls=calls, runs=runs, errors=errors, refusals=sum(r["refusals"] for r in subset),
            error_rate=_rate(errors, calls), p50_latency_ms=None if p50 is None else int(round(p50)),
            p95_latency_ms=None if p95 is None else int(round(p95)),
            input_tokens=sum(r["input_tokens"] for r in subset), output_tokens=sum(r["output_tokens"] for r in subset),
            cache_read_tokens=sum(r["cache_read_tokens"] for r in subset),
            cache_write_tokens=sum(r["cache_write_tokens"] for r in subset), estimated_cost=_cost(table, subset),
        )

    workflows = sorted({r["workflow"] for r in rows})
    by_workflow = [summarise(w, [r for r in rows if r["workflow"] == w], *latency.get(w, (None, None, 0))) for w in workflows]
    by_model = []
    for (provider, model) in sorted({(r["provider"], r["model"]) for r in rows}):
        subset = [r for r in rows if r["provider"] == provider and r["model"] == model]
        by_model.append({
            "provider": provider, "model": model, "calls": sum(r["calls"] for r in subset),
            "input_tokens": sum(r["input_tokens"] for r in subset), "output_tokens": sum(r["output_tokens"] for r in subset),
            "cache_read_tokens": sum(r["cache_read_tokens"] for r in subset),
            "cache_write_tokens": sum(r["cache_write_tokens"] for r in subset),
            "estimated_cost": (str(c) if (c := _cost(table, subset)) is not None else None),
            "priced": provider == "demo" or table.price_for(model) is not None,
        })
    failures = [
        AiFailure(at=row.created_at, workflow=row.workflow, provider=row.provider, model=row.model, outcome=row.outcome,
                  error_type=row.error_type, request_id=row.request_id, run_id=row.run_id, correlation_id=row.correlation_id)
        for row in uow.session.scalars(
            select(AiCallLog).where(*base, AiCallLog.outcome != "ok").order_by(AiCallLog.created_at.desc()).limit(MAX_FAILURES)
        )
    ]
    return AiUsageOut(
        window_days=days, window_from=start, window_to=now, price_currency="USD", cost_is_estimate=True,
        totals=summarise("all", rows, totals_pct[0], totals_pct[1], int(totals_pct[2])),
        by_workflow=by_workflow, by_model=by_model, failures=failures,
    )


def verify(uow: UnitOfWork) -> AiVerifyOut:
    from app.platform.system.service import run_verification

    providers.register()
    result = run_verification(uow, INTEGRATION_KEY)
    return AiVerifyOut(key=result.key, mode=result.mode, state=result.state, verified_at=result.verified_at,
                       last_error_code=result.last_error_code, details=result.details)


__all__ = ["circuit_from_log", "get_status", "get_usage", "provider_status", "verify"]
