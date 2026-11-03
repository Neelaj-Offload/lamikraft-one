"""Quotas (ai-routing.md section 7): per user and per workflow per day, checked before a run is enqueued.

Counting reads ``agents_run`` (orchestrator runs per user, escalations per user and per company) over the current
company day (the company time zone's calendar day). Over quota never blocks the assistant: the run is enqueued
``degraded`` so the deterministic grammar still answers, and anything that needs a model ends with a clear
``quota_exceeded`` ErrorCard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.modules.agents.models import AiCallLog, Run
from app.modules.agents.routing import RoutingTable

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

QUOTA_EXCEEDED = "quota_exceeded"


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    workflow: str
    used: int
    limit: int
    reason: str | None = None

    @property
    def message(self) -> str:
        return (f"The daily assistant quota for {self.workflow} is used up ({self.used}/{self.limit}). Direct commands "
                "still work; the full assistant is available again tomorrow.")


def company_day_start(uow: UnitOfWork) -> datetime:
    """Midnight of the current day in the company's time zone."""
    from app.platform.org.models import Company

    zone_name = uow.session.scalar(select(Company.default_time_zone).where(Company.id == uow.actor.company_id))
    zone = ZoneInfo(zone_name or "Asia/Kolkata")
    local = uow.now().astimezone(zone)
    return datetime.combine(local.date(), time.min, tzinfo=zone)


def runs_today(uow: UnitOfWork, *, user_id: uuid.UUID | None, request_type: str | None = None, model_route_prefix: str | None = None) -> int:
    start = company_day_start(uow)
    stmt = select(func.count()).select_from(Run).where(Run.company_id == uow.actor.company_id, Run.created_at >= start,
                                                        Run.degraded_reason.is_(None))
    if user_id is not None:
        stmt = stmt.where(Run.user_id == user_id)
    if request_type is not None:
        stmt = stmt.where(Run.request_type == request_type)
    if model_route_prefix is not None:
        stmt = stmt.where(Run.model_route.like(f"{model_route_prefix}%"))
    return int(uow.session.execute(stmt).scalar_one())


def calls_today(uow: UnitOfWork, *, user_id: uuid.UUID | None, workflow: str, distinct_runs: bool = False) -> int:
    """Provider calls of a workflow today, or (``distinct_runs``) the runs that made at least one such call."""
    start = company_day_start(uow)
    counted = func.count(AiCallLog.run_id.distinct()) if distinct_runs else func.count()
    stmt = select(counted).select_from(AiCallLog).where(
        AiCallLog.company_id == uow.actor.company_id, AiCallLog.created_at >= start, AiCallLog.workflow == workflow
    )
    if user_id is not None:
        stmt = stmt.where(AiCallLog.user_id == user_id)
    return int(uow.session.execute(stmt).scalar_one())


def check_orchestrator_quota(uow: UnitOfWork, table: RoutingTable, user_id: uuid.UUID) -> QuotaDecision:
    limit = int(table.quotas.get("orchestrator_runs_per_user", 0))
    used = runs_today(uow, user_id=user_id)
    return QuotaDecision(allowed=used < limit, workflow="orchestrator runs", used=used, limit=limit,
                         reason=None if used < limit else QUOTA_EXCEEDED)


def check_escalation_quota(uow: UnitOfWork, table: RoutingTable, user_id: uuid.UUID) -> QuotaDecision:
    """Per user and per company (section 2: the per-company daily Opus cap)."""
    user_limit = int(table.quotas.get("escalations_per_user", 0))
    company_limit = int(table.quotas.get("company_escalations", 0))
    user_used = calls_today(uow, user_id=user_id, workflow="escalate", distinct_runs=True)
    company_used = calls_today(uow, user_id=None, workflow="escalate", distinct_runs=True)
    if user_used >= user_limit:
        return QuotaDecision(False, "escalations", user_used, user_limit, QUOTA_EXCEEDED)
    if company_used >= company_limit:
        return QuotaDecision(False, "company escalations", company_used, company_limit, "company_escalation_cap")
    return QuotaDecision(True, "escalations", user_used, user_limit)


def quota_window_end(uow: UnitOfWork) -> datetime:
    return company_day_start(uow) + timedelta(days=1)


__all__ = ["QUOTA_EXCEEDED", "QuotaDecision", "calls_today", "check_escalation_quota", "check_orchestrator_quota", "runs_today"]
