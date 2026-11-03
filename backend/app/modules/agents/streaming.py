"""Run progress over Server-Sent Events (ADR-050 spike, implemented in Slice 3).

``GET /api/v1/agents/runs/{run_id}/events`` streams the same ``RunDetail`` payload the polling endpoint returns,
one ``event: run`` per change (new steps or a status change) and a final ``event: done`` with the finished run
(text and cards). Event ids are the last step sequence, so a reconnect with ``Last-Event-ID`` (or ``after_seq``)
resumes without duplicates. A comment heartbeat keeps proxies from closing an idle stream; the stream ends after
``MAX_STREAM_SECONDS`` and the client falls back to polling.

Each poll of the run opens its own short unit of work as the requesting member (own scope, RLS), so a stream
never holds a transaction or a connection between ticks.

Headers: ``Cache-Control: no-cache, no-transform`` (no proxy compression or caching, which would buffer the
stream), ``X-Accel-Buffering: no`` and ``Connection: keep-alive``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator

from app.modules.agents import service
from app.modules.agents.schemas import RunDetail
from app.platform.authz.context import ActorContext
from app.platform.uow import UnitOfWork

POLL_SECONDS = 0.4
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 120.0
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
MEDIA_TYPE = "text/event-stream"


def check_access(actor: ActorContext, run_id: uuid.UUID) -> None:
    """Resolve the run once before streaming so an invisible run is a plain 404, not an error event."""
    with UnitOfWork(actor) as uow:
        service.own_run(uow, run_id)


def _detail(actor: ActorContext, run_id: uuid.UUID, after_seq: int) -> RunDetail:
    with UnitOfWork(actor) as uow:
        return service.get_run(uow, run_id, after_seq=after_seq)


def format_event(event: str, data: str, event_id: int | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


def run_events(
    actor: ActorContext, run_id: uuid.UUID, *, after_seq: int = 0, poll_seconds: float = POLL_SECONDS,
    max_seconds: float = MAX_STREAM_SECONDS, sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    started = last_beat = clock()
    last_status: str | None = None
    yield "retry: 2000\n\n"
    while True:
        detail = _detail(actor, run_id, after_seq)
        changed = bool(detail.steps) or detail.run.status != last_status
        if detail.done:
            yield format_event("done", detail.model_dump_json(), detail.last_seq)
            return
        if changed:
            yield format_event("run", detail.model_dump_json(), detail.last_seq)
            after_seq, last_status = detail.last_seq, detail.run.status
            last_beat = clock()
        now = clock()
        if now - started > max_seconds:
            yield format_event("timeout", json.dumps({"run_id": str(run_id), "last_seq": after_seq}), after_seq)
            return
        if now - last_beat >= HEARTBEAT_SECONDS:
            yield ": ping\n\n"
            last_beat = now
        sleep(poll_seconds)


def resume_seq(after_seq: int, last_event_id: str | None) -> int:
    """``Last-Event-ID`` wins over the query parameter (browser reconnect)."""
    if last_event_id and last_event_id.strip().isdigit():
        return max(after_seq, int(last_event_id.strip()))
    return after_seq


__all__ = ["MEDIA_TYPE", "SSE_HEADERS", "check_access", "format_event", "resume_seq", "run_events"]
