"""The worker loop: outbox relay, scheduler, lease reaper and job execution (thread pool).

Polling only (no LISTEN/NOTIFY): adaptive 0.5–2 s. ``drain()`` runs the same steps inline for tests
and CLI one-shots, so integration tests observe outbox and job effects without a live worker.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.db.engine import session_factory
from app.core.logging import get_logger
from app.platform.events.service import relay_batch
from app.platform.jobs import runtime
from app.platform.jobs.models import WorkerHeartbeat
from app.platform.jobs.scheduler import enqueue_due, sync_schedules

log = get_logger("lk.worker")
DEFAULT_QUEUES = ["default", "events", "documents", "imports", "channels", "ai", "briefings"]
VERSION = "0.1.0"


def _tx(fn):  # type: ignore[no-untyped-def]
    with session_factory()() as session, session.begin():
        return fn(session)


def drain(*, queues: list[str] | None = None, max_rounds: int = 50, worker_id: str = "inline") -> int:
    """Relay events, run due schedules and execute every runnable job until quiescent."""
    queues = queues or DEFAULT_QUEUES
    executed = 0
    for _ in range(max_rounds):
        relayed = _tx(lambda s: relay_batch(s))
        jobs = _tx(lambda s: runtime.claim(s, worker_id, queues, limit=20))
        for job in jobs:
            runtime.execute(job, worker_id)
            executed += 1
        if not relayed and not jobs:
            break
    return executed


class Worker:
    def __init__(self, queues: list[str] | None = None, concurrency: int = 4) -> None:
        self.queues = queues or DEFAULT_QUEUES
        self.concurrency = concurrency
        self.worker_id = runtime.default_worker_id()
        self.stop_event = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="lk-job")
        self.running = 0
        self._lock = threading.Lock()

    def beat(self) -> None:
        now = get_clock().now()

        def write(s):  # type: ignore[no-untyped-def]
            stmt = pg_insert(WorkerHeartbeat).values(
                worker_id=self.worker_id,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                version=VERSION,
                queues=self.queues,
                started_at=now,
                last_beat_at=now,
                running=self.running,
            )
            s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["worker_id"], set_={"last_beat_at": now, "running": self.running}
                )
            )

        _tx(write)

    def _run_job(self, job) -> None:  # type: ignore[no-untyped-def]
        try:
            runtime.execute(job, self.worker_id)
        finally:
            with self._lock:
                self.running -= 1

    def run(self) -> None:
        from app.registry import get_registry

        registry = get_registry()
        _tx(lambda s: sync_schedules(s, list(registry.schedules.values()), dev=not get_settings().is_production))
        log.info("worker.started", worker_id=self.worker_id, queues=self.queues, concurrency=self.concurrency)
        last_beat = last_sched = last_reap = 0.0
        idle_sleep = 0.5
        while not self.stop_event.is_set():
            now = time.monotonic()
            try:
                if now - last_beat > 10:
                    self.beat()
                    last_beat = now
                if now - last_sched > 15:
                    _tx(enqueue_due)
                    last_sched = now
                if now - last_reap > 30:
                    _tx(runtime.reap_expired_leases)
                    last_reap = now
                relayed = _tx(relay_batch)
                free = self.concurrency - self.running
                jobs = _tx(lambda s: runtime.claim(s, self.worker_id, self.queues, limit=free)) if free > 0 else []
                for job in jobs:
                    with self._lock:
                        self.running += 1
                    self.pool.submit(self._run_job, job)
                idle_sleep = 0.5 if (relayed or jobs) else min(idle_sleep * 1.5, 2.0)
            except Exception as exc:  # keep the loop alive; the DB may be restarting
                log.error("worker.loop_error", error=str(exc))
                idle_sleep = 2.0
            self.stop_event.wait(idle_sleep)
        log.info("worker.stopping", worker_id=self.worker_id)
        self.pool.shutdown(wait=True, cancel_futures=False)

    def stop(self, *_args: object) -> None:
        self.stop_event.set()


def main() -> None:
    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    worker = Worker()
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    worker.run()
