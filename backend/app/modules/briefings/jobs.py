"""Briefing jobs: per-member refresh after task facts change, precompute ahead of shift start, phrasing of a new
version (now, or through the provider's batch path for a precomputed one) and the daily WhatsApp summary."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.platform.authz.context import ActorContext
from app.platform.jobs.defs import JobDef, ScheduleDef
from app.platform.jobs.runtime import JobContext
from app.platform.uow import UnitOfWork

PRECOMPUTE_INTERVAL_SECONDS = 300
SUMMARY_INTERVAL_SECONDS = 300
#: a running phrasing batch is collected every minute for at most an hour, then phrased call by call
COLLECT_DELAY_SECONDS = 60
COLLECT_MAX_ATTEMPTS = 60


def refresh_user(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.briefings import service

    user_id = uuid.UUID(payload["user_id"])
    cause = str(payload.get("cause") or "event_update")
    events = [str(payload["cause_event_id"])] if payload.get("cause_event_id") else []
    version = service.refresh_member(ctx.uow, user_id, cause=cause, cause_event_ids=events)
    return {"user_id": str(user_id), "version": version.version if version is not None else None}


def precompute_company(uow: UnitOfWork) -> int:
    """Members whose shift precompute instant has passed and whose shift has not started yet."""
    from app.modules.briefings import service
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import view_as

    now = uow.now()
    created = 0
    for user_id in responsibility.active_member_ids(uow):
        actor = responsibility.member_actor(uow, user_id)
        if actor is None or not actor.can("briefings.briefing.read"):
            continue
        member = view_as(uow, actor)
        cal = responsibility.user_calendar(member, user_id)
        work_date = cal.work_date(now)
        if cal.day_type(work_date) != "working":
            continue  # no precompute or push on non-working days
        shift_start, _ = cal.shift_bounds(work_date)
        if cal.precompute_at(work_date) <= now < shift_start and service.precompute_for(member, user_id, cal, work_date):
            created += 1
    return created


def _each_company(ctx: JobContext, reason: str, fn: Any) -> int:
    from app.platform.org.models import Company

    if ctx.uow.actor.company_id is not None:
        return int(fn(ctx.uow))
    total = 0
    companies = list(ctx.uow.session.scalars(select(Company.id).where(Company.status == "active").order_by(Company.id)))
    for company_id in companies:
        with UnitOfWork(ActorContext.system(company_id, reason=reason)) as uow:
            total += int(fn(uow))
    return total


def precompute_due_shifts(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    return {"created": _each_company(ctx, "briefings.precompute", precompute_company)}


# ---- phrasing ---------------------------------------------------------------------------------------------------------
def _member_uow(uow: UnitOfWork, user_id: uuid.UUID) -> UnitOfWork | None:
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import view_as

    actor = responsibility.member_actor(uow, user_id)
    if actor is None or not actor.can("briefings.briefing.read"):
        return None
    return view_as(uow, actor)


def _version_of(uow: UnitOfWork, payload: dict[str, Any]) -> tuple[Any, Any] | None:
    from app.modules.briefings.models import Briefing, BriefingVersion

    briefing = uow.session.get(Briefing, uuid.UUID(payload["briefing_id"]))
    if briefing is None or briefing.company_id != uow.actor.company_id:
        return None
    version = uow.session.scalars(
        select(BriefingVersion).where(BriefingVersion.briefing_id == briefing.id, BriefingVersion.version == int(payload["version"]))
    ).first()
    return (briefing, version) if version is not None else None


def _collect_later(uow: UnitOfWork, payload: dict[str, Any], briefing: Any, version: Any, attempt: int) -> None:
    uow.enqueue(
        "briefings.collect_phrasing", {**payload, "attempt": attempt},
        run_at=uow.now() + timedelta(seconds=COLLECT_DELAY_SECONDS),
        dedupe_key=f"brf-collect:{version.id}:{attempt}", resource_type="briefings.briefing", resource_id=briefing.id,
    )


def phrase_version(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Phrase one version as its member (the call log records who; quotas apply per user)."""
    from app.modules.briefings import phrasing

    member = _member_uow(ctx.uow, uuid.UUID(payload["user_id"]))
    found = _version_of(ctx.uow, payload) if member is not None else None
    if member is None or found is None:
        return {"phrased": False}
    briefing, version = found
    current = phrasing.version_text(member, version.id)
    if current is not None and current.status == "ready" and not phrasing.outage_only(current):
        return {"phrased": False, "reason": "already_phrased"}
    if payload.get("mode") == "batch":
        row, state = phrasing.submit_version_batch(member, briefing, version)
        if state is not None:
            _collect_later(ctx.uow, {**payload, "state": state}, briefing, version, 1)
            return {"phrased": False, "batch_id": state.get("batch_id")}
        return {"phrased": True, "ai_status": row.ai_status, "batch": True}
    row = phrasing.phrase_version(member, briefing, version)
    return {"phrased": True, "ai_status": row.ai_status}


