"""Durable job queue (Postgres, FOR UPDATE SKIP LOCKED, leases, fenced completion)."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, SmallInteger, String, Time, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "dead", "cancelled")


class Job(IdMixin, Base):
    __tablename__ = "job"
    __tenant_rls__ = False

    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    queue: Mapped[str] = mapped_column(String(40), nullable=False, default="default")
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_history: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','dead','cancelled')", name="status_values"
        ),
        Index("ix_job_claim", "queue", "priority", "run_at", postgresql_where=text("status = 'queued'")),
        Index("ix_job_lease", "lease_expires_at", postgresql_where=text("status = 'running'")),
        Index("ix_job_company_kind", "company_id", "kind", "created_at"),
        Index("ix_job_resource", "resource_type", "resource_id"),
    )


class JobSchedule(IdMixin, Base):
    __tablename__ = "job_schedule"
    __tenant_rls__ = False

    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    schedule_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    schedule_type: Mapped[str] = mapped_column(String(10), nullable=False)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("schedule_type IN ('interval','daily')", name="schedule_type_values"),
        CheckConstraint(
            "(schedule_type = 'interval' AND interval_seconds > 0) OR (schedule_type = 'daily' AND daily_time IS NOT NULL)",
            name="schedule_shape",
        ),
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"
    __tenant_rls__ = False

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    queues: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    running: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
