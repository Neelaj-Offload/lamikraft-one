"""Job kinds and schedules (declared per module; collected by the registry)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.platform.jobs.runtime import JobContext


@dataclass(frozen=True)
class JobDef:
    kind: str
    handler: Callable[[JobContext, dict[str, Any]], dict[str, Any] | None]
    queue: str = "default"
    max_attempts: int = 5
    lease_seconds: int = 300
    #: "system" runs as the company system actor; "user" rebuilds the enqueuing user's context
    run_as: str = "system"


@dataclass(frozen=True)
class ScheduleDef:
    schedule_key: str
    kind: str
    schedule_type: str  # interval | daily
    interval_seconds: int | None = None
    daily_time: time | None = None
    weekdays: tuple[int, ...] | None = None  # ISO weekday numbers 1..7
    time_zone: str = "Asia/Kolkata"
    payload: dict[str, Any] | None = None
    enabled_in_dev: bool = True