def collect_phrasing(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.briefings import phrasing

    member = _member_uow(ctx.uow, uuid.UUID(payload["user_id"]))
    found = _version_of(ctx.uow, payload) if member is not None else None
    if member is None or found is None:
        return {"collected": False}
    briefing, version = found
    attempt = int(payload.get("attempt") or 1)
    row = phrasing.collect_version_batch(member, briefing, version, dict(payload.get("state") or {}))
    if row is not None:
        return {"collected": True, "ai_status": row.ai_status}
    if attempt >= COLLECT_MAX_ATTEMPTS:  # the batch never ended: phrase call by call instead
        row = phrasing.phrase_version(member, briefing, version)
        return {"collected": True, "ai_status": row.ai_status, "fallback": "per_call"}
    _collect_later(ctx.uow, payload, briefing, version, attempt + 1)
    return {"collected": False, "attempt": attempt}


# ---- the daily WhatsApp summary -------------------------------------------------------------------------------------
def whatsapp_summary(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """The member's daily summary (idempotent per work date; skipped with the recorded reason when not eligible)."""
    from app.modules.briefings import summary

    user_id = uuid.UUID(payload["user_id"])
    member = _member_uow(ctx.uow, user_id)
    if member is None:
        return {"outcome": "skipped", "reason": "not_a_member"}
    row = summary.send_summary(member, user_id)
    return {"outcome": row.outcome, "reason": row.reason}


def summaries_due_company(uow: UnitOfWork) -> int:
    """Members with a linked WhatsApp identity whose shift has started today and who have no summary yet."""
    from app.modules.briefings import summary
    from app.modules.channels.models import ChannelIdentity
    from app.modules.tasks import responsibility
    from app.modules.tasks.visibility import view_as

    now = uow.now()
    queued = 0
    users = sorted(set(uow.session.scalars(
        select(ChannelIdentity.user_id).where(
            ChannelIdentity.company_id == uow.actor.company_id, ChannelIdentity.kind == "employee",
            ChannelIdentity.status == "active", ChannelIdentity.user_id.is_not(None),
        )
    )))
    for user_id in users:
        actor = responsibility.member_actor(uow, user_id)
        if actor is None or not actor.can("briefings.briefing.read"):
            continue
        member = view_as(uow, actor)
        cal = responsibility.user_calendar(member, user_id)
        work_date = cal.work_date(now)
        if cal.day_type(work_date) != "working" or summary.existing(member, user_id, work_date) is not None:
            continue  # no push on non-working days; one summary per work date
        shift_start, shift_end = cal.shift_bounds(work_date)
        if shift_start <= now < shift_end:
            uow.enqueue("briefings.whatsapp_summary", {"user_id": str(user_id)},
                        dedupe_key=f"brf-summary:{user_id}:{work_date.isoformat()}", resource_type="identity.user", resource_id=user_id)
            queued += 1
    return queued


def whatsapp_summaries_due(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    return {"queued": _each_company(ctx, "briefings.whatsapp_summary", summaries_due_company)}


JOBS = [
    JobDef("briefings.refresh_user", refresh_user, queue="briefings", max_attempts=5),
    JobDef("briefings.precompute_due_shifts", precompute_due_shifts, queue="briefings", max_attempts=3),
    JobDef("briefings.phrase_version", phrase_version, queue="briefings", max_attempts=3),
    JobDef("briefings.collect_phrasing", collect_phrasing, queue="briefings", max_attempts=3),
    JobDef("briefings.whatsapp_summary", whatsapp_summary, queue="briefings", max_attempts=3),
    JobDef("briefings.whatsapp_summaries_due", whatsapp_summaries_due, queue="briefings", max_attempts=3),
]
SCHEDULES = [
    ScheduleDef("briefings.precompute_due_shifts", "briefings.precompute_due_shifts", "interval",
                interval_seconds=PRECOMPUTE_INTERVAL_SECONDS),
    ScheduleDef("briefings.whatsapp_summaries_due", "briefings.whatsapp_summaries_due", "interval",
                interval_seconds=SUMMARY_INTERVAL_SECONDS),
]
